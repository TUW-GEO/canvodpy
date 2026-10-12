"""Tests for FilenameMapper.detect_overlaps."""

from __future__ import annotations

from pathlib import Path

import pytest

from canvod.preflight import CanVODFilename, FilenameMapper, find_overlaps
from canvod.preflight.mapping import VirtualFile
from canvod.utils import testing

# Tests of the deprecated mapping and validation API, see test_deprecations.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


def _vf(
    period: str = "01D",
    hour: int = 0,
    minute: int = 0,
    doy: int = 1,
    year: int = 2025,
) -> VirtualFile:
    """Create a VirtualFile with the given parameters."""
    cn = CanVODFilename(
        site=testing.SITE_ID,
        receiver_type="R",
        receiver_number=1,
        agency=testing.AGENCY,
        year=year,
        doy=doy,
        hour=hour,
        minute=minute,
        period=period,
        sampling="05S",
        content="AA",
        file_type="rnx",
    )
    return VirtualFile(
        physical_path=Path(f"/data/{cn.name}"),
        conventional_name=cn,
    )


class TestOverlapDetection:
    """Test FilenameMapper.detect_overlaps."""

    def test_daily_vs_subdaily(self):
        """01D file with 15M files for same day -> overlaps."""
        vfs = [
            _vf(period="01D", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=15),
            _vf(period="15M", hour=0, minute=30),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        # Daily overlaps each 15M file: 3 pairs
        assert len(overlaps) == 3

    def test_non_overlapping_subdaily(self):
        """Non-overlapping 15M files -> clean."""
        vfs = [
            _vf(period="15M", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=15),
            _vf(period="15M", hour=0, minute=30),
            _vf(period="15M", hour=0, minute=45),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_different_days_no_overlap(self):
        """Files on different DOYs never overlap."""
        vfs = [
            _vf(period="01D", doy=1),
            _vf(period="01D", doy=2),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_hourly_overlap_with_daily(self):
        """01H files overlap with 01D on same day."""
        vfs = [
            _vf(period="01D", hour=0),
            _vf(period="01H", hour=0),
            _vf(period="01H", hour=1),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 2  # daily overlaps both hourly

    def test_single_file_no_overlap(self):
        """Single file -> no overlaps."""
        vfs = [_vf()]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_empty_list(self):
        """Empty list -> no overlaps."""
        assert FilenameMapper.detect_overlaps([]) == []

    def test_adjacent_hourly_files(self):
        """Adjacent 01H files don't overlap (00:00-01:00 and 01:00-02:00)."""
        vfs = [
            _vf(period="01H", hour=0),
            _vf(period="01H", hour=1),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0


def _cn(name: str) -> CanVODFilename:
    return CanVODFilename.from_filename(name)


class TestFindOverlaps:
    """Test find_overlaps, the one overlap check on canonical names."""

    def test_named_span(self):
        cn = _cn("FANR01INK_R_20250012345_15M_05S_AA.rnx")
        assert (cn.start.isoformat(), cn.end.isoformat()) == (
            "2025-01-01T23:45:00",
            "2025-01-02T00:00:00",
        )

    def test_equal_spans_overlap(self):
        a = _cn("FANR01INK_R_20250010000_15M_05S_AA.rnx")
        b = _cn("FANR01INK_R_20250010000_15M_01S_AA.rnx")
        assert find_overlaps([a, b]) == [(a, b)]

    def test_partial_overlap(self):
        a = _cn("FANR01INK_R_20250010000_01H_05S_AA.rnx")
        b = _cn("FANR01INK_R_20250010030_01H_05S_AA.rnx")
        assert find_overlaps([b, a]) == [(a, b)]

    def test_span_past_midnight_overlaps_next_day(self):
        a = _cn("FANR01INK_R_20250011200_01D_05S_AA.rnx")
        b = _cn("FANR01INK_R_20250020000_15M_05S_AA.rnx")
        assert find_overlaps([a, b]) == [(a, b)]

    def test_file_types_and_receivers_are_separate(self):
        names = [
            "FANR01INK_R_20250010000_01D_05S_AA.rnx",
            "FANR01INK_R_20250010000_01D_05S_AA.sbf",
            "FANA01INK_R_20250010000_01D_05S_AA.rnx",
        ]
        assert find_overlaps([_cn(n) for n in names]) == []

    def test_key_maps_items_to_names(self):
        names = [
            "FANR01INK_R_20250010000_01D_05S_AA.rnx",
            "FANR01INK_R_20250010600_15M_05S_AA.rnx",
        ]
        assert find_overlaps(names, key=_cn) == [tuple(names)]
