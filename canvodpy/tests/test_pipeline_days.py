"""Tests for how the pipeline schedules days from discovered files."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from canvodpy.orchestrator.discovery import ReceiverDay, clear_discovery_cache
from canvodpy.orchestrator.pipeline import PipelineOrchestrator


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def _orchestrator(base: Path, canopy_format: str = "sbf") -> PipelineOrchestrator:
    receivers = {
        "canopy_01": SimpleNamespace(
            type="canopy", directory="canopy", reader_format=canopy_format, recipe=None
        ),
        "reference_01": SimpleNamespace(
            type="reference", directory="ref", reader_format="auto", recipe=None
        ),
    }
    site_config = SimpleNamespace(
        receivers=receivers,
        get_base_path=lambda: base,
        resolve_paired_canopies=lambda name: ["canopy_01"],
    )
    orch = object.__new__(PipelineOrchestrator)
    orch.site = SimpleNamespace(
        site_name="fangorn",
        _site_config=site_config,
        vod_analyses={
            "a": {"canopy_receiver": "canopy_01", "reference_receiver": "reference_01"}
        },
    )
    orch._logger = mock.MagicMock()
    return orch


def test_days_where_both_receivers_have_files(tmp_path: Path) -> None:
    """Canopy files in one flat folder, reference files in YYDDD folders:
    only the days both receivers cover are scheduled."""
    clear_discovery_cache()
    _touch(
        tmp_path / "canopy",
        "FANA01INK_R_20250010000_15M_05S_AA.sbf",
        "FANA01INK_R_20250020000_15M_05S_AA.sbf",
    )
    _touch(tmp_path / "ref" / "25002", "FANR01INK_R_20250020000_15M_05S_AA.sbf")
    _touch(tmp_path / "ref" / "25003", "FANR01INK_R_20250030000_15M_05S_AA.sbf")

    grouped = _orchestrator(tmp_path)._group_by_date_and_receiver()

    assert list(grouped) == ["2025002"]
    canopy_day, _, canopy_pos, canopy_fmt = grouped["2025002"]["canopy_01"]
    assert canopy_day == ReceiverDay("canopy_01", tmp_path / "canopy", "2025002")
    assert (canopy_pos, canopy_fmt) == (None, "sbf")
    ref_day, ref_type, ref_pos, ref_fmt = grouped["2025002"]["reference_01_canopy_01"]
    assert ref_day == ReceiverDay("reference_01", tmp_path / "ref", "2025002")
    assert ref_type == "reference"
    assert ref_pos == canopy_day  # the canopy's same day gives the position
    assert ref_fmt == "sbf"  # detected, the receiver is configured as auto


def test_unprocessed_files_are_warned_about_not_fatal(tmp_path: Path) -> None:
    """Files the run never reads are reported in one warning per receiver
    (counted per file type), and the readable files are still scheduled."""
    clear_discovery_cache()
    _touch(
        tmp_path / "canopy",
        "FANA01INK_R_20250020000_15M_05S_AA.sbf",
        "FANA01INK_R_20250020015_15M_05S_AA.rnx",  # canopy reads sbf only
        "rosa0020.25o",  # not a canonical name, no recipe
        "rosa0030.25o",
    )
    _touch(tmp_path / "ref", "FANR01INK_R_20250020000_15M_05S_AA.sbf")
    orch = _orchestrator(tmp_path)

    grouped = orch._group_by_date_and_receiver()

    assert list(grouped) == ["2025002"]
    orch._logger.warning.assert_called_once()
    event, fields = (
        orch._logger.warning.call_args.args[0],
        orch._logger.warning.call_args.kwargs,
    )
    assert event == "files_not_processed"
    assert fields["receiver"] == "canopy_01"
    assert fields["n_files"] == 3
    assert fields["by_file_type"] == {
        ".##o": "2 (e.g. rosa0020.25o)",
        ".rnx": "1 (e.g. FANA01INK_R_20250020015_15M_05S_AA.rnx)",
    }


def test_canopy_and_reference_of_different_formats_fail(tmp_path: Path) -> None:
    """A reference detected as SBF next to a RINEX 3 canopy stops the run
    before any file is read (mixed formats are not supported)."""
    clear_discovery_cache()
    _touch(tmp_path / "canopy", "FANA01INK_R_20250020000_15M_05S_AA.rnx")
    _touch(tmp_path / "ref", "FANR01INK_R_20250020000_15M_05S_AA.sbf")

    with pytest.raises(ValueError, match="same file format"):
        _orchestrator(tmp_path, canopy_format="rinex3")._group_by_date_and_receiver()


def test_compressed_files_get_their_own_warning(tmp_path: Path) -> None:
    _touch(
        tmp_path / "canopy",
        "FANA01INK_R_20250020000_15M_05S_AA.sbf",
        "FANA01INK_R_20250020015_15M_05S_AA.sbf.gz",
        "FANA01INK_R_20250020030_15M_05S_AA.sbf.zip",
    )
    _touch(tmp_path / "ref", "FANR01INK_R_20250020000_15M_05S_AA.sbf")
    orch = _orchestrator(tmp_path)

    grouped = orch._group_by_date_and_receiver()

    assert list(grouped) == ["2025002"]
    orch._logger.warning.assert_called_once()
    event, fields = (
        orch._logger.warning.call_args.args[0],
        orch._logger.warning.call_args.kwargs,
    )
    assert event == "compressed_files_not_processed"
    assert fields["n_files"] == 2
    assert fields["by_file_type"] == {
        ".sbf.gz": "1 (e.g. FANA01INK_R_20250020015_15M_05S_AA.sbf.gz)",
        ".sbf.zip": "1 (e.g. FANA01INK_R_20250020030_15M_05S_AA.sbf.zip)",
    }
    assert "does not decompress" in fields["hint"]
