"""Tests for the canvodpy.logging package: run_id, crash handling, stage_timer.

Covers the logging/debugging redesign: two-track logging (agent.json rename +
run_id injection), the sys.excepthook safety net, PerformanceFilter matching,
and the stage_timer performance tracker (see docs/guides/diagnostics.md).
"""

import json
import sys

import pytest
import structlog
from canvodpy.logging import (
    configure_logging,
    emit_run_summary,
    get_run_id,
    reset_run_id,
    set_run_id,
    stage_timer,
    timed_stage,
)
from canvodpy.logging.logging_config import PerformanceFilter

from canvod.utils.logging import reset_run_stats


@pytest.fixture(autouse=True)
def _restore_excepthook():
    """configure_logging() reassigns sys.excepthook globally; restore after each test.

    A couple of tests also monkeypatch sys.__excepthook__ to observe chaining
    without dumping a real traceback to stderr; restore that too.
    """
    original_hook = sys.excepthook
    original_dunder_hook = sys.__excepthook__
    yield
    sys.excepthook = original_hook
    sys.__excepthook__ = original_dunder_hook


@pytest.fixture
def configured_logs(tmp_path):
    """Configure logging against an isolated tmp directory and return its paths."""
    configure_logging(tmp_path / ".logs" / "canvodpy.log")
    machine_dir = tmp_path / ".logs" / "machine"
    return {
        "agent": machine_dir / "agent.json",
        "performance": machine_dir / "performance.json",
    }


def _read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestRunContext:
    def test_default_is_none(self):
        assert get_run_id() is None

    def test_set_get_reset_round_trip(self):
        token = set_run_id("TestSite-20260101-000000")
        try:
            assert get_run_id() == "TestSite-20260101-000000"
        finally:
            reset_run_id(token)
        assert get_run_id() is None


class TestAgentTrackAndRunId:
    def test_agent_json_exists_not_full_json(self, tmp_path, configured_logs):
        machine_dir = tmp_path / ".logs" / "machine"
        assert configured_logs["agent"].exists()
        assert not (machine_dir / "full.json").exists()

    def test_run_id_injected_automatically(self, configured_logs):
        token = set_run_id("ExampleSite-20260713-120000")
        try:
            structlog.get_logger("test").info("some_event", foo="bar")
        finally:
            reset_run_id(token)

        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "some_event"]
        assert len(matches) == 1
        assert matches[0]["run_id"] == "ExampleSite-20260713-120000"

    def test_no_run_id_key_when_unbound(self, configured_logs):
        assert get_run_id() is None
        structlog.get_logger("test").info("unbound_event")
        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "unbound_event"]
        assert len(matches) == 1
        assert "run_id" not in matches[0]


class TestExcepthook:
    def test_uncaught_exception_logged_and_chains_to_default(self, configured_logs):
        # _install_excepthook is idempotent (see its docstring) -- by the
        # time the fixture ran, the process-wide hook may already be
        # installed from an earlier test/import, so its captured
        # "default_hook" isn't necessarily observable here. Force a fresh
        # install by resetting sys.excepthook to an unmarked function first,
        # so this test can actually verify the chaining behavior.
        from canvodpy.logging.logging_config import _install_excepthook

        chained_calls = []
        sys.excepthook = lambda *args: chained_calls.append(args)
        _install_excepthook(structlog.get_logger("test_excepthook"))
        installed_hook = sys.excepthook

        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        installed_hook(*exc_info)  # must not itself raise

        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "uncaught_exception"]
        assert len(matches) == 1
        assert matches[0]["exc_type"] == "ValueError"
        assert "boom" in matches[0]["exc_message"]
        assert "ValueError: boom" in matches[0]["traceback"]
        assert len(chained_calls) == 1  # default hook still ran

    def test_keyboard_interrupt_not_logged(self, configured_logs):
        installed_hook = sys.excepthook
        sys.__excepthook__ = lambda *args: None  # suppress stderr traceback dump

        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            exc_info = sys.exc_info()

        installed_hook(*exc_info)

        events = _read_jsonl(configured_logs["agent"])
        assert not [e for e in events if e.get("event") == "uncaught_exception"]


class TestPerformanceFilter:
    def _record(self, msg: dict):
        record = type("Record", (), {})()
        record.msg = msg
        return record

    def test_matches_stage_timing_event(self):
        f = PerformanceFilter()
        assert f.filter(self._record({"event": "stage_timing", "stage": "x"}))

    def test_matches_duration_seconds_under_any_event_name(self):
        f = PerformanceFilter()
        assert f.filter(
            self._record(
                {"event": "ephemeris_interpolation_complete", "duration_seconds": 1.2}
            )
        )

    def test_rejects_unrelated_event(self):
        f = PerformanceFilter()
        assert not f.filter(self._record({"event": "file_skipped", "reason": "x"}))

    def test_performance_json_receives_both_event_shapes(self, configured_logs):
        log = structlog.get_logger("test")
        with stage_timer("generic.stage"):
            pass
        log.info("ephemeris_interpolation_complete", duration_seconds=1.23)
        log.info("file_skipped", reason="parse_error")  # should NOT appear

        events = _read_jsonl(configured_logs["performance"])
        event_names = {e["event"] for e in events}
        assert "stage_timing" in event_names
        assert "ephemeris_interpolation_complete" in event_names
        assert "file_skipped" not in event_names


class TestStageTimer:
    def test_emits_ok_on_success(self, configured_logs):
        with stage_timer("unit.success", foo="bar"):
            pass
        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "stage_timing"]
        assert len(matches) == 1
        assert matches[0]["stage"] == "unit.success"
        assert matches[0]["status"] == "ok"
        assert matches[0]["foo"] == "bar"
        assert matches[0]["duration_seconds"] >= 0

    def test_emits_error_and_reraises_on_exception(self, configured_logs):
        with pytest.raises(ValueError, match="boom"):
            with stage_timer("unit.failure"):
                raise ValueError("boom")
        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "stage_timing"]
        assert len(matches) == 1
        assert matches[0]["status"] == "error"

    def test_timed_stage_decorator(self, configured_logs):
        @timed_stage("unit.decorated")
        def _work(x):
            return x * 2

        assert _work(21) == 42
        events = _read_jsonl(configured_logs["agent"])
        matches = [e for e in events if e.get("event") == "stage_timing"]
        assert matches[0]["stage"] == "unit.decorated"


class TestRunSummary:
    def test_rolls_up_stage_timing_events(self, configured_logs):
        token = set_run_id("SummaryTest-20260101-000000")
        try:
            with stage_timer("stage.a"):
                pass
            with stage_timer("stage.a"):
                pass
            with pytest.raises(ValueError):
                with stage_timer("stage.b"):
                    raise ValueError("x")
            emit_run_summary(site="ExampleSite")
        finally:
            reset_run_stats("SummaryTest-20260101-000000")
            reset_run_id(token)

        events = _read_jsonl(configured_logs["agent"])
        summary = next(e for e in events if e.get("event") == "run_summary")
        assert summary["stages"]["stage.a"]["count"] == 2
        assert summary["stages"]["stage.b"]["count"] == 1
        assert summary["stages"]["stage.b"]["errors"] == 1
        assert summary["site"] == "ExampleSite"

    def test_reset_run_stats_clears_accumulator(self, configured_logs):
        token = set_run_id("ResetTest-20260101-000000")
        try:
            with stage_timer("stage.a"):
                pass
            reset_run_stats("ResetTest-20260101-000000")
            emit_run_summary()
        finally:
            reset_run_id(token)

        events = _read_jsonl(configured_logs["agent"])
        summaries = [e for e in events if e.get("event") == "run_summary"]
        assert summaries[-1]["stages"] == {}


class TestFileLoggingStartsWithTheRun:
    """Log files follow the configuration of the run, not of the import."""

    @pytest.fixture(autouse=True)
    def _back_to_console(self):
        yield
        from canvodpy.logging.logging_config import configure_console_logging

        configure_console_logging()

    @staticmethod
    def _settings_logging_to(logfile):
        from types import SimpleNamespace

        logging_settings = SimpleNamespace(get_log_file=lambda: logfile)
        return SimpleNamespace(processing=SimpleNamespace(logging=logging_settings))

    def test_import_reads_no_settings(self, tmp_path):
        """Even invalid settings must not matter when canvodpy is imported."""
        import os
        import subprocess

        (tmp_path / "canvod-settings.yaml").write_text("processing: [not, valid]\n")
        env = {**os.environ, "CANVOD_CONFIG_DIR": str(tmp_path)}
        result = subprocess.run(
            [
                sys.executable,
                "-W",
                "error",
                "-c",
                "import canvodpy, canvodpy.cli.run\n"
                "from canvod.config import loader\n"
                "assert loader._load_config_cached.cache_info().misses == 0\n",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / ".logs").exists()

    def test_follows_the_settings_of_each_run(self, tmp_path, monkeypatch):
        from canvodpy.logging import logging_config

        for run in ("first", "second"):
            logfile = tmp_path / run / ".logs" / "canvodpy.log"
            monkeypatch.setattr(
                logging_config,
                "load_config",
                lambda logfile=logfile: self._settings_logging_to(logfile),
            )
            logging_config.ensure_file_logging()
            structlog.get_logger("canvodpy.test").info("run_started", run=run)
            agent = tmp_path / run / ".logs" / "machine" / "agent.json"
            assert [r["run"] for r in _read_jsonl(agent)] == [run]

    def test_invalid_settings_raise(self, monkeypatch):
        from canvodpy.logging import logging_config

        def _invalid():
            raise ValueError("invalid settings")

        monkeypatch.setattr(logging_config, "load_config", _invalid)
        with pytest.raises(ValueError, match="invalid settings"):
            logging_config.ensure_file_logging()
