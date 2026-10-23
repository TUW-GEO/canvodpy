"""Files read from a raw file link (canvod.utils.remote_file).

Downloads go to a local HTTP server, never to the network: the URLs stay
``https://raw.githubusercontent.com/...`` links and
``remote_file._DOWNLOAD_ORIGIN`` sends the request to the server instead.
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

import pytest

from canvod.utils import remote_file, testing
from canvod.utils.remote_file import (
    RemoteFetchError,
    RemoteFileError,
    RemoteURL,
    RemoteURLError,
    fetch_remote,
    is_url,
    new_run,
    parse_remote_url,
    recorded_name,
    run_folder,
    without_urls,
)

COMMIT = testing.COMMIT
REPO = "the-inklings/red-book"
FILE = "config/canvod-settings.yaml"
COMMIT_URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{FILE}"
TAG_URL = f"https://raw.githubusercontent.com/{REPO}/refs/tags/v1/{FILE}"
BRANCH_URL = f"https://raw.githubusercontent.com/{REPO}/main/{FILE}"
TOKEN = "ghp_madeUpTokenOfTheInklings"
BODY = b"processing:\n  metadata:\n    author: Tolkien\n"


def fetch(url: str, **kwargs) -> Path:
    return fetch_remote(url, what="settings file", **kwargs)


def fresh_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start a new run: a new run folder, nothing fetched yet.

    The variable is set (empty) through monkeypatch, so the value
    run_folder() writes is undone after the test.
    """
    monkeypatch.setattr(remote_file, "_FOLDER", None)
    monkeypatch.setattr(remote_file, "_MADE_HERE", False)
    monkeypatch.setenv("CANVODPY_RUN_FOLDER", "")


def _closed_origin() -> str:
    """An origin nothing listens on: a fetch from it fails like no network."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A new run with its folders in tmp_path, no token."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    fresh_run(monkeypatch)
    for name in remote_file.TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    srv = testing.RemoteFileServer()
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", srv.origin)
    yield srv
    srv.close()


def _fetched_files() -> list[Path]:
    return sorted(p for p in run_folder().rglob("*") if p.is_file())


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


@pytest.mark.parametrize("url", [COMMIT_URL, TAG_URL, BRANCH_URL])
def test_commit_tag_and_branch_links_are_accepted(url: str) -> None:
    remote = parse_remote_url(url)
    assert remote.url == url
    assert remote.name == "canvod-settings.yaml"


def test_url_parts() -> None:
    assert parse_remote_url(COMMIT_URL) == RemoteURL(f"{REPO}/{COMMIT}/{FILE}")


@pytest.mark.parametrize("base", [COMMIT_URL, TAG_URL, BRANCH_URL])
def test_sibling_keeps_the_link(base: str) -> None:
    recipe = parse_remote_url(base).sibling("recipes/fangorn/fangorn_canopy.yaml")
    assert recipe.url == base.replace(
        "canvod-settings.yaml", "recipes/fangorn/fangorn_canopy.yaml"
    )


@pytest.mark.parametrize(
    "relative", ["../secrets.yaml", "/etc/x.yaml", "a/../../b.yaml", ""]
)
def test_sibling_stays_in_the_folder(relative: str) -> None:
    with pytest.raises(RemoteURLError, match="inside the folder"):
        parse_remote_url(COMMIT_URL).sibling(relative)


def test_blob_link_is_refused_with_the_raw_link() -> None:
    blob = f"https://github.com/{REPO}/blob/{COMMIT}/{FILE}"
    with pytest.raises(RemoteURLError, match="raw link") as excinfo:
        parse_remote_url(blob)
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
        (COMMIT_URL + "#L3", "fragment"),
    ],
)
def test_other_urls_are_refused(url: str, match: str) -> None:
    with pytest.raises(RemoteURLError, match=match):
        parse_remote_url(url)


def test_url_with_a_user_or_password_is_refused_without_showing_it() -> None:
    url = COMMIT_URL.replace("https://", f"https://tolkien:{TOKEN}@")
    with pytest.raises(RemoteURLError, match="GH_TOKEN") as excinfo:
        parse_remote_url(url)
    assert TOKEN not in str(excinfo.value)


def test_url_with_a_query_is_refused_without_showing_it() -> None:
    with pytest.raises(RemoteURLError, match="query") as excinfo:
        parse_remote_url(f"{COMMIT_URL}?token={TOKEN}")
    message = str(excinfo.value)
    assert TOKEN not in message
    assert COMMIT_URL in message


def test_url_errors_are_value_errors() -> None:
    assert issubclass(RemoteURLError, ValueError)
    assert issubclass(RemoteURLError, RemoteFileError)
    assert issubclass(RemoteFetchError, RemoteFileError)


def test_a_refused_url_is_never_requested(server: testing.RemoteFileServer) -> None:
    with pytest.raises(RemoteURLError):
        fetch(f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/settings.txt")
    assert server.requests == []


# ---------------------------------------------------------------------------
# What is recorded: the file name, never the link
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "recorded"),
    [
        (BRANCH_URL, "canvod-settings.yaml"),
        (TAG_URL, "canvod-settings.yaml"),
        # Any other link: only its host, since its path can name a repository.
        (f"https://github.com/{REPO}", "github.com"),
        (f"https://github.com/{REPO}/tree/main/config", "github.com"),
        (f"https://github.com/{REPO}/blob/main/{FILE}", "github.com"),
        ("https://cddis.nasa.gov/archive/gnss/products/x.sp3.gz", "cddis.nasa.gov"),
        ("fangorn_canopy", "fangorn_canopy"),
        ("config/recipes/x.yaml", "config/recipes/x.yaml"),
    ],
)
def test_recorded_name(value: str, recorded: str) -> None:
    assert recorded_name(value) == recorded


def test_links_in_a_text_become_file_names() -> None:
    text = f"Recipe not found: {BRANCH_URL}. Receiver 'canopy_01' ({TAG_URL})"
    assert without_urls(text) == (
        "Recipe not found: canvod-settings.yaml. "
        "Receiver 'canopy_01' (canvod-settings.yaml)"
    )


@pytest.mark.parametrize(
    "link",
    [
        f"https://github.com/{REPO}/blob/main/{FILE}",
        f"https://gitlab.com/{REPO}/-/raw/main/{FILE}",
        f"http://raw.githubusercontent.com/{REPO}/main/{FILE}",
    ],
)
def test_every_link_in_a_text_becomes_its_file_name(link: str) -> None:
    # A message about a refused link quotes it as given.
    with pytest.raises(RemoteURLError) as excinfo:
        parse_remote_url(link, what="recipe")
    recorded = without_urls(str(excinfo.value))
    assert "the-inklings" not in recorded
    assert "red-book" not in recorded


# ---------------------------------------------------------------------------
# Fetch: once per process, again in every new run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [COMMIT_URL, TAG_URL, BRANCH_URL])
def test_fetched_file_is_in_the_run_folder(
    server: testing.RemoteFileServer, url: str
) -> None:
    server.serve(url, BODY)
    path = fetch(url)
    assert path.read_bytes() == BODY
    assert path.name == "canvod-settings.yaml"
    assert run_folder() in path.parents
    assert server.requests[0][0] == url.removeprefix(
        "https://raw.githubusercontent.com"
    )


def test_a_process_fetches_a_link_once(server: testing.RemoteFileServer) -> None:
    server.serve(BRANCH_URL, BODY)
    first = fetch(BRANCH_URL)
    assert fetch(BRANCH_URL) == first
    assert len(server.requests) == 1


def test_every_run_fetches_again(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(BRANCH_URL, BODY)
    fetch(BRANCH_URL)
    changed = BODY + b"# the branch moved on\n"
    server.serve(BRANCH_URL, changed)
    fresh_run(monkeypatch)
    assert fetch(BRANCH_URL).read_bytes() == changed
    assert len(server.requests) == 2


def test_a_new_run_in_the_same_process_fetches_again(
    server: testing.RemoteFileServer,
) -> None:
    # A notebook that runs twice: the branch moved on between the runs.
    server.serve(BRANCH_URL, BODY)
    first = fetch(BRANCH_URL)
    changed = BODY + b"# the branch moved on\n"
    server.serve(BRANCH_URL, changed)
    folder = new_run()
    second = fetch(BRANCH_URL)
    assert second.read_bytes() == changed
    assert folder in second.parents
    assert not first.exists()  # the earlier run's folder is removed
    assert len(server.requests) == 2


def test_a_new_run_keeps_the_folder_of_the_settings_in_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # canvodpy -c URL: the settings fetched at the start of the command are
    # the configuration folder for the whole command.
    previous = run_folder()
    config_dir = previous / "config" / "fetched"
    config_dir.mkdir(parents=True)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    new_run()
    assert config_dir.is_dir()


def test_a_new_run_leaves_a_folder_of_another_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A worker process uses its run's folder; the run removes it.
    runs = tmp_path / "canvodpy-of-the-run"
    runs.mkdir()
    monkeypatch.setenv("CANVODPY_RUN_FOLDER", str(runs))
    assert run_folder() == runs
    new_run()
    assert runs.is_dir()


def test_no_network_names_the_url(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    fresh_run(monkeypatch)
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", _closed_origin())
    with pytest.raises(RemoteFetchError, match="needs network access") as excinfo:
        fetch(COMMIT_URL)
    assert COMMIT_URL in str(excinfo.value)


def test_refused_replace_keeps_a_parallel_copy(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What Windows does when a parallel fetch holds the file open.
    server.serve(COMMIT_URL, BODY)

    def replace(src: str, dst: str) -> None:
        Path(dst).write_bytes(BODY)  # the parallel fetch's copy
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(remote_file.os, "replace", replace)
    path = fetch(COMMIT_URL)
    assert path.read_bytes() == BODY
    assert _fetched_files() == [path]


def test_refused_replace_without_a_copy_is_a_fetch_error(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.serve(COMMIT_URL, BODY)

    def replace(src: str, dst: str) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(remote_file.os, "replace", replace)
    with pytest.raises(RemoteFetchError, match="Cannot write the fetched"):
        fetch(COMMIT_URL)
    assert _fetched_files() == []


def test_files_with_one_name_are_kept_apart(server: testing.RemoteFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    server.serve(BRANCH_URL, b"other: 1\n")
    assert fetch(COMMIT_URL).read_bytes() == BODY
    assert fetch(BRANCH_URL).read_bytes() == b"other: 1\n"


def test_parallel_fetches_give_complete_files(
    server: testing.RemoteFileServer,
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
    assert paths[0].read_bytes() == BODY


# ---------------------------------------------------------------------------
# Content: nothing is kept unless the check passes
# ---------------------------------------------------------------------------


def test_refused_content_is_not_kept(server: testing.RemoteFileServer) -> None:
    server.serve(COMMIT_URL, BODY)

    def check(data: bytes) -> None:
        raise RemoteFetchError("not a settings file")

    with pytest.raises(RemoteFetchError, match="not a settings file"):
        fetch(COMMIT_URL, check=check)
    assert _fetched_files() == []


def test_check_gets_the_served_bytes(server: testing.RemoteFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    seen: list[bytes] = []
    fetch(COMMIT_URL, check=seen.append)
    assert seen == [BODY]


def test_too_large_file_is_refused(server: testing.RemoteFileServer) -> None:
    server.serve(COMMIT_URL, BODY + b"#" * 100)
    with pytest.raises(RemoteFetchError, match="larger than 100 bytes"):
        fetch(COMMIT_URL, max_bytes=100)
    assert _fetched_files() == []


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def _authorization(headers: dict[str, str]) -> str | None:
    return {k.lower(): v for k, v in headers.items()}.get("authorization")


def test_no_token_sends_no_authorization(server: testing.RemoteFileServer) -> None:
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    assert _authorization(server.requests[0][1]) is None


@pytest.mark.parametrize("variable", ["GH_TOKEN", "GITHUB_TOKEN"])
def test_token_is_sent(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, TOKEN)
    server.serve(COMMIT_URL, BODY)
    fetch(COMMIT_URL)
    assert _authorization(server.requests[0][1]) == f"Bearer {TOKEN}"


def test_gh_token_comes_first(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
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
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GH_TOKEN", value)
    server.serve(COMMIT_URL, BODY)
    with pytest.raises(
        RemoteFetchError, match="GH_TOKEN does not hold a GitHub token"
    ) as exc:
        fetch(COMMIT_URL)
    assert value not in str(exc.value)
    assert server.requests == []


def test_token_is_not_sent_to_a_redirect_target(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = testing.RemoteFileServer()
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
    server: testing.RemoteFileServer,
) -> None:
    with pytest.raises(RemoteFetchError, match="Settings file not found") as excinfo:
        fetch(COMMIT_URL)
    message = str(excinfo.value)
    assert COMMIT_URL in message
    assert "A settings file in a private repository" in message
    assert "GH_TOKEN or GITHUB_TOKEN" in message


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_token_never_appears_in_messages(
    server: testing.RemoteFileServer, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    server.serve(COMMIT_URL, b"no", status=status)
    with pytest.raises(RemoteFetchError) as excinfo:
        fetch(COMMIT_URL)
    assert TOKEN not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert f"HTTP {status}" in str(excinfo.value) or status == 404


@pytest.mark.parametrize(("status", "token"), [(403, None), (429, None), (401, TOKEN)])
def test_refused_requests_say_why(
    server: testing.RemoteFileServer,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    token: str | None,
) -> None:
    if token:
        monkeypatch.setenv("GH_TOKEN", token)
    server.serve(COMMIT_URL, b"no", status=status)
    with pytest.raises(RemoteFetchError, match="try again later"):
        fetch(COMMIT_URL)


# ---------------------------------------------------------------------------
# The run folder
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file modes are POSIX only")
def test_run_folder_is_private_to_the_user() -> None:
    assert stat.S_IMODE(run_folder().stat().st_mode) == 0o700


def _run(script: str, tmp_path: Path) -> list[str]:
    path = tmp_path / "run.py"
    path.write_text(textwrap.dedent(script))
    env = {**os.environ, "TMPDIR": str(tmp_path), "TEMP": str(tmp_path)}
    env.pop("CANVODPY_RUN_FOLDER", None)
    result = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.split()


def test_run_folder_is_removed_when_the_run_ends(
    server: testing.RemoteFileServer, tmp_path: Path
) -> None:
    server.serve(COMMIT_URL, BODY)
    (folder,) = _run(
        f"""
        from canvod.utils import remote_file
        remote_file._DOWNLOAD_ORIGIN = {server.origin!r}
        print(remote_file.fetch_remote({COMMIT_URL!r}).parent.parent)
        """,
        tmp_path,
    )
    assert Path(folder).name.startswith("canvodpy-")
    assert not Path(folder).exists()


def test_workers_read_the_file_the_run_fetched(
    server: testing.RemoteFileServer, tmp_path: Path
) -> None:
    server.serve(BRANCH_URL, BODY)
    run_file, worker_file, worker_body = _run(
        f"""
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing
        from canvod.utils import remote_file

        ORIGIN = {server.origin!r}

        def fetch(_):
            remote_file._DOWNLOAD_ORIGIN = ORIGIN
            path = remote_file.fetch_remote({BRANCH_URL!r})
            return str(path), path.read_text().split()[-1]

        if __name__ == "__main__":
            print(fetch(0)[0])
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(1, mp_context=context) as pool:
                print(*pool.submit(fetch, 0).result())
        """,
        tmp_path,
    )
    assert worker_file == run_file
    assert worker_body == "Tolkien"
    # The worker read the run's file instead of fetching it again.
    assert len(server.requests) == 1
    assert not Path(run_file).exists()
