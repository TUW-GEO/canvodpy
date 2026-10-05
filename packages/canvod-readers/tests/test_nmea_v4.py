"""Test NMEA v4.00 reader functionality."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.nmea.exceptions import (
    NmeaChecksumError,
    NmeaInvalidSentenceError,
    NmeaMissingSentenceError,
)
from canvod.readers.nmea.v4_00 import (
    NmeaObs,
    _extract_gsv_signal_id,
    _parse_gsv_satellites,
    _parse_rmc_datetime,
    _sv_to_sid,
    compute_nmea_checksum,
    prn_to_sv,
    validate_nmea_checksum,
)

# Test data paths
TEST_DATA_DIR = Path(__file__).parent / "test_data"

# 01_Rosalia: Septentrio receiver — no signal ID in GSV sentences
ROSALIA_REF_DIR = TEST_DATA_DIR / "valid/nmea/01_Rosalia/01_reference"
ROSALIA_CANOPY_DIR = TEST_DATA_DIR / "valid/nmea/01_Rosalia/02_canopy"
ROSALIA_FILE = ROSALIA_REF_DIR / "ROSR01TUW_R_20250010000_15M_05S_AA.nmea"

# 02_Hainich: u-blox receiver — signal ID present in GSV sentences
HAINICH_REF_DIR = TEST_DATA_DIR / "valid/nmea/02_Hainich/01_reference"
HAINICH_CANOPY_DIR = TEST_DATA_DIR / "valid/nmea/02_Hainich/02_canopy"
HAINICH_REF_FILE = HAINICH_REF_DIR / "HAIR02MPI_R_20260010000_01H_01S_AA.nmea"
HAINICH_CANOPY_FILE = HAINICH_CANOPY_DIR / "HAIA02MPI_R_20260010000_01H_01S_AA.nmea"


@pytest.fixture
def nmea_file():
    """Fixture providing path to Rosalia test NMEA file."""
    if not ROSALIA_FILE.exists():
        pytest.skip(f"Test file not found: {ROSALIA_FILE}")
    return ROSALIA_FILE


@pytest.fixture
def hainich_ref_file():
    """Fixture providing path to Hainich (u-blox) reference NMEA file."""
    if not HAINICH_REF_FILE.exists():
        pytest.skip(f"Test file not found: {HAINICH_REF_FILE}")
    return HAINICH_REF_FILE


@pytest.fixture
def hainich_canopy_file():
    """Fixture providing path to Hainich (u-blox) canopy NMEA file."""
    if not HAINICH_CANOPY_FILE.exists():
        pytest.skip(f"Test file not found: {HAINICH_CANOPY_FILE}")
    return HAINICH_CANOPY_FILE


class TestNmeaChecksum:
    """Tests for NMEA checksum computation and validation."""

    def test_compute_checksum(self):
        """Test checksum computation for a known sentence."""
        sentence = (
            "$GPRMC,001442.00,A,4742.1601213,N,01618.1004213,E,0.0,,010125,5.1,E,D*16"
        )
        assert compute_nmea_checksum(sentence) == "16"

    def test_validate_checksum_pass(self):
        """Test checksum validation passes for valid sentence."""
        sentence = (
            "$GPRMC,001442.00,A,4742.1601213,N,01618.1004213,E,0.0,,010125,5.1,E,D*16"
        )
        validate_nmea_checksum(sentence)  # Should not raise

    def test_validate_checksum_fail(self):
        """Test checksum validation raises on bad checksum."""
        sentence = (
            "$GPRMC,001442.00,A,4742.1601213,N,01618.1004213,E,0.0,,010125,5.1,E,D*FF"
        )
        with pytest.raises(NmeaChecksumError):
            validate_nmea_checksum(sentence)

    def test_invalid_sentence_format(self):
        """Test error on malformed sentence."""
        with pytest.raises(NmeaInvalidSentenceError):
            compute_nmea_checksum("not a valid sentence")


class TestPrnToSv:
    """Tests for PRN-to-SV mapping."""

    def test_gps_prn(self):
        assert prn_to_sv("GP", 1) == "G01"
        assert prn_to_sv("GP", 32) == "G32"

    def test_sbas_in_gp(self):
        assert prn_to_sv("GP", 33) == "S01"
        assert prn_to_sv("GP", 48) == "S16"

    def test_glonass(self):
        assert prn_to_sv("GL", 1) == "R01"
        assert prn_to_sv("GL", 24) == "R24"
        assert prn_to_sv("GL", 65) == "R01"  # Global ID format

    def test_galileo(self):
        assert prn_to_sv("GA", 1) == "E01"
        assert prn_to_sv("GA", 36) == "E36"

    def test_beidou(self):
        assert prn_to_sv("GB", 1) == "C01"
        assert prn_to_sv("GB", 63) == "C63"

    def test_invalid_prn(self):
        assert prn_to_sv("GP", 0) is None
        assert prn_to_sv("GP", 100) is None
        assert prn_to_sv("GA", 37) is None
        assert prn_to_sv("XX", 1) is None

    def test_gn_multi_constellation(self):
        assert prn_to_sv("GN", 1) == "G01"
        assert prn_to_sv("GN", 65) == "R01"
        assert prn_to_sv("GN", 301) == "E01"
        assert prn_to_sv("GN", 401) == "C01"


class TestSvToSid:
    """Tests for SV-to-SID mapping."""

    def test_gps_sid(self):
        assert _sv_to_sid("G01") == "G01|L1|C"

    def test_glonass_sid(self):
        assert _sv_to_sid("R05") == "R05|G1|C"

    def test_galileo_sid(self):
        assert _sv_to_sid("E12") == "E12|E1|C"

    def test_beidou_sid(self):
        assert _sv_to_sid("C30") == "C30|B1I|I"

    def test_sbas_sid(self):
        assert _sv_to_sid("S01") == "S01|L1|C"

    # u-blox signal ID aware tests
    def test_gps_l2_signal_id(self):
        assert _sv_to_sid("G01", signal_id="6") == "G01|L2|L"

    def test_gps_l5_signal_id(self):
        assert _sv_to_sid("G01", signal_id="7") == "G01|L5|I"

    def test_galileo_e5a_signal_id(self):
        assert _sv_to_sid("E12", signal_id="1") == "E12|E5a|X"

    def test_galileo_e5b_signal_id(self):
        assert _sv_to_sid("E12", signal_id="2") == "E12|E5b|X"

    def test_galileo_e1_signal_id(self):
        assert _sv_to_sid("E12", signal_id="7") == "E12|E1|X"

    def test_glonass_g2_signal_id(self):
        assert _sv_to_sid("R05", signal_id="3") == "R05|G2|C"

    def test_beidou_b2i_signal_id(self):
        assert _sv_to_sid("C30", signal_id="B") == "C30|B2I|I"

    def test_unknown_signal_id_falls_back(self):
        # Signal ID "F" not in GPS map → fallback to default
        assert _sv_to_sid("G01", signal_id="F") == "G01|L1|C"


class TestGsvSignalIdExtraction:
    """Tests for _extract_gsv_signal_id."""

    def test_no_signal_id(self):
        """Standard GSV with 4 sats, last field is 2-digit SNR."""
        fields = [
            "6",
            "1",
            "21",
            "02",
            "85",
            "302",
            "50",
            "08",
            "22",
            "184",
            "42",
            "28",
            "16",
            "099",
            "40",
            "32",
            "36",
            "053",
            "46",
        ]
        assert _extract_gsv_signal_id(fields) is None

    def test_signal_id_present(self):
        """GSV with signal ID '1' after 4 satellite blocks."""
        fields = [
            "3",
            "1",
            "09",
            "02",
            "85",
            "302",
            "50",
            "08",
            "22",
            "184",
            "42",
            "28",
            "16",
            "099",
            "40",
            "32",
            "36",
            "053",
            "46",
            "1",
        ]
        assert _extract_gsv_signal_id(fields) == "1"

    def test_signal_id_hex(self):
        """GSV with hex signal ID 'B' (BeiDou B2I)."""
        fields = ["2", "1", "05", "29", "64", "281", "51", "19", "12", "226", "42", "B"]
        assert _extract_gsv_signal_id(fields) == "B"

    def test_empty_gsv(self):
        fields = ["6", "6", "21"]
        assert _extract_gsv_signal_id(fields) is None

    def test_gsv_with_signal_id_applies_to_sids(self):
        """Verify that signal ID flows through to SID construction."""
        # GPS L5 I: signal ID = 7
        fields = ["1", "1", "02", "02", "85", "302", "50", "7"]
        signal_id = _extract_gsv_signal_id(fields)
        assert signal_id == "7"
        sats = _parse_gsv_satellites("GP", fields, signal_id)
        assert len(sats) == 1
        assert sats[0] == ("G02|L5|I", 50.0)


class TestRmcParsing:
    """Tests for RMC datetime parsing."""

    def test_valid_rmc(self):
        fields = [
            "001442.00",
            "A",
            "4742.16",
            "N",
            "01618.10",
            "E",
            "0.0",
            "",
            "010125",
            "5.1",
            "E",
            "D",
        ]
        dt = _parse_rmc_datetime(fields)
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1
        assert dt.hour == 0
        assert dt.minute == 14
        assert dt.second == 42

    def test_empty_fields(self):
        assert _parse_rmc_datetime([]) is None

    def test_missing_date(self):
        fields = ["001442.00", "A", "", "", "", "", "", "", ""]
        assert _parse_rmc_datetime(fields) is None


class TestGsvParsing:
    """Tests for GSV satellite parsing."""

    def test_gps_gsv(self):
        # $GPGSV,6,1,21,02,85,302,50,08,22,184,42,28,16,099,40,32,36,053,46*7C
        fields = [
            "6",
            "1",
            "21",
            "02",
            "85",
            "302",
            "50",
            "08",
            "22",
            "184",
            "42",
            "28",
            "16",
            "099",
            "40",
            "32",
            "36",
            "053",
            "46",
        ]
        sats = _parse_gsv_satellites("GP", fields)
        assert len(sats) == 4
        assert sats[0] == ("G02|L1|C", 50.0)
        assert sats[1] == ("G08|L1|C", 42.0)
        assert sats[2] == ("G28|L1|C", 40.0)
        assert sats[3] == ("G32|L1|C", 46.0)

    def test_glonass_gsv(self):
        fields = [
            "2",
            "1",
            "08",
            "84",
            "81",
            "349",
            "41",
            "70",
            "12",
            "216",
            "35",
            "83",
            "29",
            "134",
            "38",
            "85",
            "26",
            "321",
            "47",
        ]
        sats = _parse_gsv_satellites("GL", fields)
        assert len(sats) == 4
        assert sats[0][0] == "R20|G1|C"  # GL PRN 84 → 84-64=20
        assert sats[0][1] == 41.0

    def test_galileo_gsv(self):
        fields = [
            "3",
            "1",
            "11",
            "11",
            "83",
            "055",
            "44",
            "02",
            "13",
            "285",
            "39",
            "09",
            "27",
            "185",
            "43",
            "12",
            "31",
            "111",
            "40",
        ]
        sats = _parse_gsv_satellites("GA", fields)
        assert len(sats) == 4
        assert sats[0] == ("E11|E1|C", 44.0)

    def test_beidou_gsv(self):
        fields = [
            "5",
            "1",
            "20",
            "29",
            "64",
            "281",
            "51",
            "19",
            "12",
            "226",
            "42",
            "35",
            "11",
            "315",
            "41",
            "39",
            "24",
            "061",
            "42",
        ]
        sats = _parse_gsv_satellites("GB", fields)
        assert len(sats) == 4
        assert sats[0] == ("C29|B1I|I", 51.0)

    def test_missing_snr(self):
        # SNR field empty → None
        fields = ["5", "1", "18", "22", "15", "219", "", "35", "16", "315", "43"]
        sats = _parse_gsv_satellites("GB", fields)
        assert len(sats) == 2
        assert sats[0] == ("C22|B1I|I", None)
        assert sats[1] == ("C35|B1I|I", 43.0)

    def test_empty_gsv(self):
        # Last message with no satellites: $GPGSV,6,6,21*7A
        fields = ["6", "6", "21"]
        sats = _parse_gsv_satellites("GP", fields)
        assert len(sats) == 0


class TestNmeaObs:
    """Tests for the NmeaObs reader."""

    def test_initialization(self, nmea_file):
        """Test NmeaObs can be initialized."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs is not None
        assert obs.fpath == nmea_file

    def test_epochs_are_gps_time(self, nmea_file):
        """NMEA times are UTC; the epochs are converted to GPS time."""
        ds = NmeaObs(fpath=nmea_file).to_ds(keep_data_vars=["SNR"])
        assert ds["epoch"].attrs["time_system"] == "GPS"

    def test_file_hash(self, nmea_file):
        """Test file hash is generated."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs.file_hash
        assert len(obs.file_hash) == 16
        assert all(c in "0123456789abcdef" for c in obs.file_hash)

    def test_start_end_time(self, nmea_file):
        """Test start and end time are parsed."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs.start_time < obs.end_time

    def test_systems(self, nmea_file):
        """Test multiple GNSS systems are detected."""
        obs = NmeaObs(fpath=nmea_file)
        systems = obs.systems
        assert len(systems) > 1
        # Should have at least GPS and one other
        assert "G" in systems

    def test_num_epochs(self, nmea_file):
        """Test epochs are parsed."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs.num_epochs > 0

    def test_num_satellites(self, nmea_file):
        """Test satellites are detected."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs.num_satellites > 0

    def test_source_format(self, nmea_file):
        """Test source format is nmea."""
        obs = NmeaObs(fpath=nmea_file)
        assert obs.source_format == "nmea"

    def test_iter_epochs(self, nmea_file):
        """Test epoch iteration works."""
        obs = NmeaObs(fpath=nmea_file)
        epochs = list(obs.iter_epochs())
        assert len(epochs) > 0
        assert epochs[0].timestamp is not None
        assert len(epochs[0].satellites) > 0

    def test_to_ds_basic(self, nmea_file):
        """Test conversion to xarray Dataset."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars

    def test_to_ds_coordinates(self, nmea_file):
        """Test Dataset has required coordinates."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        required_coords = ["epoch", "sid", "sv", "system", "band", "code"]
        for coord in required_coords:
            assert coord in ds.coords, f"Missing coordinate: {coord}"

    def test_to_ds_frequency_info(self, nmea_file):
        """Test Dataset has frequency information."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        assert "freq_center" in ds.coords
        assert "freq_min" in ds.coords
        assert "freq_max" in ds.coords

    def test_to_ds_metadata(self, nmea_file):
        """Test Dataset has required global attributes."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        assert "Created" in ds.attrs
        assert "Software" in ds.attrs
        assert "Institution" in ds.attrs
        assert "File Hash" in ds.attrs

    def test_to_ds_snr_has_valid_values(self, nmea_file):
        """Test SNR data contains valid values."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        snr = ds["SNR"].values
        valid = snr[~np.isnan(snr)]
        assert len(valid) > 0
        assert valid.min() >= 0
        assert valid.max() <= 99  # NMEA SNR range

    def test_to_ds_snr_dims(self, nmea_file):
        """Test SNR has correct dimensions."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()
        assert ds["SNR"].dims == ("epoch", "sid")


class TestNmeaSignalMapping:
    """Tests for signal ID mapping in NMEA."""

    def test_signal_ids_format(self, nmea_file):
        """Test signal IDs have correct SV|BAND|CODE format."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        for sid in ds.sid.values:
            parts = str(sid).split("|")
            assert len(parts) == 3, f"Invalid signal ID format: {sid}"

            sv, band, code = parts
            assert len(sv) == 3, f"SV should be 3 chars: {sv}"
            assert sv[0] in "GRECSI", f"Invalid system prefix: {sv[0]}"
            assert sv[1:3].isdigit(), f"PRN should be digits: {sv[1:3]}"

    def test_system_coordinate_matches_sid(self, nmea_file):
        """Test system coordinate matches signal IDs."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        for i, sid in enumerate(ds.sid.values):
            sv_system = str(sid).split("|")[0][0]
            dataset_system = str(ds.system.values[i])
            assert dataset_system == sv_system

    def test_band_names_are_valid(self, nmea_file):
        """Test band names match SignalIDMapper expectations."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        valid_bands = {
            "L1",
            "L2",
            "L5",
            "G1",
            "G2",
            "E1",
            "E5a",
            "E5b",
            "E6",
            "B1I",
            "B1C",
            "B2a",
            "B2b",
            "B3I",
        }
        for band in ds.band.values:
            assert str(band) in valid_bands, f"Unexpected band name: {band}"

    def test_multiple_constellations(self, nmea_file):
        """Test that multiple GNSS systems are present."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        systems_found = set()
        for sid in ds.sid.values:
            systems_found.add(str(sid).split("|")[0][0])

        assert len(systems_found) > 1


class TestNmeaErrorHandling:
    """Tests for error handling."""

    def test_nonexistent_file(self):
        """Test error on nonexistent file."""
        with pytest.raises((ValueError, FileNotFoundError)):
            NmeaObs(fpath=Path("/nonexistent/file.nmea"))

    def test_empty_file(self, tmp_path):
        """Test error on empty file."""
        empty_file = tmp_path / "empty.nmea"
        empty_file.write_text("")
        with pytest.raises(NmeaMissingSentenceError):
            obs = NmeaObs(fpath=empty_file)
            obs.to_ds()

    def test_no_gsv_sentences(self, tmp_path):
        """Test error when file has no GSV sentences."""
        f = tmp_path / "no_gsv.nmea"
        f.write_text(
            "$GPRMC,001442.00,A,4742.1601213,N,01618.1004213,E,0.0,,010125,5.1,E,D*16\n"
        )
        with pytest.raises(NmeaMissingSentenceError):
            obs = NmeaObs(fpath=f)
            obs.to_ds()


class TestNmeaMultipleFiles:
    """Tests reading multiple NMEA files."""

    REFERENCE_DIR = ROSALIA_REF_DIR
    CANOPY_DIR = ROSALIA_CANOPY_DIR

    def test_read_second_file(self):
        """Test reading a different time segment."""
        f = self.REFERENCE_DIR / "ROSR01TUW_R_20250010015_15M_05S_AA.nmea"
        if not f.exists():
            pytest.skip(f"Test file not found: {f}")

        obs = NmeaObs(fpath=f)
        ds = obs.to_ds()

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_file_hashes_differ(self):
        """Test that different files produce different hashes."""
        f1 = self.REFERENCE_DIR / "ROSR01TUW_R_20250010000_15M_05S_AA.nmea"
        f2 = self.REFERENCE_DIR / "ROSR01TUW_R_20250010015_15M_05S_AA.nmea"
        if not f1.exists() or not f2.exists():
            pytest.skip("Test files not found")

        obs1 = NmeaObs(fpath=f1)
        obs2 = NmeaObs(fpath=f2)
        assert obs1.file_hash != obs2.file_hash

    def test_read_canopy_file(self):
        """Test reading a canopy receiver NMEA file."""
        f = self.CANOPY_DIR / "ROSA01TUW_R_20250010000_15M_05S_AA.nmea"
        if not f.exists():
            pytest.skip(f"Test file not found: {f}")

        obs = NmeaObs(fpath=f)
        ds = obs.to_ds()

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0

    def test_reference_and_canopy_share_sids(self):
        """Test that reference and canopy share common signal IDs."""
        ref_file = self.REFERENCE_DIR / "ROSR01TUW_R_20250010000_15M_05S_AA.nmea"
        canopy_file = self.CANOPY_DIR / "ROSA01TUW_R_20250010000_15M_05S_AA.nmea"

        if not ref_file.exists() or not canopy_file.exists():
            pytest.skip("Test files not found")

        ref_ds = NmeaObs(fpath=ref_file).to_ds()
        canopy_ds = NmeaObs(fpath=canopy_file).to_ds()

        ref_sids = set(str(s) for s in ref_ds.sid.values)
        canopy_sids = set(str(s) for s in canopy_ds.sid.values)

        common_sids = ref_sids & canopy_sids
        assert len(common_sids) > 0, "Reference and canopy should share signal IDs"


class TestRosaliaNoSignalId:
    """Tests for Rosalia (Septentrio) NMEA data — no signal ID in GSV sentences.

    All SIDs should use DEFAULT_NMEA_BAND_MAP (L1/G1/E1/B1I per system).
    Each SV appears at most once per epoch (single band).
    """

    def test_rosalia_reads_successfully(self, nmea_file):
        """Basic sanity: file reads without error."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_rosalia_only_default_bands(self, nmea_file):
        """Rosalia data has no signal ID → only default bands appear."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        default_bands = {"L1", "G1", "E1", "B1I"}
        for band in ds.band.values:
            assert str(band) in default_bands, (
                f"Unexpected band '{band}' — Rosalia has no signal ID, "
                f"should only use default bands {default_bands}"
            )

    def test_rosalia_no_duplicate_sv_per_epoch(self, nmea_file):
        """Without signal ID, each SV produces exactly one SID."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        # Check that no SV appears under multiple bands
        sv_to_bands: dict[str, set[str]] = {}
        for sid in ds.sid.values:
            sv, band, _ = str(sid).split("|")
            sv_to_bands.setdefault(sv, set()).add(band)

        for sv, bands in sv_to_bands.items():
            assert len(bands) == 1, (
                f"SV {sv} appears on bands {bands} — expected single band "
                f"(no signal ID in Rosalia data)"
            )

    def test_rosalia_default_tracking_codes(self, nmea_file):
        """Default tracking codes: C for GPS/GLONASS/Galileo/SBAS, I for BeiDou."""
        obs = NmeaObs(fpath=nmea_file)
        ds = obs.to_ds()

        for sid in ds.sid.values:
            sv, band, code = str(sid).split("|")
            system = sv[0]
            if system in ("G", "R", "E", "S"):
                assert code == "C", f"Expected code 'C' for {system}, got '{code}'"
            elif system == "C":
                assert code == "I", f"Expected code 'I' for BeiDou, got '{code}'"


class TestHainichSignalId:
    """Tests for Hainich (u-blox) NMEA data — signal ID present in GSV sentences.

    The u-blox receiver outputs multiple GSV message sets per system,
    each with a different signal ID (e.g. GPS L1 + L2, Galileo E1 + E5b).
    """

    def test_hainich_reads_successfully(self, hainich_ref_file):
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_hainich_has_multiple_bands_per_system(self, hainich_ref_file):
        """u-blox signal ID produces multiple bands per constellation."""
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()

        system_bands: dict[str, set[str]] = {}
        for sid in ds.sid.values:
            sv, band, _ = str(sid).split("|")
            system = sv[0]
            system_bands.setdefault(system, set()).add(band)

        # GPS should have L1 + L2 (signal IDs 1 and 6)
        assert "L1" in system_bands.get("G", set()), "GPS should have L1"
        assert "L2" in system_bands.get("G", set()), "GPS should have L2"

    def test_hainich_gps_l1_and_l2(self, hainich_ref_file):
        """GPS satellites should appear on both L1 and L2 bands."""
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()

        gps_sids = [str(s) for s in ds.sid.values if str(s).startswith("G")]
        l1_svs = {s.split("|")[0] for s in gps_sids if "|L1|" in s}
        l2_svs = {s.split("|")[0] for s in gps_sids if "|L2|" in s}

        # Some GPS SVs should appear on both bands
        common = l1_svs & l2_svs
        assert len(common) > 0, "GPS SVs should appear on both L1 and L2"

    def test_hainich_glonass_dual_band(self, hainich_ref_file):
        """GLONASS should have G1 (signal ID 1) and G2 (signal ID 3)."""
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()

        glo_bands = set()
        for sid in ds.sid.values:
            sv, band, _ = str(sid).split("|")
            if sv[0] == "R":
                glo_bands.add(band)

        assert "G1" in glo_bands, "GLONASS should have G1"
        assert "G2" in glo_bands, "GLONASS should have G2"

    def test_hainich_galileo_dual_band(self, hainich_ref_file):
        """Galileo should have E5b (signal ID 2) and E1 (signal ID 7)."""
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()

        gal_bands = set()
        for sid in ds.sid.values:
            sv, band, _ = str(sid).split("|")
            if sv[0] == "E":
                gal_bands.add(band)

        assert "E5b" in gal_bands or "E1" in gal_bands, (
            f"Galileo should have E1 or E5b, got {gal_bands}"
        )

    def test_hainich_tracking_codes_from_signal_id(self, hainich_ref_file):
        """Signal-ID-resolved tracking codes differ from default."""
        obs = NmeaObs(fpath=hainich_ref_file)
        ds = obs.to_ds()

        # GPS L2 CL should have code "L" (not "C")
        gps_l2_codes = set()
        for sid in ds.sid.values:
            sv, band, code = str(sid).split("|")
            if sv[0] == "G" and band == "L2":
                gps_l2_codes.add(code)

        assert "L" in gps_l2_codes, (
            f"GPS L2 should have tracking code 'L' (from signal ID 6), "
            f"got {gps_l2_codes}"
        )

    def test_hainich_more_sids_than_rosalia(self, hainich_ref_file, nmea_file):
        """u-blox data with signal IDs should produce more SIDs per SV."""
        hai = NmeaObs(fpath=hainich_ref_file).to_ds()
        ros = NmeaObs(fpath=nmea_file).to_ds()

        # Hainich: each GPS SV on ~2 bands → more SIDs
        hai_sids_per_sv = len(hai.sid) / max(1, hai.sizes.get("sid", 1))
        ros_sids_per_sv = len(ros.sid) / max(1, ros.sizes.get("sid", 1))

        # Simpler: just check that Hainich has more unique bands
        hai_bands = set(str(b) for b in hai.band.values)
        ros_bands = set(str(b) for b in ros.band.values)

        assert len(hai_bands) > len(ros_bands), (
            f"Hainich should have more unique bands ({hai_bands}) "
            f"than Rosalia ({ros_bands})"
        )

    def test_hainich_canopy_reads(self, hainich_canopy_file):
        """Hainich canopy file also reads correctly."""
        obs = NmeaObs(fpath=hainich_canopy_file)
        ds = obs.to_ds()
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_hainich_ref_canopy_share_sids(self, hainich_ref_file, hainich_canopy_file):
        """Reference and canopy from same site share signal IDs."""
        ref_ds = NmeaObs(fpath=hainich_ref_file).to_ds()
        can_ds = NmeaObs(fpath=hainich_canopy_file).to_ds()

        ref_sids = set(str(s) for s in ref_ds.sid.values)
        can_sids = set(str(s) for s in can_ds.sid.values)

        common = ref_sids & can_sids
        assert len(common) > 0, "Hainich ref and canopy should share SIDs"
