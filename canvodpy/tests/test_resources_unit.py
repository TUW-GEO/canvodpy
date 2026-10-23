"""Unit tests for MemoryMonitor."""

from __future__ import annotations

import unittest.mock
from pathlib import Path

import pytest
from canvodpy.orchestrator.resources import MemoryMonitor


def _mock_vmem(
    available: int = 4 * 1024**3, percent: float = 42.5, total: int = 8 * 1024**3
):
    m = unittest.mock.MagicMock()
    m.available = available
    m.percent = percent
    m.total = total
    return m


class TestMemoryMonitor:
    def test_init_stores_max_memory_gb(self):
        mm = MemoryMonitor(max_memory_gb=16.0)
        assert mm.max_memory_gb == 16.0

    def test_init_none(self):
        mm = MemoryMonitor()
        assert mm.max_memory_gb is None

    def test_available_gb(self):
        with unittest.mock.patch(
            "psutil.virtual_memory", return_value=_mock_vmem(available=4 * 1024**3)
        ):
            mm = MemoryMonitor()
            assert abs(mm.available_gb() - 4.0) < 0.01

    def test_used_percent(self):
        with unittest.mock.patch(
            "psutil.virtual_memory", return_value=_mock_vmem(percent=55.0)
        ):
            mm = MemoryMonitor()
            assert mm.used_percent() == pytest.approx(55.0)

    def test_log_memory_stats_does_not_raise(self):
        with unittest.mock.patch("psutil.virtual_memory", return_value=_mock_vmem()):
            mm = MemoryMonitor()
            mm.log_memory_stats(context="test_context")  # should not raise


class TestPipelineRunLock:
    """Same-host signal for `canvodpy store maintain-due` to skip itself
    while a pipeline write is active (dev/todo_later.md icechunk-
    maintenance-scheduling gap, 2026-07-21)."""

    def test_not_running_when_no_pid_file(self, tmp_path):
        from canvodpy.orchestrator.resources import is_pipeline_running

        assert is_pipeline_running(tmp_path / "nonexistent.pid") is False

    def test_running_while_lock_held(self, tmp_path):
        from canvodpy.orchestrator.resources import (
            PipelineRunLock,
            is_pipeline_running,
        )

        pid_file = tmp_path / "run.pid"
        with PipelineRunLock(pid_file):
            assert is_pipeline_running(pid_file) is True
        assert is_pipeline_running(pid_file) is False, "removed on clean exit"
        assert not pid_file.exists()

    def test_stale_pid_file_reads_as_not_running(self, tmp_path):
        """A PID file surviving a hard crash (SIGKILL/OOM) must not
        permanently wedge every future scheduled run -- liveness is
        checked via the recorded PID, not just file existence."""
        from canvodpy.orchestrator.resources import is_pipeline_running

        pid_file = tmp_path / "run.pid"
        # A PID essentially guaranteed not to be a live process right now.
        pid_file.write_text("999999999")
        assert is_pipeline_running(pid_file) is False

    def test_lock_released_even_on_exception(self, tmp_path):
        from canvodpy.orchestrator.resources import (
            PipelineRunLock,
            is_pipeline_running,
        )

        pid_file = tmp_path / "run.pid"
        with pytest.raises(ValueError):
            with PipelineRunLock(pid_file):
                raise ValueError("simulated pipeline crash")
        assert is_pipeline_running(pid_file) is False
        assert not pid_file.exists()


class TestRunPidFileInTests:
    def test_tests_never_use_the_users_run_pid(self):
        """The conftest fixture moves the lock; the defaults must follow (#401)."""
        from canvodpy.orchestrator.resources import PipelineRunLock

        real = Path.home() / ".cache" / "canvodpy" / "run.pid"
        assert PipelineRunLock().pid_file != real
