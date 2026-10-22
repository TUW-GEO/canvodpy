"""``-c URL``: the commands read the settings from a URL."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import canvodpy.cli.config as cfg
import pytest
import typer
from typer.testing import CliRunner

from canvod.config import load_config, remote
from canvod.config.remote import settings_url
from canvod.utils import remote_file, testing

runner = CliRunner()


def _text(output: str) -> str:
    """The output without color codes, Rich's box and line breaks."""
    # On GitHub Actions typer forces a colored terminal.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return re.sub(r"[\s│╭╮╰╯─]+", " ", plain)


URL = (
    f"https://raw.githubusercontent.com/the-inklings/red-book/{testing.COMMIT}"
    "/config/canvod-settings.yaml"
)


def _app() -> typer.Typer:
    app = typer.Typer()
    app.add_typer(cfg.config_app, name="config")
    return app


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    monkeypatch.setattr(remote_file, "_FETCHED", {})
    monkeypatch.setattr(remote_file, "_FOLDER", None)
    monkeypatch.setattr(remote, "_FOLDERS", {})
    for name in (
        *remote_file.TOKEN_VARIABLES,
        "CANVOD_CONFIG_DIR",
        "CANVOD_CONFIG_FILE",
        "CANVODPY_RUN_FOLDER",
    ):
        monkeypatch.delenv(name, raising=False)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    srv = testing.RemoteFileServer()
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", srv.origin)
    settings = json.loads(testing.write_settings(tmp_path / "written").read_text())
    srv.body = json.dumps(settings).encode()
    srv.serve(URL, srv.body)
    srv.serve(URL.replace(testing.COMMIT, "main"), srv.body)
    yield srv
    srv.close()


def test_validate_reads_the_settings_from_a_url(server, monkeypatch):
    monkeypatch.setenv("CANVOD_CONFIG_DIR", "")  # the option sets it

    result = runner.invoke(_app(), ["config", "validate", "-c", URL])

    # The made-up receiver has no data; the settings themselves are valid.
    assert "Configuration is valid" in result.output, result.output
    assert settings_url(Path(os.environ["CANVOD_CONFIG_DIR"])) == URL


def test_a_branch_url_works(server):
    result = runner.invoke(
        _app(), ["config", "validate", "-c", URL.replace(testing.COMMIT, "main")]
    )

    assert "Configuration is valid" in result.output, result.output


def test_a_page_link_is_a_usage_error(server):
    page = URL.replace("raw.githubusercontent.com", "github.com").replace(
        "/red-book/", "/red-book/blob/"
    )

    result = runner.invoke(_app(), ["config", "validate", "-c", page])

    assert result.exit_code == 2
    assert "Use the raw link" in _text(result.output)


@pytest.mark.parametrize("command", ["init", "edit"])
def test_commands_that_write_the_settings_refuse_a_url(server, command):
    result = runner.invoke(_app(), ["config", command, "-c", URL])

    assert result.exit_code == 2
    assert "needs a local folder" in _text(result.output)
    assert server.requests == []


def test_a_url_in_the_variable_works_like_the_option(server, monkeypatch):
    monkeypatch.setenv("CANVOD_CONFIG_DIR", URL)

    result = runner.invoke(_app(), ["config", "validate"])

    assert "Configuration is valid" in result.output, result.output
    assert settings_url(Path(os.environ["CANVOD_CONFIG_DIR"])) == URL


def test_a_failed_fetch_from_the_variable_is_a_usage_error(server, monkeypatch):
    monkeypatch.setenv("CANVOD_CONFIG_DIR", URL.replace("canvod-settings", "missing"))

    result = runner.invoke(_app(), ["config", "validate"])

    assert result.exit_code == 2
    assert "Settings file not found" in _text(result.output)


def test_doctor_names_the_url_and_the_sha256(server, monkeypatch):
    import canvodpy.cli.doctor as doctor_module
    from canvodpy.cli.app import main_app
    from rich.console import Console

    monkeypatch.setattr(doctor_module, "console", Console(width=300))

    result = runner.invoke(main_app, ["doctor", "-c", URL])

    assert f"Settings from {URL}" in result.output
    assert f"sha256 {hashlib.sha256(server.body).hexdigest()}" in result.output
