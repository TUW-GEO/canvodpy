"""``-c URL``: the commands read the settings from a pinned URL."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import canvodpy.cli.config as cfg
import pytest
import typer
from typer.testing import CliRunner

from canvod.config import load_config
from canvod.config.remote import settings_source
from canvod.utils import pinned, testing

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
    for name in (*pinned.TOKEN_VARIABLES, "CANVOD_CONFIG_DIR", "CANVOD_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    srv = testing.PinnedFileServer()
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", srv.origin)
    settings = json.loads(testing.write_settings(tmp_path / "written").read_text())
    srv.serve(URL, json.dumps(settings).encode())
    yield srv
    srv.close()


def test_validate_reads_the_settings_from_a_url(server, monkeypatch):
    monkeypatch.setenv("CANVOD_CONFIG_DIR", "")  # the option sets it

    result = runner.invoke(_app(), ["config", "validate", "-c", URL])

    # The made-up receiver has no data; the settings themselves are valid.
    assert "Configuration is valid" in result.output, result.output
    assert settings_source(Path(os.environ["CANVOD_CONFIG_DIR"])).url == URL


def test_a_branch_url_is_a_usage_error(server):
    result = runner.invoke(
        _app(), ["config", "validate", "-c", URL.replace(testing.COMMIT, "main")]
    )

    assert result.exit_code == 2
    assert "pinned to a full commit hash or a tag" in _text(result.output)


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
    assert settings_source(Path(os.environ["CANVOD_CONFIG_DIR"])).url == URL


def test_a_failed_fetch_from_the_variable_is_a_usage_error(server, monkeypatch):
    monkeypatch.setenv("CANVOD_CONFIG_DIR", URL.replace("canvod-settings", "missing"))

    result = runner.invoke(_app(), ["config", "validate"])

    assert result.exit_code == 2
    assert "Settings file not found" in _text(result.output)


def test_doctor_names_the_url_and_its_pin(server, monkeypatch):
    import canvodpy.cli.doctor as doctor_module
    from canvodpy.cli.app import main_app
    from rich.console import Console

    monkeypatch.setattr(doctor_module, "console", Console(width=300))

    result = runner.invoke(main_app, ["doctor", "-c", URL])

    assert f"Settings from {URL}" in result.output
    assert f"commit {testing.COMMIT}" in result.output
