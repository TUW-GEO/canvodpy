"""Files read from a pinned URL in a GitHub repository.

A file is named by its raw file link, pinned to a commit or a tag::

    https://raw.githubusercontent.com/<account>/<repo>/<commit>/<path>
    https://raw.githubusercontent.com/<account>/<repo>/refs/tags/<tag>/<path>

A full commit hash is the only pin that never changes: a tag can be moved.

Fetched files are kept in a cache folder in the system's temporary
folder, one per kind of file and user. A cached file is used without a
new fetch, so a run works offline once the file was fetched; a file
whose tag was moved keeps its old cached copy until the cache is
emptied.

A file in a private repository needs a GitHub token in the environment
variable ``GH_TOKEN`` or ``GITHUB_TOKEN``. canvodpy stores no secrets
(ADR "Credentials come from the environment"). The token is only sent to
``raw.githubusercontent.com``, never to the target of a redirect, and
never appears in messages or logs.

canvod-filemap reads naming recipes with this module; canvodpy reads a
settings file given as a URL with it.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

#: The only host files are read from.
PINNED_HOST = "raw.githubusercontent.com"

#: Environment variables a GitHub token is read from, in this order.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")

#: Largest file accepted, in bytes, unless the caller sets another limit.
MAX_BYTES = 1_000_000

#: Where downloads go: the URL's path is appended. Tests point it to a
#: local HTTP server.
_DOWNLOAD_ORIGIN = f"https://{PINNED_HOST}"

_COMMIT = re.compile(r"[0-9a-f]{40}")

# A token is one word of visible ASCII characters.
_TOKEN = re.compile(r"[\x21-\x7e]+")

# A kind of cached file names its cache folder.
_KIND = re.compile(r"[a-z][a-z0-9-]*")


class PinnedFileError(Exception):
    """A pinned URL that cannot be used."""


class PinnedURLError(PinnedFileError, ValueError):
    """A URL that is not a raw file link pinned to a commit or a tag."""


class PinnedFetchError(PinnedFileError):
    """A file that could not be fetched, or whose content was refused."""


@dataclass(frozen=True)
class PinnedURL:
    """A raw file link in a GitHub repository, pinned to a commit or a tag.

    Attributes
    ----------
    account : str
        The account (user or organization) that owns the repository.
    repo : str
        The repository.
    pin : str
        A 40-character commit hash, or ``refs/tags/<tag>``.
    path : str
        The file's path in the repository, without a leading ``/``.
    """

    account: str
    repo: str
    pin: str
    path: str

    @property
    def url(self) -> str:
        """The raw file link."""
        return (
            f"https://{PINNED_HOST}/{self.account}/{self.repo}/{self.pin}/{self.path}"
        )

    @property
    def commit(self) -> str | None:
        """The commit hash, or None if the URL is pinned to a tag."""
        return self.pin if _COMMIT.fullmatch(self.pin) else None

    @property
    def tag(self) -> str | None:
        """The tag, or None if the URL is pinned to a commit."""
        return self.pin.removeprefix("refs/tags/") if self.commit is None else None

    def sibling(self, relative: str) -> PinnedURL:
        """The file at ``relative`` from this file's folder, at the same pin.

        Parameters
        ----------
        relative : str
            A path relative to the folder of this file, with ``/`` between
            folders; ``..`` and absolute paths are refused.

        Returns
        -------
        PinnedURL
            The other file, in the same repository at the same pin.

        Raises
        ------
        PinnedURLError
            If ``relative`` is absolute or leaves the folder.
        """
        parts = PurePosixPath(relative).parts
        if not parts or relative.startswith("/") or ".." in parts:
            msg = f"Path {relative!r} must stay inside the folder of {self.url}"
            raise PinnedURLError(msg)
        folder = PurePosixPath(self.path).parent
        return PinnedURL(
            self.account, self.repo, self.pin, str(folder.joinpath(*parts))
        )


def is_url(value: str) -> bool:
    """Whether a setting is a URL rather than a name or a local path.

    Parameters
    ----------
    value : str
        The setting.

    Returns
    -------
    bool
        True for ``https://`` and ``http://`` values.
    """
    return value.lower().startswith(("https://", "http://"))


def parse_pinned_url(
    url: str,
    *,
    what: str = "file",
    suffixes: tuple[str, ...] = (".yaml", ".yml"),
) -> PinnedURL:
    """Check that ``url`` is a raw file link pinned to a commit or a tag.

    Parameters
    ----------
    url : str
        The URL.
    what : str
        What the file is, in lower case, for messages (``"recipe"``,
        ``"settings file"``).
    suffixes : tuple[str, ...]
        The file name endings accepted.

    Returns
    -------
    PinnedURL
        The parts of the URL.

    Raises
    ------
    PinnedURLError
        If the URL is not ``https``, holds a user name, password, query or
        fragment, points to a host other than ``raw.githubusercontent.com``
        (a ``github.com/.../blob/...`` link gets the matching raw link), is
        pinned to a branch or to a bare name that could be a branch, or
        its file does not end in one of ``suffixes``.
    """
    what_ = _upper(what)
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        msg = f"{what_} URL must start with https://: {url}"
        raise PinnedURLError(msg)
    if parts.username is not None or parts.password is not None:
        msg = (
            f"{what_} URL must not hold a user name or password; a token for a "
            f"private repository goes in {' or '.join(TOKEN_VARIABLES)}."
        )
        raise PinnedURLError(msg)
    if parts.query or parts.fragment:
        msg = (
            f"{what_} URL must not have a query ('?') or fragment ('#'): {_shown(url)}. "
            f"A token for a private repository goes in {' or '.join(TOKEN_VARIABLES)}."
        )
        raise PinnedURLError(msg)
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    if host == "github.com" and len(segments) > 3 and segments[2] == "blob":
        raw = f"https://{PINNED_HOST}/" + "/".join(segments[:2] + segments[3:])
        msg = f"{what_} URL is a GitHub page, not the file. Use the raw link: {raw}"
        raise PinnedURLError(msg)
    if host != PINNED_HOST:
        msg = f"{what_} URL must be a raw file link on {PINNED_HOST}: {url}"
        raise PinnedURLError(msg)
    if len(segments) < 4:
        msg = f"{what_} URL must be <account>/<repo>/<commit or refs/tags/tag>/<file>: {url}"
        raise PinnedURLError(msg)
    ref = segments[2]
    if _COMMIT.fullmatch(ref):
        pin, file_segments = ref, segments[3:]
    elif ref == "refs" and segments[3] == "tags" and len(segments) > 5:
        pin, file_segments = "/".join(segments[2:5]), segments[5:]
    else:
        branch = segments[4] if ref == "refs" and segments[3] == "heads" else ref
        base = f"https://{PINNED_HOST}/{segments[0]}/{segments[1]}"
        msg = (
            f"{what_} URL must be pinned to a full commit hash or a tag, not '{branch}': "
            f"{url}\nUse {base}/<40-character commit>/... or "
            f"{base}/refs/tags/<tag>/... (a commit is the only pin that never changes)."
        )
        raise PinnedURLError(msg)
    if PurePosixPath(file_segments[-1]).suffix not in suffixes:
        msg = f"{what_} URL must point to a {' or '.join(suffixes)} file: {url}"
        raise PinnedURLError(msg)
    return PinnedURL(segments[0], segments[1], pin, "/".join(file_segments))


def cache_dir(kind: str) -> Path:
    """The cache folder of one kind of fetched file, created if missing.

    ``<system temp folder>/canvodpy-<kind>-<user id>`` on Linux and macOS,
    readable by its owner only. On Windows the temporary folder already
    belongs to the user, so it is ``<temp folder>/canvodpy-<kind>``.

    Parameters
    ----------
    kind : str
        The kind of file, lower case letters, digits and ``-``
        (``"recipes"``, ``"settings"``).

    Returns
    -------
    Path
        The cache folder.

    Raises
    ------
    ValueError
        If ``kind`` is not lower case letters, digits and ``-``.
    PinnedFetchError
        On Linux and macOS, if the folder is a link, belongs to another
        user or can be read by others (on a shared ``/tmp``, another user
        could otherwise place a file there).
    """
    if not _KIND.fullmatch(kind):
        msg = f"Cache kind must be lower case letters, digits and '-': {kind!r}"
        raise ValueError(msg)
    getuid = getattr(os, "getuid", None)
    if getuid is None:  # Windows: no owner ids; the temp folder is per user
        path = Path(tempfile.gettempdir()) / f"canvodpy-{kind}"
        path.mkdir(exist_ok=True)
        return path
    path = Path(tempfile.gettempdir()) / f"canvodpy-{kind}-{getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != getuid()
        or info.st_mode & 0o077
    ):
        msg = (
            f"Cache folder {path} is not a folder that only you can "
            "read and write. Remove it; it is created again."
        )
        raise PinnedFetchError(msg)
    return path


def fetch_pinned(
    url: str,
    *,
    kind: str,
    what: str = "file",
    check: Callable[[bytes], None] | None = None,
    suffixes: tuple[str, ...] = (".yaml", ".yml"),
    max_bytes: int = MAX_BYTES,
    timeout: float = 30.0,
) -> Path:
    """The local file of the file at ``url``, fetched if not cached.

    The URL is checked with :func:`parse_pinned_url`. A cached copy is
    used if its content still has the sha256 it was stored with.
    Otherwise the file is fetched and given to ``check``; only if
    ``check`` returns is it cached.

    Parameters
    ----------
    url : str
        The URL.
    kind : str
        The kind of file; names the cache folder (:func:`cache_dir`).
    what : str
        What the file is, in lower case, for messages.
    check : Callable[[bytes], None] | None
        Called with the fetched bytes; raises if the content is refused.
    suffixes : tuple[str, ...]
        The file name endings accepted.
    max_bytes : int
        Largest file accepted.
    timeout : float
        Seconds to wait for the server.

    Returns
    -------
    Path
        The cached file. Its name ends in the sha256 of its content and the
        URL's file ending.

    Raises
    ------
    PinnedURLError
        If the URL is not a pinned raw file link.
    PinnedFetchError
        If the file cannot be fetched (not found, no access, a token that
        is not a token, no network and not cached, timeout), is larger than
        ``max_bytes``, or the cached copy changed.
    """
    parsed = parse_pinned_url(url, what=what, suffixes=suffixes)
    suffix = PurePosixPath(parsed.path).suffix
    folder = cache_dir(kind)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = sorted(folder.glob(f"{key}-*{suffix}"))
    if len(cached) > 1:
        msg = (
            f"{_upper(what)} {url} has more than one cached copy (its tag was moved "
            f"while it was fetched). Remove {folder}; it is created again."
        )
        raise PinnedFetchError(msg)
    if cached:
        path = cached[0]
        if _sha256(path) != path.stem.removeprefix(f"{key}-"):
            msg = f"Cached copy of {what} {url} changed: {path}. Remove it to fetch it again."
            raise PinnedFetchError(msg)
        return path
    data = _download(url, what=what, max_bytes=max_bytes, timeout=timeout)
    if check is not None:
        check(data)
    path = folder / f"{key}-{hashlib.sha256(data).hexdigest()}{suffix}"
    # Written to a new file and renamed: parallel runs may fetch the same URL.
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        # Windows refuses to replace a file another process has open. The
        # name holds the content's sha256, so an existing file is the same
        # file, written by a parallel fetch.
        if isinstance(exc, PermissionError) and path.exists():
            return path
        msg = f"Cannot write the cached {what} {path}: {exc}"
        raise PinnedFetchError(msg) from exc
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _upper(what: str) -> str:
    return what[:1].upper() + what[1:]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _shown(url: str) -> str:
    """``url`` without its query and fragment, for messages."""
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()


def _token() -> str | None:
    """The GitHub token from the environment, or None.

    Raises
    ------
    PinnedFetchError
        If the variable holds something that cannot be a token, such as
        the help text of a command that failed. The value is not shown.
    """
    for name in TOKEN_VARIABLES:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        if not _TOKEN.fullmatch(value):
            msg = (
                f"The environment variable {name} does not hold a GitHub token: "
                "it has spaces, line breaks or other characters a token never "
                f"has (its value is not shown). Set {name} to the token alone, "
                f"or unset it for a public repository."
            )
            raise PinnedFetchError(msg)
        return value
    return None


def _download(url: str, *, what: str, max_bytes: int, timeout: float) -> bytes:
    """The bytes of the file at ``url``; the token goes only to the first host."""
    request = urllib.request.Request(
        _DOWNLOAD_ORIGIN + urlsplit(url).path,
        headers={"User-Agent": "canvodpy"},
    )
    token = _token()
    if token:
        # Not forwarded when the server redirects (urllib copies other headers).
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        msg = (
            f"{_upper(what)} {url} could not be fetched: HTTP {exc.code} {exc.reason}."
        )
        if exc.code == 404:
            msg = f"{_upper(what)} not found: {url}."
            if token is None:
                msg += (
                    f" A {what} in a private repository needs a GitHub token in "
                    f"{' or '.join(TOKEN_VARIABLES)}."
                )
            else:
                msg += (
                    " If the repository is private, check that the token can read it."
                )
        elif exc.code in (401, 403) and token is not None:
            msg += " The token was refused, or GitHub limits the requests; try again later."
        elif exc.code in (401, 403, 429):
            msg += " GitHub limits the requests; try again later."
        raise PinnedFetchError(msg) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        msg = (
            f"{_upper(what)} {url} could not be fetched ({reason}) and is not in the "
            f"cache. A run without network access needs the {what} fetched once before."
        )
        raise PinnedFetchError(msg) from None
    if len(data) > max_bytes:
        msg = f"{_upper(what)} {url} is larger than {max_bytes} bytes; it is not a {what}."
        raise PinnedFetchError(msg)
    return data
