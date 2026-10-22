"""Files read from a raw file link in a GitHub repository.

A file is named by its raw file link, at a commit, a tag or a branch::

    https://raw.githubusercontent.com/<account>/<repo>/<commit>/<path>
    https://raw.githubusercontent.com/<account>/<repo>/refs/tags/<tag>/<path>
    https://raw.githubusercontent.com/<account>/<repo>/refs/heads/<branch>/<path>

The user is responsible for what the link points to. Each run fetches
the file again; there is no cache. A run fetches a link once, into a
folder of the run (:func:`run_folder`) that only its owner can read and
that is removed when the run ends; the run's worker processes read the
same file, so every part of a run sees the same content.

A file in a private repository needs a GitHub token in the environment
variable ``GH_TOKEN`` or ``GITHUB_TOKEN``. canvodpy stores no secrets
(ADR "Credentials come from the environment"). The token is only sent to
``raw.githubusercontent.com``, never to the target of a redirect, and
never appears in messages or logs.

A link is shown in the terminal (``canvodpy doctor``, error messages) but
never recorded: stores and the run history get only its file name
(:func:`recorded_name`, :func:`without_urls`).

canvod-filemap reads naming recipes with this module; canvodpy reads a
settings file given as a URL with it.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.util import Finalize
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

#: The only host files are read from.
REMOTE_HOST = "raw.githubusercontent.com"

#: Environment variables a GitHub token is read from, in this order.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")

#: Largest file accepted, in bytes, unless the caller sets another limit.
MAX_BYTES = 1_000_000

#: Where downloads go: the URL's path is appended. Tests point it to a
#: local HTTP server.
_DOWNLOAD_ORIGIN = f"https://{REMOTE_HOST}"

# A token is one word of visible ASCII characters.
_TOKEN = re.compile(r"[\x21-\x7e]+")

# A link inside a text, for :func:`without_urls`.
_URL_IN_TEXT = re.compile(r"https?://[^\s'\"<>()]+", re.IGNORECASE)

# Names the run folder for the worker processes of a run.
_RUN_FOLDER_VARIABLE = "CANVODPY_RUN_FOLDER"

# The run folder of this process.
_FOLDER: Path | None = None
_LOCK = threading.Lock()


class RemoteFileError(Exception):
    """A file link that cannot be used."""


class RemoteURLError(RemoteFileError, ValueError):
    """A URL that is not a raw file link in a GitHub repository."""


class RemoteFetchError(RemoteFileError):
    """A file that could not be fetched, or whose content was refused."""


@dataclass(frozen=True)
class RemoteURL:
    """A raw file link in a GitHub repository.

    Attributes
    ----------
    path : str
        The URL's path without the leading ``/``:
        ``<account>/<repo>/<commit, refs/tags/tag or branch>/<file path>``.
    """

    path: str

    @property
    def url(self) -> str:
        """The raw file link."""
        return f"https://{REMOTE_HOST}/{self.path}"

    @property
    def name(self) -> str:
        """The file name, the only part of the link that is recorded."""
        return PurePosixPath(self.path).name

    def sibling(self, relative: str) -> RemoteURL:
        """The file at ``relative`` from this file's folder, at the same link.

        Parameters
        ----------
        relative : str
            A path relative to the folder of this file, with ``/`` between
            folders; ``..`` and absolute paths are refused.

        Returns
        -------
        RemoteURL
            The other file, in the same repository at the same commit, tag
            or branch.

        Raises
        ------
        RemoteURLError
            If ``relative`` is absolute or leaves the folder.
        """
        parts = PurePosixPath(relative).parts
        if not parts or relative.startswith("/") or ".." in parts:
            msg = f"Path {relative!r} must stay inside the folder of {self.url}"
            raise RemoteURLError(msg)
        folder = PurePosixPath(self.path).parent
        return RemoteURL(str(folder.joinpath(*parts)))


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


def recorded_name(value: str) -> str:
    """The form of a setting that may be recorded: a URL's file name.

    Parameters
    ----------
    value : str
        A setting: a URL, a name or a local path.

    Returns
    -------
    str
        The file name of a URL (``ROSA_canopy.yaml``), its host if it has
        no path; any other value unchanged.
    """
    if not is_url(value):
        return value
    parts = urlsplit(value)
    return PurePosixPath(parts.path).name or (parts.hostname or "")


def without_urls(text: str) -> str:
    """``text`` with each ``http(s)`` link replaced by its file name.

    For text that is recorded, such as an error kept in the run history.
    Every link is replaced, not only raw file links: a message about a
    refused link quotes it in other forms too (a GitHub page, another
    host).

    Parameters
    ----------
    text : str
        Any text.

    Returns
    -------
    str
        The text, each link replaced by its file name
        (:func:`recorded_name`).
    """
    return _URL_IN_TEXT.sub(lambda m: recorded_name(m.group(0)), text)


def parse_remote_url(
    url: str,
    *,
    what: str = "file",
    suffixes: tuple[str, ...] = (".yaml", ".yml"),
) -> RemoteURL:
    """Check that ``url`` is a raw file link in a GitHub repository.

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
    RemoteURL
        The URL's path.

    Raises
    ------
    RemoteURLError
        If the URL is not ``https``, holds a user name, password, query or
        fragment, points to a host other than ``raw.githubusercontent.com``
        (a ``github.com/.../blob/...`` link gets the matching raw link), has
        no ``<account>/<repo>/<commit, tag or branch>/<file>`` path, or its
        file does not end in one of ``suffixes``.
    """
    what_ = _upper(what)
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        msg = f"{what_} URL must start with https://: {url}"
        raise RemoteURLError(msg)
    if parts.username is not None or parts.password is not None:
        msg = (
            f"{what_} URL must not hold a user name or password; a token for a "
            f"private repository goes in {' or '.join(TOKEN_VARIABLES)}."
        )
        raise RemoteURLError(msg)
    if parts.query or parts.fragment:
        msg = (
            f"{what_} URL must not have a query ('?') or fragment ('#'): {_shown(url)}. "
            f"A token for a private repository goes in {' or '.join(TOKEN_VARIABLES)}."
        )
        raise RemoteURLError(msg)
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    if host == "github.com" and len(segments) > 3 and segments[2] == "blob":
        raw = f"https://{REMOTE_HOST}/" + "/".join(segments[:2] + segments[3:])
        msg = f"{what_} URL is a GitHub page, not the file. Use the raw link: {raw}"
        raise RemoteURLError(msg)
    if host != REMOTE_HOST:
        msg = f"{what_} URL must be a raw file link on {REMOTE_HOST}: {url}"
        raise RemoteURLError(msg)
    if len(segments) < 4:
        msg = (
            f"{what_} URL must be <account>/<repo>/<commit, tag or branch>/<file>: "
            f"{url}"
        )
        raise RemoteURLError(msg)
    if PurePosixPath(segments[-1]).suffix not in suffixes:
        msg = f"{what_} URL must point to a {' or '.join(suffixes)} file: {url}"
        raise RemoteURLError(msg)
    return RemoteURL("/".join(segments))


def run_folder() -> Path:
    """The folder of this run's fetched files, created if missing.

    A new folder in the system's temporary folder that only its owner can
    read, removed when the process that made it ends. Worker processes
    started after it was made use the same folder (it is named in the
    environment variable ``CANVODPY_RUN_FOLDER``), so they fetch into it
    and leave its removal to the run.

    Returns
    -------
    Path
        The folder.
    """
    global _FOLDER
    with _LOCK:
        if _FOLDER is not None and _FOLDER.is_dir():
            return _FOLDER
        inherited = os.environ.get(_RUN_FOLDER_VARIABLE)
        if inherited and Path(inherited).is_dir():
            _FOLDER = Path(inherited)
            return _FOLDER
        _FOLDER = Path(tempfile.mkdtemp(prefix="canvodpy-"))
        os.environ[_RUN_FOLDER_VARIABLE] = str(_FOLDER)
        # A multiprocessing finalizer runs only in the process that made
        # the folder, also in a worker process, which ends without atexit.
        Finalize(
            None,
            shutil.rmtree,
            args=(_FOLDER,),
            kwargs={"ignore_errors": True},
            exitpriority=0,
        )
        return _FOLDER


def fetch_remote(
    url: str,
    *,
    what: str = "file",
    check: Callable[[bytes], None] | None = None,
    suffixes: tuple[str, ...] = (".yaml", ".yml"),
    max_bytes: int = MAX_BYTES,
    timeout: float = 30.0,
) -> Path:
    """The local file of the file at ``url``, fetched once per run.

    The URL is checked with :func:`parse_remote_url`. If the run already
    fetched it, in this process or another process of the run, that file
    is returned. Otherwise the file is fetched and given to ``check``; only
    if ``check`` returns is it written into :func:`run_folder`.

    Parameters
    ----------
    url : str
        The URL.
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
        The local file, with the URL's file name.

    Raises
    ------
    RemoteURLError
        If the URL is not a raw file link.
    RemoteFetchError
        If the file cannot be fetched (not found, no access, a token that
        is not a token, no network, timeout) or is larger than
        ``max_bytes``.
    """
    remote = parse_remote_url(url, what=what, suffixes=suffixes)
    folder = run_folder() / hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    path = folder / remote.name
    if path.is_file():
        return path
    data = _download(url, what=what, max_bytes=max_bytes, timeout=timeout)
    if check is not None:
        check(data)
    folder.mkdir(exist_ok=True)
    # Written to a new file and renamed: processes of a run may fetch the
    # same URL at once, and a reader never sees half a file.
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        # Windows refuses to replace a file another process has open: that
        # file is the one a parallel fetch of this run wrote.
        if isinstance(exc, PermissionError) and path.is_file():
            return path
        msg = f"Cannot write the fetched {what} {path}: {exc}"
        raise RemoteFetchError(msg) from exc
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _upper(what: str) -> str:
    return what[:1].upper() + what[1:]


def _shown(url: str) -> str:
    """``url`` without its query and fragment, for messages."""
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()


def _token() -> str | None:
    """The GitHub token from the environment, or None.

    Raises
    ------
    RemoteFetchError
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
            raise RemoteFetchError(msg)
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
        raise RemoteFetchError(msg) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        msg = (
            f"{_upper(what)} {url} could not be fetched ({reason}). Each run "
            "fetches it, so a run needs network access."
        )
        raise RemoteFetchError(msg) from None
    if len(data) > max_bytes:
        msg = f"{_upper(what)} {url} is larger than {max_bytes} bytes; it is not a {what}."
        raise RemoteFetchError(msg)
    return data
