"""Tests for canvodpy's top-level CLI app entry point."""

from __future__ import annotations

import re

import pytest
import typer.main
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
        result = runner.invoke(
            main_app, ["run", "--site", "fangorn", "--start", "2025001"]
        )

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
        result = runner.invoke(
            main_app, ["run", "--site", "fangorn", "--start", "2025001"]
        )

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


class TestHelpAll:
    def test_lists_every_command_and_option(self):
        result = runner.invoke(main_app, ["--help-all"], env={"COLUMNS": "100"})
        assert result.exit_code == 0
        words = set(result.output.split())

        def walk(command, path):
            if hasattr(command, "commands"):
                for name, sub in command.commands.items():
                    if not sub.hidden:
                        walk(sub, [*path, name])
                return
            assert path[-1] in words
            for param in command.params:
                if getattr(param, "hidden", False) or param.name == "help":
                    continue
                name = (
                    next(o for o in param.opts if o.startswith("--"))
                    if param.param_type_name == "option"
                    else param.name.upper()
                )
                assert name in words, f"{' '.join(path)}: {name}"

        walk(typer.main.get_command(main_app), [])

    def test_points_to_one_command_help_and_the_reference(self):
        from canvodpy.cli.app import CLI_REFERENCE

        result = runner.invoke(main_app, ["--help-all"])
        assert "canvodpy COMMAND --help" in result.output
        assert CLI_REFERENCE in result.output

    def test_is_in_the_main_help_just_before_help(self):
        import click

        result = runner.invoke(main_app, ["--help"], env={"COLUMNS": "200"})
        # CI forces colour: without the escape codes, each line starts with the box.
        options = [
            line.split()[1]
            for line in click.unstyle(result.output).splitlines()
            if line.startswith("│ --")
        ]
        assert options[-2:] == ["--help-all", "--help"]


class TestInstallCompletionReloadHint:
    @staticmethod
    def _installed(_ctx, _param, _value):
        raise SystemExit(0)  # as Typer's install ends

    @pytest.mark.parametrize(
        ("shell", "hint"),
        [
            ("zsh", "exec zsh"),
            ("bash", "exec bash"),
            ("fish", "exec fish"),
            ("pwsh", ". $PROFILE"),
            ("powershell", ". $PROFILE"),
        ],
    )
    def test_hint_for_the_shell_it_runs_in(self, monkeypatch, capsys, shell, hint):
        from canvodpy.cli import app

        monkeypatch.setattr(app, "_current_shell", lambda: shell)
        with pytest.raises(SystemExit):
            app._with_reload_hint(self._installed)(None, None, True)

        assert capsys.readouterr().out.strip().endswith(hint)

    @pytest.mark.parametrize("shell", ["tcsh", None])
    def test_no_hint_for_another_or_undetected_shell(self, monkeypatch, capsys, shell):
        from canvodpy.cli import app

        monkeypatch.setattr(app, "_current_shell", lambda: shell)
        with pytest.raises(SystemExit):
            app._with_reload_hint(self._installed)(None, None, True)

        assert capsys.readouterr().out == ""

    def test_the_login_shell_does_not_decide(self, monkeypatch, capsys):
        """$SHELL is the login shell; Typer installs for the one running."""
        from canvodpy.cli import app

        monkeypatch.setenv("SHELL", "/bin/zsh")
        monkeypatch.setattr(app, "_current_shell", lambda: "bash")
        with pytest.raises(SystemExit):
            app._with_reload_hint(self._installed)(None, None, True)

        assert "exec bash" in capsys.readouterr().out

    def test_hint_for_the_shell_named(self, monkeypatch, capsys):
        """A shell named to Typer (detection off) wins over the one running."""
        from canvodpy.cli import app

        monkeypatch.setattr(app, "_current_shell", lambda: "zsh")
        with pytest.raises(SystemExit):
            app._with_reload_hint(self._installed)(None, None, "bash")

        assert capsys.readouterr().out.strip().endswith("exec bash")

    def test_hint_after_typers_own_install(self, monkeypatch, tmp_path):
        """Through Typer's real callback: fails if a Typer upgrade drops the hint."""
        import typer.completion
        from canvodpy.cli import app

        monkeypatch.setattr(app, "_current_shell", lambda: "zsh")
        monkeypatch.setattr(
            typer.completion,
            "install",
            lambda shell=None: ("zsh", tmp_path / ".zshrc"),
        )
        result = runner.invoke(main_app, ["--install-completion"])

        assert result.exit_code == 0
        assert "completion installed" in result.output
        assert result.output.strip().endswith("exec zsh")

    def test_canvodpy_uses_the_wrapped_install(self):
        command = typer.main.get_command(main_app)
        install = next(p for p in command.params if p.name == "install_completion")

        assert install.callback.__wrapped__ is not None
