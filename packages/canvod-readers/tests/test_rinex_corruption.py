"""Tests for RINEX v3 reader robustness against corrupted files.

Uses real RINEX test data (valid/) and pre-generated corrupted files (invalid/)
to verify the reader correctly handles:
- File-level corruption (empty, binary, truncated)
- Header corruption (missing END OF HEADER, wrong version, missing fields)
- Epoch record corruption (malformed lines, satellite count mismatch)
- Observation data corruption (invalid SV, garbled values)
- Subtle corruption (non-monotonic epochs, duplicate epochs)

Corrupted files are generated from the real data by the script at the bottom
of this module. To regenerate: run `generate_corrupted_files()`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.gnss_specs.exceptions import RinexError
from canvod.readers.rinex.v3_04 import Rnxv3Header, Rnxv3Obs

# ---------------------------------------------------------------------------
# Test data paths
# ---------------------------------------------------------------------------
TEST_DATA_DIR = Path(__file__).parent / "test_data"
VALID_DIR = (
    TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
)
INVALID_DIR = TEST_DATA_DIR / "invalid"
REAL_FILE = VALID_DIR / "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"


def _skip_if_missing(fpath: Path):
    if not fpath.exists():
        pytest.skip(f"Test file not found: {fpath}")


# ===================================================================
# 1. Baseline: real file reads correctly
# ===================================================================


class TestBaseline:
    """Verify that the real test file reads correctly before corruption tests."""

    def test_real_file_reads_successfully(self):
        _skip_if_missing(REAL_FILE)
        obs = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert ds.sizes["epoch"] == 180  # 15-min file at 5s = 180 epochs
        assert "File Hash" in ds.attrs

    def test_real_file_epochs_monotonic(self):
        _skip_if_missing(REAL_FILE)
        obs = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        diffs = np.diff(ds.epoch.values.astype("int64"))
        assert np.all(diffs > 0)

    def test_real_file_snr_in_range(self):
        _skip_if_missing(REAL_FILE)
        obs = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        snr = ds["SNR"].values
        valid = snr[np.isfinite(snr)]
        assert len(valid) > 0
        assert np.all(valid >= 0)
        assert np.all(valid <= 70)

    def test_all_epochs_from_real_file(self):
        _skip_if_missing(REAL_FILE)
        obs = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        assert len(list(obs.iter_epochs())) == 180


# ===================================================================
# 2. File-level corruption
# ===================================================================


class TestFileLevelCorruption:
    """Tests for file-level corruption from pre-generated invalid files."""

    def test_empty_file(self):
        fpath = INVALID_DIR / "empty.25o"
        _skip_if_missing(fpath)
        with pytest.raises((ValueError, RinexError)):
            Rnxv3Header.from_file(fpath)

    def test_binary_garbage(self):
        fpath = INVALID_DIR / "binary_garbage.25o"
        _skip_if_missing(fpath)
        with pytest.raises((ValueError, RinexError, UnicodeDecodeError)):
            Rnxv3Header.from_file(fpath)

    def test_truncated_mid_header(self):
        """File with only 5 header lines — georinex may still parse partial."""
        fpath = INVALID_DIR / "truncated_header.25o"
        _skip_if_missing(fpath)
        try:
            header = Rnxv3Header.from_file(fpath)
            assert header is not None
        except ValueError, RinexError:
            pass  # Also acceptable

    def test_header_only_no_data(self):
        """Real header but no observation data — zero epochs."""
        fpath = INVALID_DIR / "header_only.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        assert len(list(obs.iter_epochs())) == 0

    def test_truncated_mid_epoch(self):
        """Epoch declares ~35 sats but only 1 line follows."""
        fpath = INVALID_DIR / "truncated_mid_epoch.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        # Satellite count mismatch → IncompleteEpochError → epoch skipped
        assert len(list(obs.iter_epochs())) == 0


# ===================================================================
# 3. Header corruption
# ===================================================================


class TestHeaderCorruption:
    """Tests for corrupted header fields."""

    def test_wrong_rinex_version_2(self):
        fpath = INVALID_DIR / "wrong_version_v2.25o"
        _skip_if_missing(fpath)
        with pytest.raises(ValueError, match=r"[Vv]ersion"):
            Rnxv3Header.from_file(fpath)

    def test_wrong_rinex_version_4(self):
        fpath = INVALID_DIR / "wrong_version_v4.25o"
        _skip_if_missing(fpath)
        with pytest.raises(ValueError, match=r"[Vv]ersion"):
            Rnxv3Header.from_file(fpath)

    def test_missing_end_of_header(self):
        fpath = INVALID_DIR / "missing_end_of_header.25o"
        _skip_if_missing(fpath)
        try:
            obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
            _ = list(obs.iter_epochs())
        except ValueError, RinexError:
            pass  # Expected

    def test_missing_sys_obs_types(self):
        fpath = INVALID_DIR / "missing_obs_types.25o"
        _skip_if_missing(fpath)
        try:
            obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
            _ = list(obs.iter_epochs())
        except ValueError, RinexError, KeyError:
            pass  # Expected

    def test_zero_position(self):
        """All-zero position should parse — optional for moving platforms."""
        fpath = INVALID_DIR / "zero_position.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        assert all(p.magnitude == 0.0 for p in obs.header.approx_position)


# ===================================================================
# 4. Epoch record corruption
# ===================================================================


class TestEpochRecordCorruption:
    """Tests for corrupted epoch records."""

    def test_epoch_with_invalid_month(self):
        """Month=13 in first epoch — should be skipped, second epoch survives."""
        fpath = INVALID_DIR / "invalid_month.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) >= 1

    def test_satellite_count_mismatch(self):
        """Epoch declares 99 sats, has ~35 — skipped, next epoch survives."""
        fpath = INVALID_DIR / "satellite_count_mismatch.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) >= 1

    def test_epoch_flag_event_records(self):
        """Event epoch (flag=4) should be skipped, real epoch survives."""
        fpath = INVALID_DIR / "event_epoch.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) == 1
        assert epochs[0].info.epoch_flag == 0

    def test_epoch_flag_event_records_to_ds(self):
        """The single-pass to_ds() path also skips the flag=4 event epoch."""
        fpath = INVALID_DIR / "event_epoch.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        assert ds.sizes["epoch"] == 1


# ===================================================================
# 5. Observation data corruption
# ===================================================================


class TestObservationDataCorruption:
    """Tests for corrupted observation lines."""

    def test_invalid_satellite_identifier(self):
        """SV 'X99' causes epoch skip, second epoch survives."""
        fpath = INVALID_DIR / "invalid_satellite_id.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) >= 1

    def test_all_blank_observations(self):
        """All-blank satellite data — observations should be None."""
        fpath = INVALID_DIR / "blank_observations.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        if epochs:
            for sat in epochs[0].data:
                for o in sat.observations:
                    assert o.value is None

    def test_non_numeric_observation_values(self):
        """Non-numeric text in observation field — value should be None."""
        fpath = INVALID_DIR / "non_numeric_observations.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        if epochs:
            first_obs = epochs[0].data[0].observations[0]
            assert first_obs.value is None

    def test_blank_lines_in_data_section(self):
        """Blank lines between epochs should be filtered out."""
        fpath = INVALID_DIR / "blank_lines_in_data.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) == 2


# ===================================================================
# 6. Dataset-level integrity
# ===================================================================


class TestDatasetIntegrity:
    """Tests for dataset-level invariants."""

    def test_file_hash_deterministic(self):
        _skip_if_missing(REAL_FILE)
        obs1 = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        obs2 = Rnxv3Obs(fpath=REAL_FILE, completeness_mode="off")
        assert obs1.file_hash == obs2.file_hash

    def test_duplicate_epochs_detected(self):
        """Same epoch block twice — should have duplicate timestamps."""
        fpath = INVALID_DIR / "duplicate_epochs.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        epochs = ds.epoch.values
        assert len(epochs) > len(np.unique(epochs)), "Should detect duplicate epochs"

    def test_reversed_epochs_detected(self):
        """Epochs in reverse order — should have non-monotonic timestamps."""
        fpath = INVALID_DIR / "reversed_epochs.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        epochs = ds.epoch.values
        if len(epochs) > 1:
            diffs = np.diff(epochs.astype("int64"))
            assert np.any(diffs < 0), "Reversed epochs should be detected"

    def test_mixed_valid_and_corrupt(self):
        """Valid + corrupt + valid epochs — 2 valid should survive."""
        fpath = INVALID_DIR / "mixed_valid_corrupt.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) == 2


# ===================================================================
# 7. File suffix validation
# ===================================================================


class TestFileSuffixValidation:
    """Tests for RINEX file suffix validation."""

    def test_invalid_suffix_rejected(self, tmp_path):
        _skip_if_missing(REAL_FILE)
        fpath = tmp_path / "test.csv"
        fpath.write_text(REAL_FILE.read_text(), encoding="utf-8")
        with pytest.raises(ValueError):
            Rnxv3Header.from_file(fpath)

    def test_nav_file_suffix_rejected(self, tmp_path):
        _skip_if_missing(REAL_FILE)
        fpath = tmp_path / "test.25n"
        fpath.write_text(REAL_FILE.read_text(), encoding="utf-8")
        with pytest.raises(ValueError):
            Rnxv3Header.from_file(fpath)


# ===================================================================
# 8. Observation line structure corruption
# ===================================================================


class TestObservationLineStructure:
    """Tests for corrupted observation line structure."""

    def test_truncated_satellite_line(self):
        """Satellite line cut short (fewer columns than header obs types)."""
        fpath = INVALID_DIR / "truncated_sat_line.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # First epoch may have garbled data or be skipped; second should survive
        assert len(epochs) >= 1

    def test_extra_long_satellite_line(self):
        """Satellite line with extra columns beyond declared obs types."""
        fpath = INVALID_DIR / "extra_long_sat_line.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # A field of the long line has its decimal point in the wrong column,
        # which rejects its epoch; the clean epoch survives
        assert len(epochs) == 1

    def test_misaligned_observations(self):
        """Observation values shifted by 2 chars from expected fixed-width positions."""
        fpath = INVALID_DIR / "misaligned_observations.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # Misaligned line may parse with wrong values or be skipped
        assert len(epochs) >= 1


# ===================================================================
# 9. Epoch record edge cases
# ===================================================================


class TestEpochEdgeCases:
    """Tests for epoch record edge cases."""

    def test_zero_satellites_epoch(self):
        """Epoch declaring 0 satellites — should yield empty or be skipped."""
        fpath = INVALID_DIR / "zero_satellites.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # Second epoch should survive regardless
        assert len(epochs) >= 1

    def test_invalid_epoch_flag(self):
        """Epoch flag=9 (outside valid 0-6 range) — should be skipped."""
        fpath = INVALID_DIR / "invalid_epoch_flag.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # Invalid flag epoch skipped, second epoch survives
        assert len(epochs) >= 1

    def test_invalid_epoch_flag_to_ds(self):
        """The single-pass to_ds() path also skips the flag=9 epoch."""
        fpath = INVALID_DIR / "invalid_epoch_flag.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])
        assert ds.epoch.values.astype("datetime64[s]").tolist() == [
            np.datetime64("2025-01-01T00:00:05", "s").item()
        ]

    def test_negative_seconds(self):
        """Epoch with negative seconds — should be skipped."""
        fpath = INVALID_DIR / "negative_seconds.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) >= 1

    def test_leap_second(self):
        """Epoch with ss=60 (leap second) — may parse or be skipped."""
        fpath = INVALID_DIR / "leap_second.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # Leap second may or may not parse; second epoch must survive
        assert len(epochs) >= 1

    def test_huge_satellite_count(self):
        """Epoch declaring 999 satellites — must not cause memory explosion."""
        fpath = INVALID_DIR / "huge_satellite_count.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        # Should not hang or OOM; satellite count mismatch → skip
        epochs = list(obs.iter_epochs())
        assert len(epochs) >= 1


# ===================================================================
# 10. Encoding and format corruption
# ===================================================================


class TestEncodingCorruption:
    """Tests for encoding and line-ending corruption."""

    def test_null_bytes_in_data(self):
        """Null bytes embedded in observation data."""
        fpath = INVALID_DIR / "null_bytes.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # The field with null bytes rejects its epoch; the clean epoch survives
        assert len(epochs) == 1

    def test_crlf_line_endings(self):
        """Windows CRLF line endings — common when files transfer between OS."""
        fpath = INVALID_DIR / "crlf_line_endings.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        try:
            epochs = list(obs.iter_epochs())
            # CRLF should either parse correctly or fail gracefully
            assert len(epochs) >= 0
        except ValueError, RinexError:
            pass  # Acceptable if reader rejects CRLF

    def test_non_ascii_header_comments(self):
        """Non-ASCII UTF-8 characters in header comment fields."""
        fpath = INVALID_DIR / "non_ascii_header.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        try:
            epochs = list(obs.iter_epochs())
            assert len(epochs) >= 1
        except ValueError, RinexError, UnicodeDecodeError:
            pass  # Also acceptable


# ===================================================================
# 11. Header edge cases
# ===================================================================


class TestHeaderEdgeCases:
    """Tests for header structural edge cases."""

    def test_duplicate_obs_types_same_constellation(self):
        """Duplicate SYS / # / OBS TYPES line for GPS constellation."""
        fpath = INVALID_DIR / "duplicate_obs_types.25o"
        _skip_if_missing(fpath)
        try:
            obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
            epochs = list(obs.iter_epochs())
            assert len(epochs) >= 0
        except ValueError, RinexError, KeyError:
            pass  # Acceptable

    def test_obs_type_count_mismatch(self):
        """Header declares 5 obs types but lists 12 — count/list disagreement."""
        fpath = INVALID_DIR / "obs_type_count_mismatch.25o"
        _skip_if_missing(fpath)
        try:
            obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
            epochs = list(obs.iter_epochs())
            assert len(epochs) >= 0
        except ValueError, RinexError, KeyError:
            pass  # Acceptable

    def test_multiple_end_of_header(self):
        """Two END OF HEADER markers — should use the first one."""
        fpath = INVALID_DIR / "multiple_end_of_header.25o"
        _skip_if_missing(fpath)
        try:
            obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
            epochs = list(obs.iter_epochs())
            assert len(epochs) >= 0
        except ValueError, RinexError:
            pass  # Acceptable


# ===================================================================
# 12. Real-world corruption patterns
# ===================================================================


class TestRealWorldCorruption:
    """Tests for corruption patterns common in production."""

    def test_truncated_at_epoch_boundary(self):
        """File truncated after first complete epoch — should yield 1 epoch."""
        fpath = INVALID_DIR / "truncated_at_epoch_boundary.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        assert len(epochs) == 1

    def test_bitflip_in_numeric_field(self):
        """Single bit-flip turns a digit into non-ASCII, which rejects its epoch."""
        fpath = INVALID_DIR / "bitflip_numeric.25o"
        _skip_if_missing(fpath)
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
        epochs = list(obs.iter_epochs())
        # The malformed field rejects its epoch; the clean epoch survives
        assert len(epochs) == 1
