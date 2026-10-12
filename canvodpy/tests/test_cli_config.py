"""Tests for canvodpy's config CLI, focused on the --interactive wizard."""

from __future__ import annotations

import re
from unittest import mock

import canvodpy.cli.config as cfg
import pytest
import typer
import yaml
from typer.testing import CliRunner

from canvod.utils import testing

runner = CliRunner()


def _app() -> typer.Typer:
    app = typer.Typer()
    app.add_typer(cfg.config_app, name="config")
    return app


def _run_wizard(config_dir, answers: str, force: bool = False):
    args = ["config", "init", "--config-dir", str(config_dir), "--interactive"]
    if force:
        args.append("--force")
    return runner.invoke(_app(), args, input=answers)


class TestInteractiveWizard:
    def test_writes_all_answers_and_validates_cleanly(self, tmp_path):
        config_dir = tmp_path / "config"
        answers = (
            f"{testing.PERSON_NAME}\n"
            f"{testing.PERSON_EMAIL}\n"
            "University of Oxford\n"
            f"{tmp_path / 'stores'}\n"
            f"{tmp_path / 'logs'}\n"
            "Fangorn\n"
            f"{tmp_path / 'data'}\n"
            "custom_canopy\n"
            "custom_reference\n"
        )
        result = _run_wizard(config_dir, answers)

        assert result.exit_code == 0, result.output
        assert "Configuration is valid" in result.output

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert f"author: {testing.PERSON_NAME}" in text
        assert f"email: {testing.PERSON_EMAIL}" in text
        assert "institution: University of Oxford" in text
        assert f"stores_root_dir: {tmp_path / 'stores'}" in text
        assert f"log_dir: {tmp_path / 'logs'}" in text
        assert "  Fangorn:" in text
        assert f"gnss_site_data_root: {tmp_path / 'data'}" in text
        assert "directory: custom_canopy" in text
        assert "directory: custom_reference" in text

    def test_preserves_template_comments(self, tmp_path):
        """A full YAML parse/re-dump would strip these — must survive."""
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\n{tmp_path / 'l'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert (
            "# ============================================================================="
            in text
        )
        assert "SID Format: PRN|Band|Code" in text

    def test_does_not_touch_commented_example_block(self, tmp_path):
        """The commented-out 'my_second_site' illustration must stay verbatim."""
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\n{tmp_path / 'l'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert "#       directory: 01_reference" in text
        assert "#       directory: 02_canopy" in text

    def test_default_receiver_directories_when_answer_blank(self, tmp_path):
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\n{tmp_path / 'l'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert "directory: 02_canopy" in text
        assert "directory: 01_reference" in text

    def test_skips_wizard_when_config_already_exists(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        existing = config_dir / "canvod-settings.yaml"
        existing.write_text("# hand-edited, do not touch\n")

        result = _run_wizard(config_dir, answers="")

        assert result.exit_code == 0
        assert "skipping interactive setup" in result.output
        assert existing.read_text() == "# hand-edited, do not touch\n"

    def test_reports_actionable_error_for_bad_answer(self, tmp_path):
        """An answer that fails Pydantic validation shows the clean
        field-path report (format_validation_error), not a traceback."""
        config_dir = tmp_path / "config"
        answers = (
            "Your Name\n"  # still-placeholder value — same validator #4 fixed
            "b@example.com\n"
            "C\n"
            f"{tmp_path / 's'}\n"
            f"{tmp_path / 'l'}\n"
            "Site\n"
            f"{tmp_path / 'd'}\n"
            "\n\n"
        )
        result = _run_wizard(config_dir, answers)

        assert result.exit_code == 0
        assert "still need attention" in result.output
        assert "metadata.author" in result.output
        assert "Traceback" not in result.output


class TestValidateRecipeWithoutFilemap:
    """canvod-filemap is an optional extra, not installed in this test env —
    a receiver with recipe: set must fail fast and clearly, not silently
    degrade to canonical globs deep inside a real run."""

    def _write_config(self, config_dir, tmp_path, *, with_recipe: bool):
        config_dir.mkdir(parents=True)
        receiver = {"type": "canopy", "directory": "02_canopy"}
        if with_recipe:
            receiver["recipe"] = "fangorn_canopy"
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
                    "sites": {
                        "TestSite": {
                            "gnss_site_data_root": str(tmp_path / "data"),
                            "receivers": {"canopy_01": receiver},
                        }
                    },
                }
            )
        )

    def test_recipe_without_filemap_fails_fast(self, tmp_path):
        config_dir = tmp_path / "config"
        self._write_config(config_dir, tmp_path, with_recipe=True)

        # Simulate an install without canvod-filemap, whatever this env has
        with mock.patch.dict("sys.modules", {"canvod.filemap": None}):
            result = runner.invoke(
                _app(), ["config", "validate", "--config-dir", str(config_dir)]
            )

        assert result.exit_code == 1
        assert "canopy_01" in result.output
        assert "uv sync --group filemap" in result.output

    def test_no_recipe_does_not_trip_the_filemap_check(self, tmp_path):
        config_dir = tmp_path / "config"
        self._write_config(config_dir, tmp_path, with_recipe=False)

        result = runner.invoke(
            _app(), ["config", "validate", "--config-dir", str(config_dir)]
        )

        assert "uv sync --group filemap" not in result.output


class TestConfigDirOption:
    def test_selects_the_settings_and_the_recipes(self, tmp_path):
        pytest.importorskip("canvod.filemap.recipe_files")
        from canvodpy.orchestrator.discovery import recipe_file

        from canvod.config.loader import get_default_config_dir

        config_dir = tmp_path / "my_config"
        result = runner.invoke(
            _app(), ["config", "init", "--config-dir", str(config_dir)]
        )
        assert result.exit_code == 0, result.output
        assert (config_dir / "canvod-settings.yaml").exists()

        # Every later lookup in the same process uses that directory
        assert get_default_config_dir() == config_dir.resolve()
        (config_dir / "recipes" / "fangorn").mkdir(parents=True)
        (config_dir / "recipes" / "fangorn" / "rx.yaml").write_text("")
        assert recipe_file("fangorn", "rx") == (
            config_dir.resolve() / "recipes" / "fangorn" / "rx.yaml"
        )

    def test_every_command_offers_it(self):
        from canvodpy.cli.app import main_app

        for command in (
            ["run"],
            ["vod"],
            ["vod-reconcile"],
            ["doctor"],
            ["store", "list"],
            ["store", "info"],
            ["store", "log"],
            ["store", "maintain"],
            ["store", "maintain-due"],
            ["config", "init"],
            ["config", "validate"],
            ["config", "show"],
            ["config", "edit"],
        ):
            # Wide help text, ANSI codes removed: on GitHub Actions typer
            # forces a colored terminal, and the codes split option names.
            result = runner.invoke(
                main_app, [*command, "--help"], env={"COLUMNS": "200"}
            )
            plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
            assert "--config-dir" in plain, command
