"""Test RINEX v2.11 reader functionality."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.gnss_specs.constellations import V2_UNRESOLVED_CODES
from canvod.readers.preprocessing import pad_to_global_sid
from canvod.readers.rinex.v2_11 import (
    Rnxv2Header,
    Rnxv2Obs,
    _parse_wavelength_fact_line,
    _v2_tracking_code,
)

# Test data paths
TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_V2_FILE = (
    TEST_DATA_DIR
    / "valid/rinex_v2_11/02_Moflux/01_reference/25001/MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
)


@pytest.fixture
def rinex_v2_file():
    """Fixture providing path to test RINEX v2.11 file."""
    if not RINEX_V2_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_V2_FILE}")
    return RINEX_V2_FILE


class TestRnxv2Header:
    """Tests for RINEX v2.11 header parsing."""

    def test_header_from_file(self, rinex_v2_file):
        """Test header can be parsed from file."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header is not None
        assert header.version == pytest.approx(2.11)
        assert header.fpath == rinex_v2_file

    def test_header_required_fields(self, rinex_v2_file):
        """Test header contains required fields."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.marker_name
        assert header.receiver_type
        assert header.antenna_type
        assert header.observer
        assert header.agency

    def test_header_position_data(self, rinex_v2_file):
        """Test header position information."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert len(header.approx_position) == 3
        assert len(header.antenna_delta) == 3

        for pos in header.approx_position:
            assert hasattr(pos, "magnitude")
            assert hasattr(pos, "units")

    def test_header_observation_types(self, rinex_v2_file):
        """Test v2 observation types are parsed."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.obs_types
        assert isinstance(header.obs_types, list)
        assert len(header.obs_types) > 0
        # v2 uses 2-char codes like L1, L2, C1, P1, P2, S1, S2
        for ot in header.obs_types:
            assert len(ot) == 2

    def test_header_obs_codes_per_system(self, rinex_v2_file):
        """Test obs codes are mapped to v3 format per system."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.obs_codes_per_system
        assert isinstance(header.obs_codes_per_system, dict)
        assert len(header.obs_codes_per_system) > 0

        # Mapped codes should be 3-char v3 format
        for sys_codes in header.obs_codes_per_system.values():
            for code in sys_codes:
                assert len(code) == 3

    def test_header_version_is_v2(self, rinex_v2_file):
        """Test that parsed version is 2.x."""
        header = Rnxv2Header.from_file(rinex_v2_file)
        assert header.version >= 2.0
        assert header.version < 3.0

    def test_header_time_of_first_obs(self, rinex_v2_file):
        """Test time of first observation is parsed."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.t0
        assert len(header.t0) > 0
        assert header.time_system in ("GPS", "GLO", "GAL", "UTC")

    def test_header_mixed_system(self, rinex_v2_file):
        """Test mixed system file is recognized."""
        header = Rnxv2Header.from_file(rinex_v2_file)
        # The test file has "M (MIXED)" in the header
        assert header.systems == "M"


class TestRnxv2Obs:
    """Tests for RINEX v2.11 observation reader."""

    def test_obs_initialization(self, rinex_v2_file):
        """Test Rnxv2Obs can be initialized."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        assert obs is not None
        assert obs.fpath == rinex_v2_file
        assert obs.header is not None

    def test_source_format(self, rinex_v2_file):
        """The reader names itself as registered, not as RINEX 3."""
        assert Rnxv2Obs(fpath=rinex_v2_file).source_format == "rinex2"

    def test_obs_header_access(self, rinex_v2_file):
        """Test header is accessible from obs object."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        assert obs.header.version == pytest.approx(2.11)
        assert obs.header.marker_name

    def test_epoch_iteration(self, rinex_v2_file):
        """Test epoch iteration works."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        epochs = list(obs.iter_epochs())

        assert len(epochs) > 0

        first_epoch = epochs[0]
        assert first_epoch.year == 2025
        assert first_epoch.month == 1
        assert first_epoch.day == 1
        assert len(first_epoch.satellites) > 0

    def test_epoch_has_satellites(self, rinex_v2_file):
        """Test epochs contain satellite observations."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        first_epoch = next(obs.iter_epochs())

        assert first_epoch.num_satellites > 0
        assert len(first_epoch.satellite_list) > 0
        assert len(first_epoch.satellites) > 0

    def test_sampling_interval_inference(self, rinex_v2_file):
        """Test sampling interval can be inferred."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        interval = obs.infer_sampling_interval()

        if interval is not None:
            assert interval.magnitude > 0
            assert hasattr(interval, "units")

    def test_to_ds_basic(self, rinex_v2_file):
        """Test conversion to xarray Dataset."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars

    def test_to_ds_coordinates(self, rinex_v2_file):
        """Test Dataset has required coordinates."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        required_coords = ["epoch", "sid", "sv", "system", "band", "code"]
        for coord in required_coords:
            assert coord in ds.coords, f"Missing coordinate: {coord}"

    def test_to_ds_frequency_info(self, rinex_v2_file):
        """Test Dataset has frequency information."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert "freq_center" in ds.coords
        assert "freq_min" in ds.coords
        assert "freq_max" in ds.coords

    def test_to_ds_metadata(self, rinex_v2_file):
        """Test Dataset has required global attributes."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert "Created" in ds.attrs
        assert "Software" in ds.attrs
        assert "Institution" in ds.attrs
        assert "File Hash" in ds.attrs

    def test_file_hash_generation(self, rinex_v2_file):
        """Test file hash is generated."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        file_hash = obs.file_hash

        assert file_hash
        assert len(file_hash) == 16
        assert all(c in "0123456789abcdef" for c in file_hash)

    def test_multiple_data_vars(self, rinex_v2_file):
        """Test keeping multiple data variables."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"],
            pad_global_sid=False,
        )

        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert "Phase" in ds.data_vars

    def test_create_rinex_netcdf_with_signal_id(self, rinex_v2_file):
        """Test the raw dataset creation method."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.create_rinex_netcdf_with_signal_id()

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        # Raw dataset should have all data vars
        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert "Phase" in ds.data_vars
        assert "Doppler" in ds.data_vars
        assert "LLI" in ds.data_vars
        assert "SSI" in ds.data_vars


class TestRnxv2SignalMapping:
    """Tests for signal ID mapping in RINEX v2."""

    def test_signal_ids_format(self, rinex_v2_file):
        """Test signal IDs have correct SV|BAND|CODE format."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        for sid in ds.sid.values:
            parts = str(sid).split("|")
            assert len(parts) == 3, f"Invalid signal ID format: {sid}"

            sv, band, code = parts
            assert len(sv) == 3, f"SV should be 3 chars: {sv}"
            assert sv[0] in "GRECJSI", f"Invalid system prefix: {sv[0]}"
            assert sv[1:3].isdigit(), f"PRN should be digits: {sv[1:3]}"

    def test_system_coordinate_matches_sid(self, rinex_v2_file):
        """Test system coordinate matches signal IDs."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        for i, sid in enumerate(ds.sid.values):
            sv_system = str(sid).split("|")[0][0]
            dataset_system = str(ds.system.values[i])

            if dataset_system == "nan":
                continue

            assert dataset_system == sv_system

    def test_mixed_constellations(self, rinex_v2_file):
        """Test that multiple GNSS systems are present in mixed file."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        systems_found = set()
        for sid in ds.sid.values:
            systems_found.add(str(sid).split("|")[0][0])

        # The test file is mixed (M), should have multiple systems
        assert len(systems_found) > 1, (
            f"Expected multiple systems, got: {systems_found}"
        )


# Spec rows: rinex211.txt Table A1 ("C: Pseudorange GPS: C/A, L2C; Glonass:
# C/A; Galileo: All", "P: Pseudorange GPS and Glonass: P code") and section
# 10.1 (v2 codes cannot express the underlying code or channel).
_V2_TRACKING_CODE_CASES = [
    ("G", "C1", "L1", "C"),  # C/A: defined by the v2 code
    ("G", "P1", "L1", "p"),  # P family: P/W/Y (D on L2) under AS not recorded
    ("G", "C2", "L2", "l"),  # C2: C/A or L2C (C/S/L/X) not recorded
    ("G", "P2", "L2", "p"),
    ("G", "L1", "L1", "u"),  # phase: no code information at all
    ("G", "S2", "L2", "u"),  # SNR belongs to "the respective phase"
    ("G", "D1", "L1", "u"),
    ("G", "C5", "L5", "u"),  # L5 I/Q/X not recorded
    ("R", "C1", "G1", "C"),  # GLONASS C/A
    ("R", "P2", "G2", "P"),  # GLONASS P code is unencrypted: exact
    ("R", "L1", "G1", "u"),
    ("R", "C1", "G1_FDMA", "C"),  # same codes without FDMA aggregation
    ("E", "C1", "E1", "u"),  # Galileo "C" means "All"
    ("E", "L5", "E5a", "u"),
    ("S", "C1", "L1", "C"),  # SBAS L1 carries only C/A ...
    ("S", "L1", "L1", "C"),  # ... so even phase/SNR resolve exactly
    ("S", "C5", "L5", "u"),
]


class TestRnxv2TrackingCodes:
    """Tracking codes follow RINEX 2.11 instead of guessed RINEX 3 attributes."""

    @pytest.mark.parametrize(
        ("system", "obs_code", "band", "expected"), _V2_TRACKING_CODE_CASES
    )
    def test_tracking_code_follows_rinex211(self, system, obs_code, band, expected):
        assert _v2_tracking_code(system, obs_code, band) == expected

    def test_markers_can_never_be_rinex_attributes(self):
        # RINEX observation codes are uppercase-only; a marker must not
        # collide with a real attribute (e.g. "X" = L2C M+L).
        assert len(set(V2_UNRESOLVED_CODES)) == len(V2_UNRESOLVED_CODES)
        assert all(code.islower() and len(code) == 1 for code in V2_UNRESOLVED_CODES)

    def test_mixed_file_sids(self, rinex_v2_file):
        """Obs types L1 L2 C1 P1 P2 S1 S2 yield exactly these band|code pairs."""
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        by_system: dict[str, set[str]] = {}
        for sid in ds.sid.values:
            sv, band_code = str(sid).split("|", 1)
            by_system.setdefault(sv[0], set()).add(band_code)
        assert by_system["G"] == {"L1|C", "L1|p", "L1|u", "L2|p", "L2|u"}
        assert by_system["R"] == {"G1|C", "G1|P", "G1|u", "G2|P", "G2|u"}
        assert by_system["E"] == {"E1|u"}
        assert by_system["S"] == {"L1|C"}

    def test_observables_land_on_their_sids(self, rinex_v2_file):
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        gps = ds.sel(sid=[s for s in ds.sid.values if str(s).startswith("G")])
        has = {
            var: {
                str(s).split("|", 1)[1]
                for s in gps.sid.values[gps[var].notnull().any("epoch").values]
            }
            for var in ("Pseudorange", "Phase", "SNR")
        }
        assert has["Pseudorange"] == {"L1|C", "L1|p", "L2|p"}
        assert has["Phase"] == {"L1|u", "L2|u"}
        assert has["SNR"] == {"L1|u", "L2|u"}

    def test_global_padding_keeps_every_observation(self, rinex_v2_file):
        """Regression: padding onto the global sid space used to drop GLONASS,
        SBAS and Galileo phase/SNR (41 % of them in this file), because their
        v2 sids were not in any constellation's BAND_CODES."""
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        padded = pad_to_global_sid(ds)
        assert set(ds.sid.values) <= set(padded.sid.values)
        for var in ("SNR", "Pseudorange", "Phase"):
            assert int(np.isfinite(padded[var]).sum()) == int(
                np.isfinite(ds[var]).sum()
            )

    def test_markers_documented_in_attrs(self, rinex_v2_file):
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )
        assert ds.attrs["RINEX Version"] == "2.11"
        assert "'u' = carrier band only" in ds.attrs["Tracking Code Markers"]

    def test_header_codes_are_system_specific(self, rinex_v2_file):
        codes = Rnxv2Header.from_file(rinex_v2_file).obs_codes_per_system
        assert codes["G"] == ["L1u", "L2u", "C1C", "C1p", "C2p", "S1u", "S2u"]
        assert codes["R"] == ["L1u", "L2u", "C1C", "C1P", "C2P", "S1u", "S2u"]


def _v2_obs_field(value: float, lli: int | None, ssi: int | None = None) -> str:
    """One F14.3 + LLI + SSI observation field."""
    return f"{value:14.3f}{'' if lli is None else lli:1}{'' if ssi is None else ssi:1}"


def _v2_header(rinex_v2_file: Path, wavelength_fact: str | None = None) -> list[str]:
    """Header of the test file (obs types L1 L2 C1 P1 P2 S1 S2), optionally
    with the default WAVELENGTH FACT L1/2 record replaced."""
    lines = rinex_v2_file.read_text(encoding="ascii", errors="replace").splitlines()
    header = lines[
        : next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    ]
    if wavelength_fact is not None:
        header = [
            f"{wavelength_fact:<60}WAVELENGTH FACT L1/2"
            if line[60:].strip() == "WAVELENGTH FACT L1/2"
            else line
            for line in header
        ]
    return header


def _v2_sat_records(lli_l1: int | None, lli_l2: int | None) -> list[str]:
    """Observation records of one satellite: L1 L2 C1 P1 P2 / S1 S2."""
    fields = [
        _v2_obs_field(1.0e8, lli_l1),
        _v2_obs_field(8.0e7, lli_l2),
        _v2_obs_field(2.1e7, None),
        _v2_obs_field(2.1e7, None),
        _v2_obs_field(2.1e7, None),
        _v2_obs_field(45.0, None),
        _v2_obs_field(40.0, None),
    ]
    return ["".join(fields[:5]), "".join(fields[5:])]


def _read_lli(tmp_path: Path, header: list[str], body: list[str]) -> xr.Dataset:
    path = tmp_path / "lli.25o"
    path.write_text("\n".join([*header, *body]) + "\n", encoding="ascii")
    return Rnxv2Obs(fpath=path).to_ds(
        keep_data_vars=["Phase", "Pseudorange", "SNR", "LLI", "SSI"],
        pad_global_sid=False,
    )


def test_lli_is_translated_to_rinex3_meaning(rinex_v2_file, tmp_path):
    """RINEX 2.11 Table A2 -> RINEX 3.04 Table A3: bit 0 (lost lock) carries
    over, bit 2 (antispoofing, obsolete in RINEX 3) is dropped, and flags on
    signal strength never reach the shared phase sid."""
    lines = _v2_header(rinex_v2_file)
    fields = [
        _v2_obs_field(1.0e8, 5),  # L1: slip + AS
        _v2_obs_field(8.0e7, 4),  # L2: AS
        _v2_obs_field(2.1e7, 4),  # C1
        _v2_obs_field(2.1e7, 4),  # P1
        _v2_obs_field(2.1e7, 4),  # P2
        _v2_obs_field(45.0, 5),  # S1: slip bit a signal strength must not carry
        _v2_obs_field(40.0, 5),  # S2
    ]
    body = [
        " 25  1  1  0  0  0.0000000  0  1G01",
        "".join(fields[:5]),
        "".join(fields[5:]),
    ]
    ds = _read_lli(tmp_path, lines, body)
    assert int(ds.LLI.sel(sid="G01|L1|u").item()) == 1
    assert int(ds.LLI.sel(sid="G01|L2|u").item()) == 0
    # LLI is associated with the phase only (RINEX 3.04 Table A3 note 1).
    assert int(ds.LLI.sel(sid="G01|L1|C").item()) == -1


def test_ssi_comes_from_phase_then_code(rinex_v2_file, tmp_path):
    """The phase's SSI outranks S1's; the code's stays with the code sid."""
    fields = [
        _v2_obs_field(1.0e8, None, 7),  # L1
        _v2_obs_field(8.0e7, None),  # L2
        _v2_obs_field(2.1e7, None, 6),  # C1
        _v2_obs_field(2.1e7, None),  # P1
        _v2_obs_field(2.1e7, None),  # P2
        _v2_obs_field(45.0, None, 9),  # S1
        _v2_obs_field(40.0, None),  # S2
    ]
    body = [
        " 25  1  1  0  0  0.0000000  0  1G01",
        "".join(fields[:5]),
        "".join(fields[5:]),
    ]
    ds = _read_lli(tmp_path, _v2_header(rinex_v2_file), body)
    assert int(ds.SSI.sel(sid="G01|L1|u").item()) == 7
    assert int(ds.SSI.sel(sid="G01|L1|C").item()) == 6


def test_half_cycle_bit_from_wavelength_factor(rinex_v2_file, tmp_path):
    """Header factor 2 (half-cycle ambiguities, Table A1) sets RINEX 3 bit 1
    even without an LLI digit; v2 bit 1 switches the factor for one epoch."""
    header = _v2_header(rinex_v2_file, wavelength_fact="     1     2")
    body = [
        " 25  1  1  0  0  0.0000000  0  2G01G02",
        *_v2_sat_records(None, None),  # G01: L1 factor 1, L2 factor 2
        *_v2_sat_records(2, 3),  # G02: both switched, L2 slip
    ]
    ds = _read_lli(tmp_path, header, body)
    assert int(ds.LLI.sel(sid="G01|L1|u").item()) == -1
    assert int(ds.LLI.sel(sid="G01|L2|u").item()) == 2
    assert int(ds.LLI.sel(sid="G02|L1|u").item()) == 2
    assert int(ds.LLI.sel(sid="G02|L2|u").item()) == 1


def test_wavelength_factor_changed_by_event_flag_4(rinex_v2_file, tmp_path):
    """A satellite-specific WAVELENGTH FACT L1/2 record inside an epoch-flag-4
    block applies from the following epochs on (rinex211.txt example file)."""
    body = [
        " 25  1  1  0  0  0.0000000  0  1G09",
        *_v2_sat_records(None, None),
        " 25  1  1  0  0 10.0000000  4  1",
        f"{'     1     2     1   G 9':<60}WAVELENGTH FACT L1/2",
        " 25  1  1  0  0 15.0000000  0  1G09",
        *_v2_sat_records(None, None),
    ]
    ds = _read_lli(tmp_path, _v2_header(rinex_v2_file), body)
    lli_l2 = ds.LLI.sel(sid="G09|L2|u").values.tolist()
    assert lli_l2 == [-1, 2]


def test_parse_wavelength_fact_line_normalizes_satellites():
    wl1, wl2, sats = _parse_wavelength_fact_line("     1     2     3   G 9   G12    14")
    assert (wl1, wl2) == (1, 2)
    assert sats == ["G09", "G12", "G14"]


class TestRnxv2ErrorHandling:
    """Tests for error handling."""

    def test_nonexistent_file(self):
        """Test error on nonexistent file."""
        with pytest.raises((ValueError, FileNotFoundError)):
            Rnxv2Obs(fpath=Path("/nonexistent/file.25o"))

    def test_header_nonexistent_file(self):
        """Test error on nonexistent file for header."""
        with pytest.raises((ValueError, FileNotFoundError)):
            Rnxv2Header.from_file(Path("/nonexistent/file.25o"))


class TestRnxv2MultipleFiles:
    """Tests reading multiple RINEX v2.11 files."""

    CANOPY_DIR = TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/02_canopy/25001"
    REFERENCE_DIR = TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/01_reference/25001"

    def test_read_canopy_file(self):
        """Test reading a canopy receiver file."""
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"
        if not canopy_file.exists():
            pytest.skip(f"Test file not found: {canopy_file}")

        obs = Rnxv2Obs(fpath=canopy_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_read_reference_file(self):
        """Test reading a reference receiver file."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        if not ref_file.exists():
            pytest.skip(f"Test file not found: {ref_file}")

        obs = Rnxv2Obs(fpath=ref_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_reference_and_canopy_share_sids(self):
        """Test that reference and canopy files share common signal IDs."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"

        if not ref_file.exists() or not canopy_file.exists():
            pytest.skip("Test files not found")

        ref_ds = Rnxv2Obs(fpath=ref_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )
        canopy_ds = Rnxv2Obs(fpath=canopy_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )

        ref_sids = set(str(s) for s in ref_ds.sid.values)
        canopy_sids = set(str(s) for s in canopy_ds.sid.values)

        common_sids = ref_sids & canopy_sids
        assert len(common_sids) > 0, "Reference and canopy should share signal IDs"

    def test_file_hashes_differ(self):
        """Test that different files produce different hashes."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"

        if not ref_file.exists() or not canopy_file.exists():
            pytest.skip("Test files not found")

        ref_obs = Rnxv2Obs(fpath=ref_file)
        canopy_obs = Rnxv2Obs(fpath=canopy_file)

        assert ref_obs.file_hash != canopy_obs.file_hash


@pytest.mark.parametrize("data_var", ["SNR", "Pseudorange", "Phase", "Doppler"])
def test_individual_data_vars(rinex_v2_file, data_var):
    """Test each data variable can be read individually."""
    obs = Rnxv2Obs(fpath=rinex_v2_file)
    ds = obs.to_ds(keep_data_vars=[data_var], pad_global_sid=False)

    assert data_var in ds.data_vars
    assert ds[data_var].dims == ("epoch", "sid")


def test_snr_and_lli_metadata(rinex_v2_file):
    """Shared LLI metadata carries the RINEX 3.04 meaning; the SNR metadata
    states that RINEX 2.11 declares no unit (dB assumed)."""
    ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
        keep_data_vars=["SNR", "LLI"], pad_global_sid=False
    )
    assert ds.SNR.attrs["units"] == "dB"
    assert "RINEX 2.11 declares no unit" in ds.SNR.attrs["description"]
    assert ds.LLI.attrs["valid_range"] == [0, 7]
    assert "RINEX 3.04 Table A3" in ds.LLI.attrs["description"]
    assert int(ds.LLI.max()) <= 3  # v2 bit 2 (antispoofing) never survives
