"""A pipeline created from Python sets a run_id, like ``canvodpy run``."""

import re
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from canvodpy.orchestrator.pipeline import PipelineOrchestrator

from canvod.utils.logging import get_run_id, new_run_id, reset_run_id, set_run_id


@pytest.fixture
def make_orchestrator():
    with ExitStack() as stack:
        for name in ("ensure_file_logging", "clear_discovery_cache", "check_receivers"):
            stack.enter_context(patch(f"canvodpy.orchestrator.pipeline.{name}"))

        def _make() -> PipelineOrchestrator:
            site = MagicMock()
            site.site_name = "ExampleSite"
            return PipelineOrchestrator(site)

        yield _make


RUN_ID = r"ExampleSite-\d{8}-\d{6}-[0-9a-f]{6}"


def test_new_run_id_format():
    assert re.fullmatch(RUN_ID, new_run_id("ExampleSite"))


def test_new_run_id_starts_with_the_start_time_in_utc():
    start = datetime(2026, 10, 10, 3, 0, 0, tzinfo=UTC)
    with patch("canvod.utils.logging.run_context.datetime") as clock:
        clock.now.return_value = start
        run_id = new_run_id("ExampleSite")
    assert run_id.startswith("ExampleSite-20261010-030000-")


def test_runs_started_in_the_same_second_get_different_run_ids():
    start = datetime(2026, 10, 10, 3, 0, 0, tzinfo=UTC)
    with patch("canvod.utils.logging.run_context.datetime") as clock:
        clock.now.return_value = start
        run_ids = {new_run_id("ExampleSite") for _ in range(100)}
    assert len(run_ids) == 100


def test_sets_run_id_until_closed(make_orchestrator):
    assert get_run_id() is None
    with make_orchestrator():
        assert re.fullmatch(RUN_ID, get_run_id() or "")
    assert get_run_id() is None


def test_keeps_a_run_id_set_before(make_orchestrator):
    token = set_run_id("ExampleSite-20261010-030000")
    try:
        with make_orchestrator():
            assert get_run_id() == "ExampleSite-20261010-030000"
        assert get_run_id() == "ExampleSite-20261010-030000"
    finally:
        reset_run_id(token)


def test_close_twice(make_orchestrator):
    orchestrator = make_orchestrator()
    orchestrator.close()
    orchestrator.close()
    assert get_run_id() is None


def test_no_run_id_left_when_checks_fail():
    # The receivers are checked once the days to process are known (#353).
    site = MagicMock()
    site.site_name = "ExampleSite"
    with (
        patch("canvodpy.orchestrator.pipeline.ensure_file_logging"),
        patch("canvodpy.orchestrator.pipeline.clear_discovery_cache"),
        patch(
            "canvodpy.orchestrator.pipeline.PipelineOrchestrator._find_files",
            side_effect=ValueError("no receivers"),
        ),
        pytest.raises(ValueError, match="no receivers"),
        PipelineOrchestrator(site) as orchestrator,
    ):
        orchestrator.preview_processing_plan()
    assert get_run_id() is None
