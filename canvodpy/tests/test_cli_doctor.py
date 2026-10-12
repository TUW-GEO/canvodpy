"""Tests for canvodpy's doctor CLI command — read-only diagnostics."""

from __future__ import annotations

from unittest.mock import patch

import canvodpy.cli.doctor as doctor_module
import pytest
import yaml
from canvodpy.cli.app import main_app
from rich.console import Console
from typer.testing import CliRunner

import canvod.config.loader as loader_module

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    """Under CliRunner (no real terminal attached), rich falls back to a
    narrow default width and hard-wraps long temp-dir paths mid-string —
    not at a word boundary, so no output post-processing can undo it.
    Give doctor's Console a wide fixed width for the duration of these
    tests only; production still auto-detects the real terminal width."""
    monkeypatch.setattr(doctor_module, "console", Console(width=300))


def _app():
    # Test against the real, multi-command app (run/config/stats/doctor) —
    # a fresh single-command Typer() wrapping only `doctor` collapses into
    # Typer's "single command mode" and stops expecting a subcommand name,
    # which doesn't reflect how `canvodpy doctor` is actually invoked.
    return main_app


def _run(monkeypatch, tmp_path, mock_no_monorepo: bool = True):
    monkeypatch.delenv("CANVOD_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    if mock_no_monorepo:
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            return runner.invoke(_app(), ["doctor"])
    return runner.invoke(_app(), ["doctor"])


class TestDoctor:
    def test_reports_versions_and_xdg_config_when_no_checkout(
        self, monkeypatch, tmp_path
    ):
        result = _run(monkeypatch, tmp_path)

        assert result.exit_code == 0
        assert "canvodpy:" in result.output
        assert "Config resolved to:" in result.output
        assert str(tmp_path / "xdg" / "canvodpy") in result.output
        assert "XDG default" in result.output

    def test_reports_dev_checkout_when_monorepo_config_exists(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("CANVOD_CONFIG_DIR", raising=False)
        fake_root = tmp_path / "checkout"
        (fake_root / "config").mkdir(parents=True)
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = runner.invoke(_app(), ["doctor"])

        assert result.exit_code == 0
        assert str(fake_root / "config") in result.output
        assert "dev checkout" in result.output

    def test_reports_templates_reachable(self, monkeypatch, tmp_path):
        result = _run(monkeypatch, tmp_path)

        assert "Templates reachable" in result.output
        assert (
            "not found"
            not in result.output.split("Templates reachable")[1].split("\n")[0]
        )

    def test_reports_settings_not_found_and_suggests_wizard(
        self, monkeypatch, tmp_path
    ):
        result = _run(monkeypatch, tmp_path)

        assert "canvod-settings.yaml:" in result.output
        assert "not found" in result.output
        assert "canvodpy config init --interactive" in result.output

    def test_reports_valid_for_a_good_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CANVOD_CONFIG_DIR", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "canvod-settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "processing": {
                        "metadata": {
                            "author": "A",
                            "email": "a@example.com",
                            "institution": "B",
                        },
                        "storage": {"stores_root_dir": str(tmp_path / "stores")},
                    },
                    "sites": {},
                }
            )
        )
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = runner.invoke(
                _app(), ["doctor"], env={"CANVOD_CONFIG_DIR": str(config_dir)}
            )

        assert result.exit_code == 0
        assert "valid" in result.output
        assert "Traceback" not in result.output

    def test_reports_actionable_error_for_invalid_config_not_traceback(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("CANVOD_CONFIG_DIR", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "canvod-settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "processing": {
                        "metadata": {
                            "author": "Your Name",
                            "email": "your.email@example.com",
                            "institution": "B",
                        },
                        "storage": {"stores_root_dir": str(tmp_path / "stores")},
                    },
                    "sites": {},
                }
            )
        )
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = runner.invoke(
                _app(), ["doctor"], env={"CANVOD_CONFIG_DIR": str(config_dir)}
            )

        assert result.exit_code == 0
        assert "invalid" in result.output
        assert "metadata.author" in result.output
        assert "Traceback" not in result.output
