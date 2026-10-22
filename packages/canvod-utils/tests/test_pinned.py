"""Files read from a pinned URL (canvod.utils.pinned).

Downloads go to a local HTTP server, never to the network: the URLs stay
``https://raw.githubusercontent.com/...`` links and
``pinned._DOWNLOAD_ORIGIN`` sends the request to the server instead.
"""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import tempfile
import threading
from pathlib import Path

import pytest

from canvod.utils import pinned, testing
from canvod.utils.pinned import (
    PinnedFetchError,
    PinnedFileError,
    PinnedURL,
    PinnedURLError,
    cache_dir,
    fetch_pinned,
    is_url,
    parse_pinned_url,
)

COMMIT = testing.COMMIT
REPO = "the-inklings/red-book"
FILE = "config/canvod-settings.yaml"
COMMIT_URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{FILE}"
TAG_URL = f"https://raw.githubusercontent.com/{REPO}/refs/tags/v1/{FILE}"
TOKEN = "ghp_madeUpTokenOfTheInklings"
BODY = b"processing:\n  metadata:\n    author: Tolkien\n"


def fetch(url: str, **kwargs) -> Path:
    return fetch_pinned(url, kind="settings", what="settings file", **kwargs)


def _closed_origin() -> str:
    """An origin nothing listens on: a fetch from it fails like no network."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cache in tmp_path, no token from the user's environment."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in pinned.TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    srv = testing.PinnedFileServer()
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", srv.origin)
    yield srv
    srv.close()


def _cache_files() -> list[Path]:
    return sorted(cache_dir("settings").iterdir())


# ---------------------------------------------------------------------------
# URL check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (COMMIT_URL, True),
        ("HTTPS://raw.githubusercontent.com/a/b/c.yaml", True),
        ("http://raw.githubusercontent.com/a/b/c.yaml", True),
        ("fangorn_canopy", False),
        ("config/canvod-settings.yaml", False),
    ],
)
def test_is_url(value: str, expected: bool) -> None:
    assert is_url(value) is expected


def test_commit_url_parts() -> None:
    url = parse_pinned_url(COMMIT_URL)
    assert url == PinnedURL("the-inklings", "red-book", COMMIT, FILE)
    assert url.commit == COMMIT
    assert url.tag is None
    assert url.url == COMMIT_URL


def test_tag_url_parts() -> None:
    url = parse_pinned_url(TAG_URL)
    assert url.pin == "refs/tags/v1"
    assert url.commit is None
    assert url.tag == "v1"
    assert url.url == TAG_URL


@pytest.mark.parametrize("base", [COMMIT_URL, TAG_URL])
def test_sibling_keeps_the_pin(base: str) -> None:
    recipe = parse_pinned_url(base).sibling("recipes/fangorn/fangorn_canopy.yaml")
    assert recipe.url == base.replace(
        "canvod-settings.yaml", "recipes/fangorn/fangorn_canopy.yaml"
    )


@pytest.mark.parametrize(
    "relative", ["../secrets.yaml", "/etc/x.yaml", "a/../../b.yaml", ""]
)
def test_sibling_stays_in_the_folder(relative: str) -> None:
    with pytest.raises(PinnedURLError, match="inside the folder"):
        parse_pinned_url(COMMIT_URL).sibling(relative)


@pytest.mark.parametrize(
    ("url", "named"),
    [
        (f"https://raw.githubusercontent.com/{REPO}/main/{FILE}", "'main'"),
        (f"https://raw.githubusercontent.com/{REPO}/v1/{FILE}", "'v1'"),
        (f"https://raw.githubusercontent.com/{REPO}/refs/heads/main/{FILE}", "'main'"),
        # a short commit hash could also be a branch name
        (
            f"https://raw.githubusercontent.com/{REPO}/{COMMIT[:7]}/{FILE}",
            f"'{COMMIT[:7]}'",
        ),
    ],
)
def test_branch_urls_are_refused_with_the_pinned_forms(url: str, named: str) -> None:
    with pytest.raises(PinnedURLError) as excinfo:
        parse_pinned_url(url, what="settings file")
    message = str(excinfo.value)
    assert message.startswith("Settings file URL must be pinned")
    assert named in message
    assert f"https://raw.githubusercontent.com/{REPO}/<40-character commit>/" in message
    assert f"https://raw.githubusercontent.com/{REPO}/refs/tags/<tag>/" in message


def test_blob_link_is_refused_with_the_raw_link() -> None:
    blob = f"https://github.com/{REPO}/blob/{COMMIT}/{FILE}"
    with pytest.raises(PinnedURLError, match="raw link") as excinfo:
        parse_pinned_url(blob)
    assert str(excinfo.value).endswith(COMMIT_URL)


@pytest.mark.parametrize(
    ("url", "match"),
    [
        (COMMIT_URL.replace("https://", "http://"), "https://"),
        (f"https://gitlab.com/{REPO}/{COMMIT}/{FILE}", "raw file link"),
        (
            f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/settings.txt",
            r"\.yaml or \.yml",
        ),
        (f"https://raw.githubusercontent.com/{REPO}/{COMMIT}", "<account>/<repo>"),
        (f"https://raw.githubusercontent.com/{REPO}/refs/tags/v1", "pinned"),
        (COMMIT_URL + "#L3", "fragment"),
    ],
)
def test_other_urls_are_refused(url: str, match: str) -> None:
    with pytest.raises(PinnedURLError, match=match):
        parse_pinned_url(url)


def test_url_with_a_user_or_password_is_refused_without_showing_it() -> None:
    url = COMMIT_URL.replace("https://", f"https://tolkien:{TOKEN}@")
    with pytest.raises(PinnedURLError, match="GH_TOKEN") as excinfo:
        parse_pinned_url(url)
    assert TOKEN not in str(excinfo.value)


def test_url_with_a_query_is_refused_without_showing_it() -> None:
    with pytest.raises(PinnedURLError, match="query") as excinfo:
        parse_pinned_url(f"{COMMIT_URL}?token={TOKEN}")
    message = str(excinfo.value)
    assert TOKEN not in message
    assert COMMIT_URL in message


def test_url_errors_are_value_errors() -> None:
    assert issubclass(PinnedURLError, ValueError)
    assert issubclass(PinnedURLError, PinnedFileError)
    assert issubclass(PinnedFetchError, PinnedFileError)


def test_a_refused_url_is_never_requested(server: testing.PinnedFileServer) -> None:
    with pytest.raises(PinnedURLError):
        fetch(f"https://raw.githubusercontent.com/{REPO}/main/{FILE}")
    assert server.requests == []


# ---------------------------------------------------------------------------
# Fetch and cache
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [COMMIT_URL, TAG_URL])
def test_fetched_file_is_cached(server: testing.PinnedFileServer, url: str) -> None:
    server.serve(url, BODY)
    path = fetch(url)
    assert path.read_bytes() == BODY
    assert path.parent == cache_dir("settings")
    assert path.suffix == ".yaml"
    assert hashlib.sha256(BODY).hexdigest() in path.name
    assert server.requests[0][0] == url.removeprefix(
        "https://raw.githubusercontent.com"
    )


def test_kinds_are_cached_apart(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    settings = fetch(COMMIT_URL)
    recipe = fetch_pinned(COMMIT_URL, kind="recipes")
    assert settings.parent != recipe.parent
    assert recipe.parent == cache_dir("recipes")


def test_cache_hit_needs_no_network(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(COMMIT_URL, BODY)
    first = fetch(COMMIT_URL)
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", _closed_origin())
    assert fetch(COMMIT_URL) == first
    assert len(server.requests) == 1


def test_cache_miss_without_network_names_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", _closed_origin())
    with pytest.raises(PinnedFetchError, match="not in the cache") as excinfo:
        fetch(COMMIT_URL)
    assert COMMIT_URL in str(excinfo.value)
    assert "settings file fetched once" in str(excinfo.value)
    assert _cache_files() == []


def test_cached_copy_that_changed_is_refused(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    path = fetch(COMMIT_URL)
    path.write_bytes(BODY + b"# changed\n")
    with pytest.raises(PinnedFetchError, match="changed"):
        fetch(COMMIT_URL)


def test_two_cached_copies_of_one_url_are_refused(
    server: testing.PinnedFileServer,
) -> None:
    server.serve(TAG_URL, BODY)
    path = fetch(TAG_URL)
    moved = BODY + b"# moved tag\n"
    key = path.name.split("-")[0]
    (path.parent / f"{key}-{hashlib.sha256(moved).hexdigest()}.yaml").write_bytes(moved)
    with pytest.raises(PinnedFetchError, match="more than one cached copy"):
        fetch(TAG_URL)


def test_refused_replace_keeps_a_parallel_copy(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What Windows does when a parallel fetch holds the cached file open.
    server.serve(COMMIT_URL, BODY)

    def replace(src: str, dst: str) -> None:
        Path(dst).write_bytes(BODY)  # the parallel fetch's copy
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(pinned.os, "replace", replace)
    path = fetch(COMMIT_URL)
    assert path.read_bytes() == BODY
    assert _cache_files() == [path]


def test_refused_replace_without_a_copy_is_a_fetch_error(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(COMMIT_URL, BODY)

    def replace(src: str, dst: str) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(pinned.os, "replace", replace)
    with pytest.raises(PinnedFetchError, match="Cannot write the cached settings file"):
        fetch(COMMIT_URL)
    assert _cache_files() == []


def test_parallel_fetches_leave_one_complete_copy(
    server: testing.PinnedFileServer,
) -> None:
    server.serve(COMMIT_URL, BODY)
    paths: list[Path] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            paths.append(fetch(COMMIT_URL))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(set(paths)) == 1
    assert [p.name for p in _cache_files()] == [paths[0].name]


# ---------------------------------------------------------------------------
# Content: nothing is cached unless the check passes
# ---------------------------------------------------------------------------


def test_refused_content_is_not_cached(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY)

    def check(data: bytes) -> None:
        raise PinnedFetchError("not a settings file")

    with pytest.raises(PinnedFetchError, match="not a settings file"):
        fetch(COMMIT_URL, check=check)
    assert _cache_files() == []


def test_check_gets_the_served_bytes(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    seen: list[bytes] = []
    fetch(COMMIT_URL, check=seen.append)
    assert seen == [BODY]


def test_too_large_file_is_refused(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY + b"#" * 100)
    with pytest.raises(PinnedFetchError, match="larger than 100 bytes"):
        fetch(COMMIT_URL, max_bytes=100)
    assert _cache_files() == []


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def _authorization(headers: dict[str, str]) -> str | None:
    return {k.lower(): v for k, v in headers.items()}.get("authorization")


def test_no_token_sends_no_authorization(server: testing.PinnedFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    assert _authorization(server.requests[0][1]) is None


@pytest.mark.parametrize("variable", ["GH_TOKEN", "GITHUB_TOKEN"])
def test_token_is_sent(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, TOKEN)
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    assert _authorization(server.requests[0][1]) == f"Bearer {TOKEN}"


def test_gh_token_comes_first(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_otherToken")
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    assert _authorization(server.requests[0][1]) == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    "value",
    [
        # what an old gh without `gh auth token` prints into the variable
        'unknown command "token" for "gh auth"\n\nUsage:  gh auth <command> [flags]',
        f"{TOKEN} {TOKEN}",
        "tökén",
    ],
)
def test_a_token_that_is_not_a_token_is_named_not_shown(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GH_TOKEN", value)
    server.serve(COMMIT_URL, BODY)
    with pytest.raises(
        PinnedFetchError, match="GH_TOKEN does not hold a GitHub token"
    ) as exc:
        fetch(COMMIT_URL)
    assert value not in str(exc.value)
    assert server.requests == []


def test_a_bad_token_does_not_matter_for_a_cached_file(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(COMMIT_URL, BODY)
    first = fetch(COMMIT_URL)
    monkeypatch.setenv("GH_TOKEN", "not a token")
    assert fetch(COMMIT_URL) == first


def test_token_is_not_sent_to_a_redirect_target(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = testing.PinnedFileServer()
    try:
        target.serve(COMMIT_URL, BODY)
        path = COMMIT_URL.removeprefix("https://raw.githubusercontent.com")
        server.serve(COMMIT_URL, b"", status=302, Location=target.origin + path)
        monkeypatch.setenv("GH_TOKEN", TOKEN)
        fetch(COMMIT_URL)
    finally:
        target.close()
    assert _authorization(server.requests[0][1]) == f"Bearer {TOKEN}"
    assert len(target.requests) == 1
    assert _authorization(target.requests[0][1]) is None


def test_private_file_without_token_names_the_variables(
    server: testing.PinnedFileServer,
) -> None:
    with pytest.raises(PinnedFetchError, match="Settings file not found") as excinfo:
        fetch(COMMIT_URL)
    message = str(excinfo.value)
    assert COMMIT_URL in message
    assert "A settings file in a private repository" in message
    assert "GH_TOKEN or GITHUB_TOKEN" in message


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_token_never_appears_in_messages(
    server: testing.PinnedFileServer, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    server.serve(COMMIT_URL, b"no", status=status)
    with pytest.raises(PinnedFetchError) as excinfo:
        fetch(COMMIT_URL)
    assert TOKEN not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert f"HTTP {status}" in str(excinfo.value) or status == 404


@pytest.mark.parametrize(("status", "token"), [(403, None), (429, None), (401, TOKEN)])
def test_refused_requests_say_why(
    server: testing.PinnedFileServer,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    token: str | None,
) -> None:
    if token:
        monkeypatch.setenv("GH_TOKEN", token)
    server.serve(COMMIT_URL, b"no", status=status)
    with pytest.raises(PinnedFetchError, match="try again later"):
        fetch(COMMIT_URL)


# ---------------------------------------------------------------------------
# Cache folder
# ---------------------------------------------------------------------------

posix_only = pytest.mark.skipif(
    not hasattr(os, "getuid"), reason="owner check is POSIX only"
)


@pytest.mark.parametrize("kind", ["", "Settings", "../x", "a b"])
def test_cache_kind_is_checked(kind: str) -> None:
    with pytest.raises(ValueError, match="Cache kind"):
        cache_dir(kind)


@posix_only
def test_cache_folder_is_private_to_the_user(tmp_path: Path) -> None:
    folder = cache_dir("recipes")
    assert folder == tmp_path / f"canvodpy-recipes-{os.getuid()}"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@posix_only
def test_cache_folder_others_can_read_is_refused() -> None:
    folder = cache_dir("settings")
    folder.chmod(0o755)
    with pytest.raises(PinnedFetchError, match=r"Remove it") as excinfo:
        cache_dir("settings")
    assert str(folder) in str(excinfo.value)


@posix_only
def test_cache_folder_that_is_a_link_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (tmp_path / f"canvodpy-settings-{os.getuid()}").symlink_to(elsewhere)
    with pytest.raises(PinnedFetchError, match="only you can"):
        cache_dir("settings")
