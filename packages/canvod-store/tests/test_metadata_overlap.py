"""Tests for metadata_row_exists temporal overlap detection.

Verifies that the store correctly detects:
- Exact hash matches (file already ingested)
- Temporal overlaps (daily file covering sub-daily intervals)
- Non-overlapping intervals (safe to ingest)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import new_gnss_store


def _make_dataset(start: str, end: str, n_epochs: int = 10) -> xr.Dataset:
    """Create a minimal dataset with epoch dimension and File Hash attr."""
    epochs = np.linspace(
        np.datetime64(start).astype("int64"),
        np.datetime64(end).astype("int64"),
        n_epochs,
    ).astype("datetime64[ns]")
    return xr.Dataset(
        {"SNR": (["epoch", "sid"], np.random.rand(n_epochs, 3).astype(np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C", "G03|L1|C"],
        },
        attrs={"File Hash": f"hash_{start}_{end}"},
    )


@pytest.fixture
def gnss_store(tmp_path: Path):
    """Create a GNSS store with one 15-min file already ingested."""
    store = new_gnss_store(tmp_path / "test_rinex")

    # Write initial group with a 15-min dataset
    ds = _make_dataset("2025-01-01T00:00:00", "2025-01-01T00:14:55")
    store.write_initial_group(
        dataset=ds, group_name="canopy_01", commit_message="initial"
    )

    # Append metadata for this file
    store.append_metadata(
        group_name="canopy_01",
        rinex_hash="hash_15min_file_1",
        start=np.datetime64("2025-01-01T00:00:00", "ns"),
        end=np.datetime64("2025-01-01T00:14:55", "ns"),
        snapshot_id="snap1",
        action="write",
        commit_msg="wrote 15min file 1",
        dataset_attrs={"File Hash": "hash_15min_file_1"},
    )

    # Append a second 15-min file's metadata
    store.append_metadata(
        group_name="canopy_01",
        rinex_hash="hash_15min_file_2",
        start=np.datetime64("2025-01-01T00:15:00", "ns"),
        end=np.datetime64("2025-01-01T00:29:55", "ns"),
        snapshot_id="snap2",
        action="write",
        commit_msg="wrote 15min file 2",
        dataset_attrs={"File Hash": "hash_15min_file_2"},
    )

    return store


class TestHashMatch:
    """Test exact hash match detection."""

    def test_exact_hash_detected(self, gnss_store) -> None:
        """File with same hash as existing entry is detected."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_15min_file_1",
            start=np.datetime64("2025-01-01T00:00:00", "ns"),
            end=np.datetime64("2025-01-01T00:14:55", "ns"),
        )
        assert exists is True
        assert matches.height == 1

    def test_unknown_hash_no_overlap(self, gnss_store) -> None:
        """File with new hash and non-overlapping interval passes."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_new_file",
            start=np.datetime64("2025-01-01T00:30:00", "ns"),
            end=np.datetime64("2025-01-01T00:44:55", "ns"),
        )
        assert exists is False
        assert matches.is_empty()


class TestTemporalOverlap:
    """Test temporal overlap detection (the daily-file scenario)."""

    def test_daily_file_overlapping_15min_files(self, gnss_store) -> None:
        """Daily file covering existing 15-min intervals is detected."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_daily_file",
            start=np.datetime64("2025-01-01T00:00:00", "ns"),
            end=np.datetime64("2025-01-01T23:59:55", "ns"),
        )
        assert exists is True
        assert matches.height == 2  # Both 15-min files overlap

    def test_partial_overlap_start(self, gnss_store) -> None:
        """File that partially overlaps at the start is detected."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_partial",
            start=np.datetime64("2025-01-01T00:10:00", "ns"),
            end=np.datetime64("2025-01-01T00:20:00", "ns"),
        )
        assert exists is True
        assert matches.height == 2  # Overlaps both files

    def test_partial_overlap_end(self, gnss_store) -> None:
        """File that overlaps only the second 15-min file is detected."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_partial_end",
            start=np.datetime64("2025-01-01T00:20:00", "ns"),
            end=np.datetime64("2025-01-01T00:40:00", "ns"),
        )
        assert exists is True
        assert matches.height == 1  # Only second file overlaps

    def test_adjacent_intervals_no_overlap(self, gnss_store) -> None:
        """File immediately after existing intervals is not flagged."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="canopy_01",
            rinex_hash="hash_adjacent",
            start=np.datetime64("2025-01-01T00:30:00", "ns"),
            end=np.datetime64("2025-01-01T00:44:55", "ns"),
        )
        assert exists is False

    def test_nonexistent_group(self, gnss_store) -> None:
        """Query for a group that doesn't exist returns False."""
        exists, matches = gnss_store.metadata_row_exists(
            group_name="nonexistent_group",
            rinex_hash="hash_whatever",
            start=np.datetime64("2025-01-01T00:00:00", "ns"),
            end=np.datetime64("2025-01-01T00:14:55", "ns"),
        )
        assert exists is False
        assert matches.is_empty()


class TestBatchTemporalOverlap:
    """Test check_temporal_overlaps (batch temporal overlap detection)."""

    def test_daily_file_detected_in_batch(self, gnss_store) -> None:
        """Daily file overlapping existing 15-min files is flagged."""
        intervals = [
            (
                "hash_daily",
                np.datetime64("2025-01-01T00:00:00", "ns"),
                np.datetime64("2025-01-01T23:59:55", "ns"),
            ),
        ]
        overlaps = gnss_store.check_temporal_overlaps("canopy_01", intervals)
        assert "hash_daily" in overlaps

    def test_non_overlapping_passes_batch(self, gnss_store) -> None:
        """File after existing intervals is not flagged."""
        intervals = [
            (
                "hash_new",
                np.datetime64("2025-01-01T00:30:00", "ns"),
                np.datetime64("2025-01-01T00:44:55", "ns"),
            ),
        ]
        overlaps = gnss_store.check_temporal_overlaps("canopy_01", intervals)
        assert len(overlaps) == 0

    def test_mixed_batch(self, gnss_store) -> None:
        """Batch with one overlapping and one clean file."""
        intervals = [
            (
                "hash_overlap",
                np.datetime64("2025-01-01T00:10:00", "ns"),
                np.datetime64("2025-01-01T00:20:00", "ns"),
            ),
            (
                "hash_clean",
                np.datetime64("2025-01-02T00:00:00", "ns"),
                np.datetime64("2025-01-02T00:14:55", "ns"),
            ),
        ]
        overlaps = gnss_store.check_temporal_overlaps("canopy_01", intervals)
        assert "hash_overlap" in overlaps
        assert "hash_clean" not in overlaps


class TestShouldSkipFile:
    """Test should_skip_file — the public 3-layer early-exit check."""

    def test_skip_exact_hash(self, gnss_store) -> None:
        """Returns (True, 'hash_match') for a file already ingested."""
        skip, reason = gnss_store.should_skip_file(
            group_name="canopy_01",
            file_hash="hash_15min_file_1",
            time_start=np.datetime64("2025-01-01T00:00:00", "ns"),
            time_end=np.datetime64("2025-01-01T00:14:55", "ns"),
        )
        assert skip is True
        assert reason == "hash_match"

    def test_skip_temporal_overlap(self, gnss_store) -> None:
        """Returns (True, 'temporal_overlap') for new hash but overlapping range."""
        skip, reason = gnss_store.should_skip_file(
            group_name="canopy_01",
            file_hash="hash_new_daily_file",
            time_start=np.datetime64("2025-01-01T00:00:00", "ns"),
            time_end=np.datetime64("2025-01-01T23:59:55", "ns"),
        )
        assert skip is True
        assert reason == "temporal_overlap"

    def test_no_skip_new_file(self, gnss_store) -> None:
        """Returns (False, '') for a new file with no overlap."""
        skip, reason = gnss_store.should_skip_file(
            group_name="canopy_01",
            file_hash="hash_next_15min",
            time_start=np.datetime64("2025-01-01T00:30:00", "ns"),
            time_end=np.datetime64("2025-01-01T00:44:55", "ns"),
        )
        assert skip is False
        assert reason == ""

    def test_no_skip_when_hash_is_none(self, gnss_store) -> None:
        """Returns (False, '') when file_hash is None (cannot check)."""
        skip, reason = gnss_store.should_skip_file(
            group_name="canopy_01",
            file_hash=None,
            time_start=np.datetime64("2025-01-01T00:00:00", "ns"),
            time_end=np.datetime64("2025-01-01T23:59:55", "ns"),
        )
        assert skip is False
        assert reason == ""

    def test_no_skip_fresh_group(self, gnss_store) -> None:
        """Returns (False, '') when the group does not yet exist."""
        skip, reason = gnss_store.should_skip_file(
            group_name="canopy_99",
            file_hash="hash_anything",
            time_start=np.datetime64("2025-01-01T00:00:00", "ns"),
            time_end=np.datetime64("2025-01-01T00:14:55", "ns"),
        )
        assert skip is False
        assert reason == ""

    def test_empty_intervals(self, gnss_store) -> None:
        """Empty interval list returns empty set."""
        overlaps = gnss_store.check_temporal_overlaps("canopy_01", [])
        assert len(overlaps) == 0

    def test_nonexistent_group_batch(self, gnss_store) -> None:
        """Non-existent group returns empty set."""
        intervals = [
            (
                "hash_x",
                np.datetime64("2025-01-01T00:00:00", "ns"),
                np.datetime64("2025-01-01T23:59:55", "ns"),
            ),
        ]
        overlaps = gnss_store.check_temporal_overlaps("no_group", intervals)
        assert len(overlaps) == 0


class TestAppendToGroupGuardrail:
    """Test that append_to_group blocks overlapping data."""

    def test_append_blocked_when_overlapping(self, gnss_store) -> None:
        """Appending a dataset that overlaps existing data is silently skipped."""
        ds = _make_dataset("2025-01-01T00:00:00", "2025-01-01T00:14:55")
        ds.attrs["File Hash"] = "hash_new_but_overlapping"

        # Should not raise, but should be silently skipped
        gnss_store.append_to_group(dataset=ds, group_name="canopy_01", action="write")

        # Verify no extra data was appended (epoch count unchanged)
        result = gnss_store.read_group("canopy_01")
        assert result.dims["epoch"] == 10  # same as fixture

    def test_append_allowed_when_no_overlap(self, gnss_store) -> None:
        """Appending a dataset with no overlap succeeds."""
        ds = _make_dataset("2025-01-02T00:00:00", "2025-01-02T00:14:55")
        ds.attrs["File Hash"] = "hash_day2"

        gnss_store.append_to_group(dataset=ds, group_name="canopy_01", action="write")

        result = gnss_store.read_group("canopy_01")
        assert result.dims["epoch"] == 20  # 10 + 10


class TestRootAttrs:
    """Test root-level store attributes."""

    def test_set_and_get_root_attrs(self, tmp_path: Path) -> None:
        store = new_gnss_store(tmp_path / "test_attrs")
        assert "version" not in store.get_root_attrs()

        store.set_root_attrs({"source_format": "sbf", "version": "1.0"})
        attrs = store.get_root_attrs()
        assert attrs["source_format"] == "sbf"
        assert attrs["version"] == "1.0"
        assert store.source_format == "sbf"

    def test_source_format_property(self, tmp_path: Path) -> None:
        store = new_gnss_store(tmp_path / "test_fmt")
        store.set_root_attrs({"source_format": "rinex3"})
        assert store.source_format == "rinex3"
