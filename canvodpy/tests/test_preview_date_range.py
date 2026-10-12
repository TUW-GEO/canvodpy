"""Regression tests for date-range-aware preview_processing_plan().

``canvodpy run --dry-run`` used to ignore ``--start``/``--end`` entirely:
the CLI's dry-run branch called ``pipeline.preview()`` with no arguments at
all, and ``PipelineOrchestrator.preview_processing_plan()`` itself had no
date-range parameter to receive one -- both the CLI's dry-run and the real
``process_range(dry_run=True)`` path's own ``print_preview()`` call always
showed every available date instead of the requested window.

``PipelineOrchestrator`` has no lightweight unit-test harness (requires a
real ``GnssResearchSite``) -- these tests build a bare instance via
``object.__new__`` (bypassing ``__init__``) and set only the attributes
``preview_processing_plan``/``_filter_dates`` actually touch, the same
technique already used for ``RinexDataProcessor`` in
``test_shared_aux_cache.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from canvodpy.orchestrator.discovery import ReceiverDay
from canvodpy.orchestrator.pipeline import PipelineOrchestrator


def _fake_orchestrator(
    grouped: dict, receivers: dict | None = None
) -> PipelineOrchestrator:
    orch = object.__new__(PipelineOrchestrator)
    site_config = SimpleNamespace(
        receivers=receivers or {}, get_base_path=lambda: Path("/nonexistent")
    )
    orch.site = SimpleNamespace(site_name="test_site", _site_config=site_config)
    orch._logger = mock.MagicMock()
    orch._group_by_date_and_receiver = lambda: grouped
    return orch


def _grouped_fixture(tmp_path: Path) -> dict:
    return {
        date: {
            "canopy_01": (
                ReceiverDay("canopy_01", tmp_path, date),
                "canopy",
                None,
                "sbf",
            )
        }
        for date in ("2025001", "2025002", "2025003")
    }


def test_preview_defaults_to_full_range(tmp_path: Path) -> None:
    orch = _fake_orchestrator(_grouped_fixture(tmp_path))
    plan = orch.preview_processing_plan()
    assert [d["date"] for d in plan["dates"]] == ["2025001", "2025002", "2025003"]


def test_preview_respects_start_end(tmp_path: Path) -> None:
    orch = _fake_orchestrator(_grouped_fixture(tmp_path))
    plan = orch.preview_processing_plan(start="2025002", end="2025002")
    assert [d["date"] for d in plan["dates"]] == ["2025002"]


def test_preview_respects_start_only(tmp_path: Path) -> None:
    orch = _fake_orchestrator(_grouped_fixture(tmp_path))
    plan = orch.preview_processing_plan(start="2025002")
    assert [d["date"] for d in plan["dates"]] == ["2025002", "2025003"]


def test_preview_respects_end_only(tmp_path: Path) -> None:
    orch = _fake_orchestrator(_grouped_fixture(tmp_path))
    plan = orch.preview_processing_plan(end="2025002")
    assert [d["date"] for d in plan["dates"]] == ["2025001", "2025002"]


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def test_preview_counts_files_like_the_run(tmp_path: Path) -> None:
    """The dry run counts the files a run would read (canonical names by
    ``reader_format``), not RINEX v2 short names only."""
    rnx_dir = tmp_path / "rnx"
    sbf_dir = tmp_path / "sbf"
    _touch(
        rnx_dir,
        "FANA01INK_R_20250010000_15M_05S_AA.rnx",
        "FANA01INK_R_20250010015_15M_05S_AA.rnx",
        "notes.txt",
    )
    _touch(sbf_dir, "FANR01INK_R_20250010000_15M_05S_AA.sbf")
    grouped = {
        "2025001": {
            "canopy_01": (
                ReceiverDay("canopy_01", rnx_dir, "2025001"),
                "canopy",
                None,
                "rinex3",
            ),
            "reference_01_canopy_01": (
                ReceiverDay("reference_01", sbf_dir, "2025001"),
                "reference",
                None,
                "sbf",
            ),
        }
    }
    orch = _fake_orchestrator(grouped)
    with mock.patch.dict("sys.modules", {"canvod.filemap.patterns": None}):
        plan = orch.preview_processing_plan()
    files = {r["name"]: r["files"] for r in plan["dates"][0]["receivers"]}
    assert files == {"canopy_01": 2, "reference_01_canopy_01": 1}
    assert plan["total_files"] == 3
