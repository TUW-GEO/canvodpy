"""Tests for how the pipeline schedules days from discovered files."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import canvodpy.orchestrator.discovery as discovery_module
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


def test_discovery_messages_bracket_the_real_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 'Found' time covers the listing, not a cache hit.

    The messages for a receiver bracket its directory scan: the start message
    comes before the (slow) listing and the reported seconds cover its real
    duration, so a run on a network drive says what it is doing while it
    waits.
    """
    _touch(tmp_path / "canopy", "FANA01INK_R_20250010000_15M_05S_AA.sbf")
    _touch(tmp_path / "ref", "FANR01INK_R_20250010000_15M_05S_AA.sbf")
    receivers = {
        "canopy_01": SimpleNamespace(
            type="canopy", directory="canopy", reader_format="sbf", recipe=None
        ),
        "reference_01": SimpleNamespace(
            type="reference", directory="ref", reader_format="sbf", recipe=None
        ),
    }
    site = SimpleNamespace(
        site_name="fangorn",
        _site_config=SimpleNamespace(
            receivers=receivers,
            get_base_path=lambda: tmp_path,
            resolve_paired_canopies=lambda name: ["canopy_01"],
        ),
    )
    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orch.site = site
    events: list[tuple] = []
    orch._on_discovery_start = lambda name, folder: events.append(
        ("start", name, time.monotonic())
    )
    orch._on_discovery_end = lambda name, n_files, n_days, seconds: events.append(
        ("end", name, time.monotonic(), seconds)
    )

    original = discovery_module._scan_directory
    scan_markers: list[float | tuple] = []
    clear_discovery_cache()

    def slow_scan(directory: Path, recipe: Path | None):
        scan_markers.append(time.monotonic())
        time.sleep(0.5)
        result = original(directory, recipe)
        scan_markers.append(time.monotonic())
        return result

    monkeypatch.setattr(discovery_module, "_scan_directory", slow_scan)
    orch._warm_and_report_discovery()

    # One start and one end per receiver, in receiver order.
    assert events[0][0] == "start" and events[0][1] == "canopy_01"
    assert events[1][0] == "end" and events[1][1] == "canopy_01"
    assert events[2][0] == "start" and events[2][1] == "reference_01"
    assert events[3][0] == "end" and events[3][1] == "reference_01"
    # The start message precedes a receiver's first listing, and the end
    # message follows it, so the reported time covers the real scan.
    assert events[0][2] < scan_markers[0] < scan_markers[1] < events[1][2]
    for name in ("canopy_01", "reference_01"):
        end = next(e for e in events if e[0] == "end" and e[1] == name)
        assert end[3] >= 0.5, end


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
