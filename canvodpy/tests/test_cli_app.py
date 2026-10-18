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

    def test_a_run_that_does_not_fit_in_memory_exits_with_the_message(
        self, monkeypatch
    ):
        """Not even one worker fits: the run stops before reading (exit 1)."""
        from canvodpy.cli import run as run_module
        from canvodpy.orchestrator.memory_budget import MemoryBudgetError

        def refuse(_args):
            raise MemoryBudgetError("The run needs at least 2.1 GB of memory")

        monkeypatch.setattr(run_module, "_main_impl", refuse)
        result = runner.invoke(main_app, ["run", "--site", "fangorn"])

        assert result.exit_code == 1
        assert "The run needs at least 2.1 GB of memory" in result.output
        assert "Traceback" not in result.output


class TestDeprecatedDaysPerBatch:
    """``--days-per-batch`` is deprecated: a run without it passes nothing on."""

    @staticmethod
    def _pipeline_kwargs(monkeypatch, extra: list[str]) -> dict:
        import canvodpy.api

        seen: dict = {}

        class _Stop(Exception):
            pass

        class _Site:
            def __init__(self, _name):
                pass

            def pipeline(self, **kwargs):
                seen.update(kwargs)
                raise _Stop

        monkeypatch.setattr(canvodpy.api, "Site", _Site)
        runner.invoke(
            main_app,
            [
                "run",
                "--site",
                "fangorn",
                "--start",
                "2025001",
                "--end",
                "2025002",
                "--dry-run",
                *extra,
            ],
        )
        return seen

    def test_without_the_option_nothing_is_passed(self, monkeypatch):
        kwargs = self._pipeline_kwargs(monkeypatch, [])

        assert "n_workers" in kwargs
        assert "days_per_batch" not in kwargs

    def test_the_option_is_passed_on_when_given(self, monkeypatch):
        kwargs = self._pipeline_kwargs(monkeypatch, ["--days-per-batch", "3"])

        assert kwargs["days_per_batch"] == 3

    def test_the_option_is_hidden_from_the_help(self):
        result = runner.invoke(main_app, ["run", "--help"])

        assert "--days-per-batch" not in result.output
