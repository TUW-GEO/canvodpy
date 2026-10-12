"""Tests for canvodpy's top-level CLI app entry point."""

from __future__ import annotations

import re

from canvodpy.cli.app import main_app
from typer.testing import CliRunner

runner = CliRunner()


class TestVersion:
    def test_version_flag_prints_version_and_exits(self):
        result = runner.invoke(main_app, ["--version"])

        assert result.exit_code == 0
        assert re.match(r"canvodpy \d+\.\d+\.\d+", result.output)

    def test_version_flag_does_not_require_a_subcommand(self):
        result = runner.invoke(main_app, ["--version"])

        assert "Traceback" not in result.output

    def test_no_args_shows_help_not_error(self):
        result = runner.invoke(main_app, [])

        assert "Process GNSS observations into VOD" in result.output
        assert "Commands" in result.output


class TestRunStopsOnPreprocessingMismatch:
    def test_exit_code_and_message(self, monkeypatch):
        """Every later day would be refused too, so the run stops (exit 1)."""
        from canvodpy.cli import run as run_module

        from canvod.config.models import PreprocessingMismatchError

        def refuse(_args):
            raise PreprocessingMismatchError("Group 'canopy_01' holds data with ...")

        monkeypatch.setattr(run_module, "_main_impl", refuse)
        result = runner.invoke(main_app, ["run", "--site", "fangorn"])

        assert result.exit_code == 1
        assert "Group 'canopy_01' holds data with" in result.output
        assert "Traceback" not in result.output
