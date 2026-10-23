"""Test RINEX v3 reader functionality."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.rinex.v3_04 import Rnxv3Header, Rnxv3Obs

# Test data paths
TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_FILE = (
    TEST_DATA_DIR
    / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
)


# Contains SBAS GEO S48 (EGNOS PRN 148) besides S23 and S36.
RINEX_FILE_WITH_S48 = (
    TEST_DATA_DIR
    / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250012230_15M_05S_AA.rnx"
)


@pytest.fixture
def rinex_file():
    """Fixture providing path to test RINEX file."""
    if not RINEX_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_FILE}")
    return RINEX_FILE


class TestRnxv3Header:
    """Tests for RINEX v3 header parsing."""

    def test_header_from_file(self, rinex_file):
        """Test header can be parsed from file."""
        header = Rnxv3Header.from_file(rinex_file)

        assert header is not None
        assert header.version >= 3.0
        assert header.version < 4.0
        assert header.fpath == rinex_file

    def test_header_required_fields(self, rinex_file):
        """Test header contains required fields."""
        header = Rnxv3Header.from_file(rinex_file)

        # Required fields
        assert header.marker_name
        assert header.receiver_type
        assert header.antenna_type
        assert header.observer
        assert header.agency

    def test_header_position_data(self, rinex_file):
        """Test header position information."""
        header = Rnxv3Header.from_file(rinex_file)

        assert len(header.approx_position) == 3
        assert len(header.antenna_position) == 3

        # Check positions have units
        for pos in header.approx_position:
            assert hasattr(pos, "magnitude")
            assert hasattr(pos, "units")

    def test_header_observation_codes(self, rinex_file):
        """Test observation codes are parsed."""
        header = Rnxv3Header.from_file(rinex_file)

        assert header.obs_codes_per_system
        assert isinstance(header.obs_codes_per_system, dict)

        # Should have at least one GNSS system
        assert len(header.obs_codes_per_system) > 0


class TestRnxv3Obs:
    """Tests for RINEX v3 observation reader."""

    def test_obs_initialization(self, rinex_file):
        """Test Rnxv3Obs can be initialized."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        assert obs is not None
        assert obs.fpath == rinex_file
        assert obs.header is not None

    def test_obs_header_access(self, rinex_file):
        """Test header is accessible from obs object."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        assert obs.header.version >= 3.0
        assert obs.header.marker_name

    def test_epoch_iteration(self, rinex_file):
        """Test epoch iteration works."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        epochs = list(obs.iter_epochs())

        assert len(epochs) > 0

        # Check first epoch structure
        first_epoch = epochs[0]
        assert hasattr(first_epoch, "info")
        assert hasattr(first_epoch, "data")
        assert len(first_epoch.data) > 0

    def test_epoch_batches(self, rinex_file):
        """Test epoch batch extraction."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        batches = obs.get_epoch_record_batches()

        assert len(batches) > 0
        assert all(isinstance(b, tuple) and len(b) == 2 for b in batches)
        assert all(b[0] < b[1] for b in batches)  # Start < end

    def test_sampling_interval_inference(self, rinex_file):
        """Test sampling interval can be inferred."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        interval = obs.infer_sampling_interval()

        if interval is not None:
            assert interval.magnitude > 0
            assert hasattr(interval, "units")

    def test_to_ds_basic(self, rinex_file):
        """Test conversion to xarray Dataset."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        ds = obs.to_ds(keep_data_vars=["SNR"])

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars

    def test_to_ds_coordinates(self, rinex_file):
        """Test Dataset has required coordinates."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        ds = obs.to_ds(keep_data_vars=["SNR"])

        # Required coordinates
        required_coords = ["epoch", "sid", "sv", "system", "band", "code"]
        for coord in required_coords:
            assert coord in ds.coords, f"Missing coordinate: {coord}"

    def test_to_ds_frequency_info(self, rinex_file):
        """Test Dataset has frequency information."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        ds = obs.to_ds(keep_data_vars=["SNR"])

        # Frequency coordinates
        assert "freq_center" in ds.coords
        assert "freq_min" in ds.coords
        assert "freq_max" in ds.coords

    def test_to_ds_metadata(self, rinex_file):
        """Test Dataset has global attributes."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        ds = obs.to_ds(keep_data_vars=["SNR"])

        assert "Created" in ds.attrs
        assert "Software" in ds.attrs
        assert "Institution" in ds.attrs

    def test_file_hash_generation(self, rinex_file):
        """Test file hash is generated."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        file_hash = obs.file_hash

        assert file_hash
        assert len(file_hash) == 16  # Short hash
        assert all(c in "0123456789abcdef" for c in file_hash)

    def test_multiple_data_vars(self, rinex_file):
        """Test keeping multiple data variables."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")

        ds = obs.to_ds(keep_data_vars=["SNR", "Pseudorange", "Phase"])

        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert "Phase" in ds.data_vars


class TestSignalMapping:
    """Tests for signal ID mapping."""

    def test_signal_ids_format(self, rinex_file):
        """Test signal IDs have correct format."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])

        # Check signal ID format: "SV|BAND|CODE"
        for sid in ds.sid.values:
            parts = str(sid).split("|")
            assert len(parts) == 3, f"Invalid signal ID format: {sid}"

            sv, band, code = parts
            assert len(sv) == 3  # e.g., "G01"
            assert sv[0] in "GRECJSI"  # Valid GNSS systems
            assert sv[1:3].isdigit()

    def test_system_coordinate(self, rinex_file):
        """Test system coordinate matches signal IDs."""
        obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")
        ds = obs.to_ds(keep_data_vars=["SNR"])

        for i, sid in enumerate(ds.sid.values):
            sv_system = str(sid).split("|")[0][0]
            dataset_system = str(ds.system.values[i])

            # Skip NaN values from padded sids
            if dataset_system == "nan":
                continue

            assert dataset_system == sv_system


def test_sbas_satellites_beyond_s36_are_read():
    """Regression: SBAS sats are Snn with nn = PRN - 100 over the full
    two-digit range (RINEX 3.04 section 8.4). The reader used to keep its own
    S01-S36 list and silently dropped S48's observations at read time."""
    if not RINEX_FILE_WITH_S48.exists():
        pytest.skip(f"Test file not found: {RINEX_FILE_WITH_S48}")
    lines = RINEX_FILE_WITH_S48.read_text(encoding="ascii").splitlines()
    n_s48_records = sum(line.startswith("S48") for line in lines)
    assert n_s48_records > 0

    ds = Rnxv3Obs(fpath=RINEX_FILE_WITH_S48).to_ds(
        keep_data_vars=["SNR"], pad_global_sid=False
    )
    assert int(np.isfinite(ds.SNR.sel(sid="S48|L1|C")).sum()) == n_s48_records


def _v3_obs_field(value: float, lli: int | None, ssi: int | None) -> str:
    """One F14.3 + LLI + SSI observation field."""
    return f"{value:14.3f}{'' if lli is None else lli:1}{'' if ssi is None else ssi:1}"


def test_lli_and_ssi_come_from_phase_then_code(rinex_file, tmp_path):
    """Regression: phase, code, Doppler and SNR of one signal share a sid, and
    the reader used to keep whichever flag came last in the header order
    (S1C after L1C). RINEX 3.04 Table A3 notes 1-3: LLI belongs to the phase
    only; SSI to the phase, or to the code when the signal has no phase."""
    lines = rinex_file.read_text(encoding="ascii").splitlines()
    header = lines[
        : next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    ]
    # G obs types start: X1 C1C L1C D1C S1C C1W S1W
    record = "G01" + "".join(
        [
            _v3_obs_field(1.0, None, None),  # X1
            _v3_obs_field(2.1e7, 1, 6),  # C1C: flags a code must not carry
            _v3_obs_field(1.1e8, 1, 7),  # L1C: slip, SSI 7
            _v3_obs_field(-500.0, 1, 3),  # D1C
            _v3_obs_field(45.0, 0, 9),  # S1C: written last in header order
            _v3_obs_field(2.1e7, None, 5),  # C1W: signal with no phase
            _v3_obs_field(40.0, 1, 8),  # S1W
        ]
    )
    body = []
    for second in (0, 5):
        body += [f"> 2025 01 01 00 00 {second:2d}.0000000  0  1", record]
    path = tmp_path / rinex_file.name
    path.write_text("\n".join([*header, *body]) + "\n", encoding="ascii")

    ds = Rnxv3Obs(fpath=path).to_ds(
        keep_data_vars=["SNR", "Phase", "LLI", "SSI"], pad_global_sid=False
    )
    l1c = ds.sel(sid="G01|L1|C").isel(epoch=0)
    l1w = ds.sel(sid="G01|L1|W").isel(epoch=0)
    assert int(l1c.LLI) == 1
    assert int(l1c.SSI) == 7
    assert int(l1w.LLI) == -1
    assert int(l1w.SSI) == 5


class TestErrorHandling:
    """Tests for error handling."""

    def test_nonexistent_file(self):
        """Test error on nonexistent file."""
        with pytest.raises(ValueError):
            Rnxv3Header.from_file(Path("/nonexistent/file.25o"))

    def test_invalid_file_type(self, tmp_path):
        """Test error on invalid file type."""
        invalid_file = tmp_path / "test.txt"
        invalid_file.write_text("Not a RINEX file")

        with pytest.raises(ValueError):
            Rnxv3Header.from_file(invalid_file)


@pytest.mark.parametrize("data_var", ["SNR", "Pseudorange", "Phase", "Doppler"])
def test_individual_data_vars(rinex_file, data_var):
    """Test each data variable can be read individually."""
    obs = Rnxv3Obs(fpath=rinex_file, completeness_mode="off")
    ds = obs.to_ds(keep_data_vars=[data_var])

    assert data_var in ds.data_vars
    assert ds[data_var].dims == ("epoch", "sid")
