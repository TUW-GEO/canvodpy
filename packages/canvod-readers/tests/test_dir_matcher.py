"""Unit tests for DataDirMatcher and PairDataDirMatcher.

Uses pytest tmp_path fixtures to create temporary directory structures.
No real GNSS data required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from canvod.readers.matching.dir_matcher import (
    DataDirMatcher,
    PairDataDirMatcher,
    _has_rinex_files,
)
from canvod.readers.matching.models import MatchedDirs, PairMatchedDirs

# ===================================================================
# Helpers
# ===================================================================


def _create_rinex_file(directory: Path, suffix: str = ".25o") -> Path:
    """Create a dummy RINEX observation file."""
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / f"test001a00{suffix}"
    f.write_text("dummy")
    return f


def _setup_standard_dirs(
    tmp_path: Path,
    ref_dates: list[str] | None = None,
    can_dates: list[str] | None = None,
) -> Path:
    """Create a standard directory structure with RINEX files.

    Returns the root directory.
    """
    root = tmp_path / "site"
    ref_base = root / "01_reference" / "01_GNSS" / "01_raw"
    can_base = root / "02_canopy" / "01_GNSS" / "01_raw"

    # Create base directories
    ref_base.mkdir(parents=True)
    can_base.mkdir(parents=True)

    for date_str in ref_dates or []:
        _create_rinex_file(ref_base / date_str)

    for date_str in can_dates or []:
        _create_rinex_file(can_base / date_str)

    return root


# ===================================================================
# _has_rinex_files
# ===================================================================


class TestHasRinexFiles:
    """Test the module-level RINEX file detection."""

    def test_empty_dir_returns_false(self, tmp_path):
        assert _has_rinex_files(tmp_path) is False

    def test_nonexistent_dir_returns_false(self, tmp_path):
        assert _has_rinex_files(tmp_path / "nonexistent") is False

    def test_dir_with_rinex_v2_obs(self, tmp_path):
        _create_rinex_file(tmp_path, suffix=".25o")
        assert _has_rinex_files(tmp_path) is True

    def test_dir_with_rinex_v3_obs(self, tmp_path):
        _create_rinex_file(tmp_path, suffix=".rnx")
        assert _has_rinex_files(tmp_path) is True

    def test_dir_with_sbf_files(self, tmp_path):
        _create_rinex_file(tmp_path, suffix=".25_")
        assert _has_rinex_files(tmp_path) is True

    def test_dir_with_uppercase_obs(self, tmp_path):
        _create_rinex_file(tmp_path, suffix=".O")
        assert _has_rinex_files(tmp_path) is True

    @pytest.mark.parametrize(
        "name",
        [
            "FANA00INK_R_20250010000_15M_05S_AA.sbf",
            "FANA00INK_R_20250010000_01D_30S_MO.rnx.gz",
            "fana0010.25o.gz",
            "fana001a00.25_.gz",
        ],
    )
    def test_dir_with_canonical_or_compressed_files(self, tmp_path, name):
        (tmp_path / name).write_text("")
        assert _has_rinex_files(tmp_path) is True

    def test_dir_with_unrelated_files(self, tmp_path):
        """Non-RINEX files should not trigger detection."""
        (tmp_path / "readme.txt").write_text("not RINEX")
        (tmp_path / "data.csv").write_text("not RINEX")
        assert _has_rinex_files(tmp_path) is False


# ===================================================================
# DataDirMatcher
# ===================================================================


class TestDataDirMatcher:
    """DataDirMatcher: match canopy+reference directories by date."""

    def test_basic_matching(self, tmp_path):
        """Dates present in both canopy and reference are matched."""
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25001", "25002", "25003"],
            can_dates=["25001", "25002", "25004"],
        )
        matcher = DataDirMatcher(root)
        dates = matcher.get_common_dates()
        assert dates == ["25001", "25002"]

    def test_no_common_dates(self, tmp_path):
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25001"],
            can_dates=["25002"],
        )
        matcher = DataDirMatcher(root)
        assert matcher.get_common_dates() == []

    def test_placeholder_00000_excluded(self, tmp_path):
        """The '00000' placeholder directory is always excluded."""
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["00000", "25001"],
            can_dates=["00000", "25001"],
        )
        matcher = DataDirMatcher(root)
        dates = matcher.get_common_dates()
        assert "00000" not in dates
        assert "25001" in dates

    def test_iteration_yields_matched_dirs(self, tmp_path):
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25001", "25002"],
            can_dates=["25001", "25002"],
        )
        matcher = DataDirMatcher(root)
        results = list(matcher)
        assert len(results) == 2
        assert all(isinstance(r, MatchedDirs) for r in results)

    def test_matched_dirs_paths_correct(self, tmp_path):
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25010"],
            can_dates=["25010"],
        )
        matcher = DataDirMatcher(root)
        results = list(matcher)
        assert len(results) == 1
        md = results[0]
        assert md.canopy_data_dir.name == "25010"
        assert md.reference_data_dir.name == "25010"

    def test_dates_returned_sorted(self, tmp_path):
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25100", "25010", "25050"],
            can_dates=["25100", "25010", "25050"],
        )
        matcher = DataDirMatcher(root)
        dates = matcher.get_common_dates()
        assert dates == sorted(dates)

    def test_custom_patterns(self, tmp_path):
        """Custom reference/canopy path patterns."""
        root = tmp_path / "site"
        ref = root / "ref_data"
        can = root / "can_data"
        _create_rinex_file(ref / "25001")
        _create_rinex_file(can / "25001")

        matcher = DataDirMatcher(
            root,
            reference_pattern=Path("ref_data"),
            canopy_pattern=Path("can_data"),
        )
        assert matcher.get_common_dates() == ["25001"]

    def test_missing_root_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Root"):
            DataDirMatcher(tmp_path / "nonexistent")

    def test_missing_reference_dir_raises(self, tmp_path):
        root = tmp_path / "site"
        (root / "02_canopy" / "01_GNSS" / "01_raw").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="Reference"):
            DataDirMatcher(root)

    def test_missing_canopy_dir_raises(self, tmp_path):
        root = tmp_path / "site"
        (root / "01_reference" / "01_GNSS" / "01_raw").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="Canopy"):
            DataDirMatcher(root)

    def test_empty_dirs_no_matches(self, tmp_path):
        """Both dirs exist but have no date subdirectories."""
        root = _setup_standard_dirs(tmp_path)
        matcher = DataDirMatcher(root)
        assert matcher.get_common_dates() == []

    def test_dir_without_rinex_not_matched(self, tmp_path):
        """Date dirs that exist but contain no RINEX files are excluded."""
        root = _setup_standard_dirs(
            tmp_path,
            ref_dates=["25001"],
            can_dates=["25001"],
        )
        # Also create a date dir in reference with non-RINEX files
        empty_dir = root / "01_reference" / "01_GNSS" / "01_raw" / "25002"
        empty_dir.mkdir()
        (empty_dir / "notes.txt").write_text("not rinex")
        # Add matching canopy dir with RINEX
        _create_rinex_file(root / "02_canopy" / "01_GNSS" / "01_raw" / "25002")
        matcher = DataDirMatcher(root)
        dates = matcher.get_common_dates()
        # 25002 should NOT be matched because reference has no RINEX
        assert "25002" not in dates
        assert "25001" in dates


# ===================================================================
# PairDataDirMatcher
# ===================================================================


class TestPairDataDirMatcher:
    """PairDataDirMatcher: multi-receiver pair matching."""

    @pytest.fixture
    def pair_setup(self, tmp_path):
        """Create a standard pair directory structure."""
        base = tmp_path / "site"
        receivers = {
            "canopy_01": {"directory": "02_canopy_01/01_GNSS/01_raw"},
            "reference_01": {"directory": "01_reference_01/01_GNSS/01_raw"},
        }
        pairs = {
            "pair_01": {
                "canopy_receiver": "canopy_01",
                "reference_receiver": "reference_01",
            }
        }
        # Create dirs with RINEX data
        for name, cfg in receivers.items():
            _create_rinex_file(base / cfg["directory"] / "25001")
            _create_rinex_file(base / cfg["directory"] / "25002")

        return base, receivers, pairs

    def test_basic_iteration(self, pair_setup):
        base, receivers, pairs = pair_setup
        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        assert len(results) == 2  # 2 dates × 1 pair
        assert all(isinstance(r, PairMatchedDirs) for r in results)

    def test_pair_name_in_result(self, pair_setup):
        base, receivers, pairs = pair_setup
        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        assert all(r.pair_name == "pair_01" for r in results)

    def test_receiver_names_in_result(self, pair_setup):
        base, receivers, pairs = pair_setup
        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        for r in results:
            assert r.canopy_receiver == "canopy_01"
            assert r.reference_receiver == "reference_01"

    def test_partial_date_coverage(self, tmp_path):
        """Only dates with both canopy AND reference RINEX data are yielded."""
        base = tmp_path / "site"
        receivers = {
            "canopy_01": {"directory": "can"},
            "reference_01": {"directory": "ref"},
        }
        pairs = {
            "p1": {
                "canopy_receiver": "canopy_01",
                "reference_receiver": "reference_01",
            }
        }
        _create_rinex_file(base / "can" / "25001")
        _create_rinex_file(base / "can" / "25002")
        _create_rinex_file(base / "ref" / "25001")
        # ref/25002 has no RINEX

        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        assert len(results) == 1
        assert results[0].yyyydoy.yydoy == "25001"

    def test_missing_directory_key_raises(self, tmp_path):
        """Receiver config missing 'directory' key must raise ValueError."""
        receivers = {"rx1": {"type": "canopy"}}  # missing "directory"
        with pytest.raises(ValueError, match="missing 'directory'"):
            PairDataDirMatcher(tmp_path, receivers, {})

    def test_placeholder_00000_excluded(self, tmp_path):
        """'00000' directories are excluded from date scanning."""
        base = tmp_path / "site"
        receivers = {
            "c": {"directory": "can"},
            "r": {"directory": "ref"},
        }
        pairs = {"p1": {"canopy_receiver": "c", "reference_receiver": "r"}}
        _create_rinex_file(base / "can" / "00000")
        _create_rinex_file(base / "ref" / "00000")
        _create_rinex_file(base / "can" / "25001")
        _create_rinex_file(base / "ref" / "25001")

        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        dates = [r.yyyydoy.yydoy for r in results]
        assert "00000" not in dates
        assert "25001" in dates

    def test_non_date_directories_ignored(self, tmp_path):
        """Non-5-digit dirs and non-numeric dirs are silently ignored."""
        base = tmp_path / "site"
        receivers = {"c": {"directory": "can"}, "r": {"directory": "ref"}}
        pairs = {"p1": {"canopy_receiver": "c", "reference_receiver": "r"}}

        # Create non-date directories
        _create_rinex_file(base / "can" / "readme")  # not 5 digits
        _create_rinex_file(base / "can" / "1234")  # only 4 digits
        _create_rinex_file(base / "can" / "abcde")  # not numeric
        _create_rinex_file(base / "ref" / "readme")
        _create_rinex_file(base / "ref" / "1234")
        _create_rinex_file(base / "ref" / "abcde")
        # Create one valid date
        _create_rinex_file(base / "can" / "25001")
        _create_rinex_file(base / "ref" / "25001")

        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        assert len(results) == 1

    def test_multiple_pairs(self, tmp_path):
        """Multiple analysis pairs yield results for each pair."""
        base = tmp_path / "site"
        receivers = {
            "c1": {"directory": "can1"},
            "c2": {"directory": "can2"},
            "r1": {"directory": "ref1"},
        }
        pairs = {
            "p1": {"canopy_receiver": "c1", "reference_receiver": "r1"},
            "p2": {"canopy_receiver": "c2", "reference_receiver": "r1"},
        }
        for rx in ("can1", "can2", "ref1"):
            _create_rinex_file(base / rx / "25001")

        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        assert len(results) == 2
        pair_names = {r.pair_name for r in results}
        assert pair_names == {"p1", "p2"}

    def test_results_sorted_by_date(self, tmp_path):
        base = tmp_path / "site"
        receivers = {"c": {"directory": "can"}, "r": {"directory": "ref"}}
        pairs = {"p1": {"canopy_receiver": "c", "reference_receiver": "r"}}
        for d in ("25100", "25010", "25050"):
            _create_rinex_file(base / "can" / d)
            _create_rinex_file(base / "ref" / d)

        matcher = PairDataDirMatcher(base, receivers, pairs)
        results = list(matcher)
        dates = [r.yyyydoy for r in results]
        assert dates == sorted(dates)

    def test_has_data_decides_which_days_match(self, pair_setup):
        """An injected ``has_data`` replaces the filename-glob check."""
        base, receivers, pairs = pair_setup
        calls = []

        def has_data(receiver, path):
            calls.append(receiver)
            return path.name == "25002"

        matcher = PairDataDirMatcher(base, receivers, pairs, has_data=has_data)
        results = list(matcher)
        assert [r.yyyydoy.to_str() for r in results] == ["2025002"]
        assert set(calls) == {"canopy_01", "reference_01"}

    def test_is_deprecated(self, pair_setup):
        """The pipeline finds days through its own discovery now."""
        base, receivers, pairs = pair_setup
        with pytest.warns(FutureWarning, match="left over from development"):
            PairDataDirMatcher(base, receivers, pairs)
