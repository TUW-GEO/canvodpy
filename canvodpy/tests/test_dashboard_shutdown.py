"""Shutting down the dashboard of ``canvodpy run --dashboard``."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest
from canvodpy.cli import run as run_module
from canvodpy.cli.app import main_app
from canvodpy.cli.dashboards.shutdown import RUN_VARIABLE, run_going, run_marker
from typer.testing import CliRunner


def _sleeper() -> subprocess.Popen:
    """A process that stands in for the dashboard or for a run."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


class TestRunGoing:
    def test_no_run_started_the_dashboard(self):
        assert run_going({}) is None

    def test_the_run_is_going(self):
        assert run_going({RUN_VARIABLE: run_marker()}) is True

    def test_the_run_has_ended(self):
        run = _sleeper()
        marker = f"{run.pid} {psutil.Process(run.pid).create_time()!r}"
        run.kill()
        run.wait()

        assert run_going({RUN_VARIABLE: marker}) is False

    def test_a_later_process_with_the_run_s_id_is_not_the_run(self):
        started = psutil.Process().create_time()
        marker = f"{psutil.Process().pid} {started - 3600!r}"

        assert run_going({RUN_VARIABLE: marker}) is False

    def test_another_user_s_process_is_not_the_run(self, monkeypatch):
        def refuse(_process):
            raise psutil.AccessDenied(1)

        monkeypatch.setattr(psutil.Process, "create_time", refuse)

        assert run_going({RUN_VARIABLE: "1 1700000000.0"}) is False

    @pytest.mark.parametrize("marker", ["garbage", "12", "12 34 56", "x 1.0"])
    def test_a_value_that_holds_no_run_is_no_run(self, marker):
        assert run_going({RUN_VARIABLE: marker}) is None


def _args(*, dashboard: bool, stop_at_end: bool) -> SimpleNamespace:
    return SimpleNamespace(
        dashboard=dashboard,
        dashboard_host="127.0.0.1",
        dashboard_port=8765,
        dashboard_stop_at_end=stop_at_end,
    )


@pytest.fixture
def dashboards(monkeypatch):
    """The dashboards the run starts: stand-in processes, killed afterwards."""
    started: list[subprocess.Popen] = []

    def start(_log_dir, _host, _port):
        started.append(_sleeper())
        return started[-1]

    monkeypatch.setattr(run_module, "_start_dashboard", start)
    yield started
    for process in started:
        process.kill()
        process.wait()


class TestDashboardForRun:
    def test_stays_up_after_the_run(self, dashboards, tmp_path, capsys):
        with run_module._dashboard_for_run(
            _args(dashboard=True, stop_at_end=False), tmp_path
        ):
            pass

        assert dashboards[0].poll() is None
        assert "still running" in capsys.readouterr().out

    def test_stops_with_the_run(self, dashboards, tmp_path):
        with run_module._dashboard_for_run(
            _args(dashboard=True, stop_at_end=True), tmp_path
        ):
            pass

        assert dashboards[0].wait(timeout=10) is not None

    def test_stops_when_the_run_fails(self, dashboards, tmp_path):
        with (
            pytest.raises(RuntimeError),
            run_module._dashboard_for_run(
                _args(dashboard=True, stop_at_end=True), tmp_path
            ),
        ):
            raise RuntimeError("the run crashed")

        assert dashboards[0].wait(timeout=10) is not None

    def test_no_dashboard_without_the_option(self, dashboards, tmp_path):
        with run_module._dashboard_for_run(
            _args(dashboard=False, stop_at_end=False), tmp_path
        ):
            pass

        assert dashboards == []


def test_stop_at_end_needs_the_dashboard():
    result = CliRunner().invoke(
        main_app,
        ["run", "--site", "fangorn", "--start", "2025001", "--dashboard-stop-at-end"],
    )

    assert result.exit_code == 1
    assert "--dashboard-stop-at-end needs --dashboard" in result.output
