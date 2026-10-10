"""A pipeline created from Python sets a run_id, like ``canvodpy run``."""

import re
from contextlib import ExitStack
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


def test_new_run_id_format():
    assert re.fullmatch(r"ExampleSite-\d{8}-\d{6}", new_run_id("ExampleSite"))


def test_sets_run_id_until_closed(make_orchestrator):
    assert get_run_id() is None
    with make_orchestrator():
        assert re.fullmatch(r"ExampleSite-\d{8}-\d{6}", get_run_id() or "")
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
    site = MagicMock()
    site.site_name = "ExampleSite"
    with (
        patch("canvodpy.orchestrator.pipeline.ensure_file_logging"),
        patch("canvodpy.orchestrator.pipeline.clear_discovery_cache"),
        patch(
            "canvodpy.orchestrator.pipeline.check_receivers",
            side_effect=ValueError("no receivers"),
        ),
        pytest.raises(ValueError, match="no receivers"),
    ):
        PipelineOrchestrator(site)
    assert get_run_id() is None
