"""Integration tests for SbfReader — ABC compliance, to_ds(), to_ds_and_auxiliary()."""

from __future__ import annotations

import math
from datetime import UTC
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError

from canvod.readers.base import (
    GNSSDataReader,
    validate_dataset,
)
from canvod.readers.sbf.models import SbfHeader
from canvod.readers.sbf.reader import SbfReader, _snr_dbhz_to_ssi

# ---------------------------------------------------------------------------
# Test data location
# ---------------------------------------------------------------------------

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
# Reference station SBF file — DOY 001/2025, 00:00–00:15 UTC, 5-second sampling → 180 epochs
SBF_FILE = (
    _TEST_DATA_DIR
    / "valid/sbf/01_Rosalia/01_reference/25001/ROSR01TUW_R_20250010000_15M_05S_AA.sbf"
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sbf_file() -> Path:
    """Skip the test module if the test_data submodule has not been initialised."""
    if not SBF_FILE.exists():
        pytest.skip(
            f"SBF test file not found (run: git submodule update --init): {SBF_FILE}"
        )
    return SBF_FILE


@pytest.fixture(scope="module")
def reader(sbf_file: Path) -> SbfReader:
    """One SbfReader for the whole module (file-scan results are cached)."""
    return SbfReader(fpath=sbf_file)


@pytest.fixture(scope="module")
def obs_ds(reader: SbfReader) -> xr.Dataset:
    """Full observation dataset (SNR, Pseudorange, Phase, Doppler, SSI — no padding)."""
    return reader.to_ds(pad_global_sid=False, strip_fillval=False)


@pytest.fixture(scope="module")
def combined_result(
    reader: SbfReader,
) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
    """Result of to_ds_and_auxiliary() — single-pass combined scan."""
    return reader.to_ds_and_auxiliary(pad_global_sid=False, strip_fillval=False)


@pytest.fixture(scope="module")
def meta_ds(combined_result: tuple[xr.Dataset, dict[str, xr.Dataset]]) -> xr.Dataset:
    """SBF metadata dataset ``sbf_obs`` (no padding)."""
    return combined_result[1]["sbf_obs"]


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestSnrDbhzToSsi:
    """RINEX 3.04 §5.7 CN0-to-SSI banding, applied where SBF has no native SSI."""

    def test_no_observation_stays_sentinel(self) -> None:
        ssi = _snr_dbhz_to_ssi(np.array([np.nan]))
        assert ssi[0] == -1

    def test_band_boundaries(self) -> None:
        # (snr_dbhz, expected_ssi) at and around each RINEX band edge.
        cases = [
            (0.0, 1),
            (11.9, 1),
            (12.0, 2),
            (17.9, 2),
            (18.0, 3),
            (23.9, 3),
            (24.0, 4),
            (29.9, 4),
            (30.0, 5),
            (35.9, 5),
            (36.0, 6),
            (41.9, 6),
            (42.0, 7),
            (47.9, 7),
            (48.0, 8),
            (53.9, 8),
            (54.0, 9),
            (100.0, 9),  # clamps, doesn't overflow past 9
        ]
        snr = np.array([c[0] for c in cases])
        expected = np.array([c[1] for c in cases])
        ssi = _snr_dbhz_to_ssi(snr)
        np.testing.assert_array_equal(ssi, expected)

    def test_mixed_valid_and_missing(self) -> None:
        ssi = _snr_dbhz_to_ssi(np.array([np.nan, 32.25, np.nan, 44.5]))
        np.testing.assert_array_equal(ssi, [-1, 5, -1, 7])

    def test_dtype_is_int8(self) -> None:
        assert _snr_dbhz_to_ssi(np.array([42.0])).dtype == np.int8


class TestSbfReaderInit:
    """Pydantic field_validator runs at construction time."""

    def test_valid_file_constructs(self, sbf_file: Path) -> None:
        r = SbfReader(fpath=sbf_file)
        assert r.fpath == sbf_file

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Construction with a missing path must raise at runtime (Pydantic validator)."""
        bad = tmp_path / "does_not_exist.25_"
        with pytest.raises((ValidationError, FileNotFoundError)):
            SbfReader(fpath=bad)

    def test_repr_contains_class_and_filename(self, reader: SbfReader) -> None:
        r = repr(reader)
        assert "SbfReader" in r
        assert reader.fpath.name in r

    def test_repr_contains_epoch_count(self, reader: SbfReader) -> None:
        r = repr(reader)
        assert "180" in r


class TestSbfReaderABC:
    """SbfReader satisfies the GNSSDataReader ABC."""

    def test_is_gnss_data_reader(self, reader: SbfReader) -> None:
        assert isinstance(reader, GNSSDataReader)

    def test_file_hash(self, reader: SbfReader) -> None:
        fh = reader.file_hash
        assert isinstance(fh, str)
        assert len(fh) == 16
        assert all(c in "0123456789abcdef" for c in fh)

    def test_file_hash_deterministic(self, sbf_file: Path) -> None:
        """Same file produces the same hash regardless of reader instance."""
        assert (
            SbfReader(fpath=sbf_file).file_hash == SbfReader(fpath=sbf_file).file_hash
        )

    def test_start_end_time(self, reader: SbfReader) -> None:
        st = reader.start_time
        et = reader.end_time
        assert st < et
        assert st.tzinfo is not None  # timezone-aware (GPS time)
        assert st.tzinfo == UTC

    def test_start_time_is_gps_time(self, reader: SbfReader) -> None:
        """ROSR01TUW_R_20250010000_15M_05S_AA.sbf starts at the GPS day boundary.

        Its first MeasEpoch has TOW 259200 s (Wednesday 00:00:00 GPS time).
        Stored in GPS time, the first epoch is 2025-01-01 00:00:00, not
        2024-12-31 23:59:42 (UTC, 18 leap seconds earlier).
        """
        from datetime import datetime

        assert reader.start_time == datetime(2025, 1, 1, tzinfo=UTC)

    def test_systems(self, reader: SbfReader) -> None:
        valid = {"G", "R", "E", "C", "J", "I", "S"}
        systems = reader.systems
        assert isinstance(systems, list)
        assert len(systems) > 0
        assert set(systems).issubset(valid), (
            f"Unexpected systems: {set(systems) - valid}"
        )

    def test_systems_sorted(self, reader: SbfReader) -> None:
        assert reader.systems == sorted(reader.systems)

    def test_num_epochs(self, reader: SbfReader) -> None:
        assert (
            reader.num_epochs == 180
        )  # 15-minute file at 5-second sampling (180 = 15 × 60 / 5)

    def test_num_satellites(self, reader: SbfReader) -> None:
        assert reader.num_satellites > 0

    def test_num_satellites_upper_bound(self, reader: SbfReader) -> None:
        """Physical limit: no real receiver tracks more than ~200 SVs."""
        assert reader.num_satellites < 200


class TestSbfHeader:
    """reader.header parses the ReceiverSetup block correctly."""

    @pytest.fixture(scope="class")
    def header(self, reader: SbfReader) -> SbfHeader:
        return reader.header

    def test_header_is_sbf_header(self, header: SbfHeader) -> None:
        assert isinstance(header, SbfHeader)

    def test_header_string_fields_non_empty(self, header: SbfHeader) -> None:
        # At minimum the receiver must report a firmware version
        assert len(header.rx_version) > 0

    def test_header_string_fields_are_str(self, header: SbfHeader) -> None:
        for field in (
            "marker_name",
            "rx_serial",
            "rx_name",
            "rx_version",
            "ant_type",
            "ant_serial",
            "agency",
            "observer",
        ):
            assert isinstance(getattr(header, field), str), f"{field} must be str"

    def test_header_rx_version_dotted(self, header: SbfHeader) -> None:
        """Firmware version should be a dotted numeric string, e.g. '4.14.4'."""
        parts = header.rx_version.split(".")
        assert len(parts) >= 2, f"Expected dotted version, got: {header.rx_version!r}"
        assert all(p.isdigit() for p in parts), (
            f"Non-numeric part in: {header.rx_version!r}"
        )

    def test_header_latitude_in_radian_range(self, header: SbfHeader) -> None:
        assert -math.pi / 2 <= header.latitude_rad <= math.pi / 2

    def test_header_longitude_in_radian_range(self, header: SbfHeader) -> None:
        assert -math.pi <= header.longitude_rad <= math.pi

    def test_header_height_plausible(self, header: SbfHeader) -> None:
        """Rosalia reference station is ~460 m a.s.l.; allow generous 0–4000 m."""
        h_m = header.height_m.magnitude  # pint.Quantity in meters
        assert 0 < h_m < 4000, f"Implausible station height: {h_m:.1f} m"


class TestToDs:
    """to_ds() produces a valid (epoch, sid) observation dataset."""

    def test_to_ds_validates(self, obs_ds: xr.Dataset) -> None:
        validate_dataset(obs_ds)

    def test_to_ds_dims(self, obs_ds: xr.Dataset) -> None:
        assert "epoch" in obs_ds.dims
        assert "sid" in obs_ds.dims

    def test_to_ds_coords(self, obs_ds: xr.Dataset) -> None:
        required = {
            "epoch",
            "sid",
            "sv",
            "system",
            "band",
            "code",
            "freq_center",
            "freq_min",
            "freq_max",
        }
        missing = required - set(obs_ds.coords)
        assert not missing, f"Missing coords: {missing}"

    def test_to_ds_required_vars(self, obs_ds: xr.Dataset) -> None:
        for var in ("SNR", "Pseudorange", "Phase", "Doppler"):
            assert var in obs_ds.data_vars, f"Missing data var: {var}"
        # SBF has no loss-of-lock indicator — LLI must not be present
        assert "LLI" not in obs_ds.data_vars, "LLI should be absent from SBF datasets"

    def test_to_ds_ssi_present(self, obs_ds: xr.Dataset) -> None:
        assert "SSI" in obs_ds.data_vars, "SSI data var must be present"

    def test_to_ds_ssi_derived_from_snr(self, obs_ds: xr.Dataset) -> None:
        """SBF has no native RINEX SSI field — it must be banded from CN0.

        Regression test: SSI used to stay at its -1 "no data" sentinel for
        every epoch/sid regardless of what the receiver reported, because
        the fill loop only ever populated SNR/Pseudorange/Phase/Doppler/
        Smoothing/HalfCycle, never SSI.
        """
        ssi = obs_ds["SSI"].values
        snr = obs_ds["SNR"].values
        assert set(np.unique(ssi[np.isfinite(ssi)])) != {-1}, (
            "SSI must vary with signal strength, not stay uniformly at -1"
        )

        valid = np.isfinite(snr)
        assert np.all(ssi[valid] >= 1) and np.all(ssi[valid] <= 9), (
            "SSI must be in RINEX's 1-9 range wherever SNR is valid"
        )
        assert np.all(ssi[~valid] == -1), (
            "SSI must stay at the -1 sentinel wherever there is no observation"
        )

    def test_to_ds_global_attrs(self, obs_ds: xr.Dataset) -> None:
        for attr in ("File Hash", "Created", "Software", "Institution"):
            assert attr in obs_ds.attrs, f"Missing global attr: {attr}"

    def test_to_ds_file_hash_attr(self, obs_ds: xr.Dataset) -> None:
        assert "File Hash" in obs_ds.attrs

    def test_to_ds_snr_values(self, obs_ds: xr.Dataset) -> None:
        snr = obs_ds["SNR"].values
        valid = snr[~np.isnan(snr)]
        assert len(valid) > 0, "SNR array is all-NaN"
        assert np.any(valid > 20), "Expected some SNR values > 20 dB-Hz"
        assert np.all(valid >= 0), "SNR cannot be negative dB-Hz"
        assert np.all(valid <= 70), (
            f"SNR unrealistically high: max={valid.max():.1f} dB-Hz"
        )

    def test_to_ds_pseudorange_physical(self, obs_ds: xr.Dataset) -> None:
        """Pseudorange bounds for all GNSS constellations except SBAS.

        Expected slant-range windows by orbit type (all within 19 000–46 000 km):
          - GPS / GLONASS / Galileo (MEO): ~19 000–29 000 km
          - BeiDou MEO:                   ~21 000–28 000 km
          - BeiDou IGSO / GEO:            ~34 000–42 000 km  (C orbit mix)
          - NavIC / IRNSS IGSO:           ~34 000–39 000 km
          - QZSS IGSO / GEO:              ~38 000–42 000 km

        SBAS (system 'S') is excluded: SBF encodes SBAS pseudoranges
        anomalously (~8 000–64 000 km) and they are not used for positioning.
        """
        system_arr = obs_ds["system"].values  # (sid,) coordinate
        non_sbas_mask = system_arr != "S"
        pr = obs_ds["Pseudorange"].values[:, non_sbas_mask]
        valid = pr[~np.isnan(pr)]
        assert len(valid) > 0, "Pseudorange is all-NaN for non-SBAS signals"
        pr_km = valid / 1000.0
        assert np.all(pr_km > 19_000), (
            f"Pseudorange too short: min={pr_km.min():.0f} km"
        )
        assert np.all(pr_km < 46_000), f"Pseudorange too long: max={pr_km.max():.0f} km"

    def test_to_ds_phase_not_all_nan(self, obs_ds: xr.Dataset) -> None:
        ph = obs_ds["Phase"].values
        valid = ph[~np.isnan(ph)]
        assert len(valid) > 0, "Phase array is all-NaN"

    def test_to_ds_sid_format(self, obs_ds: xr.Dataset) -> None:
        for sid in obs_ds.sid.values:
            parts = str(sid).split("|")
            assert len(parts) == 3, f"Bad SID format: {sid}"
            sv, band, code = parts
            assert len(sv) >= 3, f"Bad SV length: {sv}"
            assert sv[0] in "GRECJSI?", f"Unknown system in SV: {sv}"
            assert len(band) >= 2, f"Empty band in {sid}"
            assert len(code) >= 1, f"Empty code in {sid}"

    def test_to_ds_freq_coords_positive(self, obs_ds: xr.Dataset) -> None:
        for coord in ("freq_center", "freq_min", "freq_max"):
            vals = obs_ds[coord].values
            valid = vals[~np.isnan(vals)]
            assert np.all(valid > 0), f"{coord} has non-positive values"

    def test_to_ds_freq_ordering(self, obs_ds: xr.Dataset) -> None:
        """freq_min <= freq_center <= freq_max for every non-NaN entry."""
        fc = obs_ds["freq_center"].values
        fmin = obs_ds["freq_min"].values
        fmax = obs_ds["freq_max"].values
        mask = ~(np.isnan(fc) | np.isnan(fmin) | np.isnan(fmax))
        assert np.all(fmin[mask] <= fc[mask]), "freq_min > freq_center"
        assert np.all(fc[mask] <= fmax[mask]), "freq_center > freq_max"

    def test_to_ds_epoch_count(self, obs_ds: xr.Dataset) -> None:
        assert obs_ds.sizes["epoch"] == 180

    def test_to_ds_epoch_monotonic(self, obs_ds: xr.Dataset) -> None:
        epochs = obs_ds.epoch.values.astype("i8")
        assert np.all(np.diff(epochs) > 0), "Epoch coordinate is not strictly monotone"

    def test_to_ds_keep_vars(self, reader: SbfReader) -> None:
        """keep_data_vars filters data variables to the requested subset."""
        ds = reader.to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False, strip_fillval=False
        )
        assert list(ds.data_vars) == ["SNR"]


class TestSbfObsDataset:
    """The ``sbf_obs`` dataset of to_ds_and_auxiliary() is a valid (epoch, sid) dataset."""

    def test_sbf_obs_dims(self, meta_ds: xr.Dataset, obs_ds: xr.Dataset) -> None:
        assert "epoch" in meta_ds.dims
        assert "sid" in meta_ds.dims
        # Must span at least as many epochs as observations
        assert meta_ds.sizes["epoch"] == obs_ds.sizes["epoch"]

    def test_sbf_obs_sid_coverage(
        self, meta_ds: xr.Dataset, obs_ds: xr.Dataset
    ) -> None:
        obs_sids = set(obs_ds.sid.values)
        meta_sids = set(meta_ds.sid.values)
        missing = obs_sids - meta_sids
        assert not missing, (
            f"Metadata dataset missing sids from observations: {missing}"
        )

    def test_sbf_obs_broadcast_theta_phi(self, meta_ds: xr.Dataset) -> None:
        theta = meta_ds["broadcast_theta"].values
        phi = meta_ds["broadcast_phi"].values
        valid_theta = theta[~np.isnan(theta)]
        valid_phi = phi[~np.isnan(phi)]
        if len(valid_theta) > 0:
            assert np.all(valid_theta >= 0), "broadcast_theta values must be >= 0"
            assert np.all(valid_theta <= np.pi / 2), (
                "broadcast_theta (polar angle) must be <= pi/2"
            )
        if len(valid_phi) > 0:
            assert np.all(valid_phi >= 0), "broadcast_phi values must be >= 0"
            assert np.all(valid_phi < 2 * np.pi), (
                "broadcast_phi (azimuth) must be < 2*pi"
            )
        # Provenance attrs must be present
        assert "source" in meta_ds["broadcast_theta"].attrs, (
            "broadcast_theta must have 'source' provenance attr"
        )
        assert "source" in meta_ds["broadcast_phi"].attrs, (
            "broadcast_phi must have 'source' provenance attr"
        )
        assert meta_ds["broadcast_theta"].attrs["units"] == "rad"
        assert meta_ds["broadcast_phi"].attrs["units"] == "rad"

    def test_sbf_obs_broadcast_theta_not_all_nan(self, meta_ds: xr.Dataset) -> None:
        """At least some epochs must have SatVisibility-derived geometry."""
        assert not np.all(np.isnan(meta_ds["broadcast_theta"].values)), (
            "broadcast_theta is entirely NaN — SatVisibility blocks absent or not matched?"
        )

    def test_sbf_obs_rise_set_values(self, meta_ds: xr.Dataset) -> None:
        """rise_set cells must only contain {-1, 0, 1}: fill, setting, rising."""
        rs = meta_ds["rise_set"].values
        unique_vals = set(np.unique(rs).tolist())
        unexpected = unique_vals - {-1, 0, 1}
        assert not unexpected, f"Unexpected rise_set values: {unexpected}"

    def test_sbf_obs_broadcast_angle_source_values(self, meta_ds: xr.Dataset) -> None:
        """broadcast_angle_source only holds {-1, 1, 2}: fill, almanac, ephemeris."""
        src = meta_ds["broadcast_angle_source"].values
        assert src.dtype == np.int8
        unexpected = set(np.unique(src).tolist()) - {-1, 1, 2}
        assert not unexpected, f"Unexpected broadcast_angle_source: {unexpected}"

    def test_sbf_obs_broadcast_angle_source_has_geometry(
        self, meta_ds: xr.Dataset
    ) -> None:
        """Every almanac/ephemeris cell carries a reported elevation."""
        src = meta_ds["broadcast_angle_source"].values
        theta = meta_ds["broadcast_theta"].values
        assert not np.isnan(theta[src > 0]).any()

    def test_sbf_obs_epoch_coords(self, meta_ds: xr.Dataset) -> None:
        for coord in ("pdop", "hdop", "n_sv"):
            assert coord in meta_ds.coords, f"Missing epoch coord: {coord}"

    def test_epochs_record_gps_time(
        self, meta_ds: xr.Dataset, obs_ds: xr.Dataset
    ) -> None:
        for ds in (obs_ds, meta_ds):
            assert ds["epoch"].attrs["time_system"] == "GPS"

    def test_epochs_lie_on_the_sampling_grid(self, obs_ds: xr.Dataset) -> None:
        """GPS time keeps the receiver's 5 s grid; UTC would shift it by 2 s."""
        seconds = obs_ds["epoch"].values.astype("datetime64[s]").astype(np.int64)
        assert (seconds % 5 == 0).all()

    def test_sbf_obs_pdop_plausible(self, meta_ds: xr.Dataset) -> None:
        pdop = meta_ds["pdop"].values
        valid = pdop[~np.isnan(pdop)]
        if len(valid) > 0:
            assert np.all(valid > 0), "PDOP must be positive"
            assert np.all(valid < 50), (
                f"PDOP unrealistically large: max={valid.max():.2f}"
            )

    def test_sbf_obs_data_vars(self, meta_ds: xr.Dataset) -> None:
        for var in (
            "broadcast_theta",
            "broadcast_phi",
            "broadcast_angle_source",
            "rise_set",
            "mp_correction_m",
        ):
            assert var in meta_ds.data_vars, f"Missing metadata data var: {var}"

    def test_sbf_obs_epoch_coord_dims(self, meta_ds: xr.Dataset) -> None:
        for coord in ("pdop", "hdop", "vdop", "n_sv", "cpu_load"):
            if coord in meta_ds.coords:
                assert meta_ds[coord].dims == ("epoch",), (
                    f"Coord {coord} should be 1-D over epoch"
                )

    def test_sbf_obs_global_attrs(self, meta_ds: xr.Dataset) -> None:
        for attr in ("File Hash", "Created", "Software", "Institution"):
            assert attr in meta_ds.attrs, f"Missing global attr: {attr}"

    def test_sbf_obs_file_hash_attr(self, meta_ds: xr.Dataset) -> None:
        assert "File Hash" in meta_ds.attrs

    def test_sbf_obs_hash_matches_obs(
        self, meta_ds: xr.Dataset, obs_ds: xr.Dataset
    ) -> None:
        """Both datasets must reference the same source file."""
        assert meta_ds.attrs["File Hash"] == obs_ds.attrs["File Hash"]

    def test_sbf_obs_epoch_alignment(
        self, meta_ds: xr.Dataset, obs_ds: xr.Dataset
    ) -> None:
        """Epoch arrays in metadata and observation datasets must be identical."""
        np.testing.assert_array_equal(
            meta_ds.epoch.values,
            obs_ds.epoch.values,
            err_msg="Metadata and observation epoch arrays differ",
        )


# ---------------------------------------------------------------------------
# to_ds_and_auxiliary() — single-pass combined scan
# ---------------------------------------------------------------------------


class TestToDsAndAuxiliary:
    """Tests for SbfReader.to_ds_and_auxiliary()."""

    def test_returns_two_element_tuple(self, combined_result: tuple) -> None:
        assert len(combined_result) == 2

    def test_first_element_is_dataset(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        obs, _ = combined_result
        assert isinstance(obs, xr.Dataset)

    def test_second_element_is_dict(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        _, aux = combined_result
        assert isinstance(aux, dict)

    def test_aux_contains_sbf_obs_key(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        _, aux = combined_result
        assert "sbf_obs" in aux

    def test_obs_passes_validator(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        obs, _ = combined_result
        validate_dataset(obs)

    def test_obs_dims(self, combined_result: tuple[xr.Dataset, dict]) -> None:
        obs, _ = combined_result
        assert set(obs.dims) == {"epoch", "sid"}

    def test_obs_epoch_count_matches_to_ds(
        self,
        combined_result: tuple[xr.Dataset, dict],
        obs_ds: xr.Dataset,
    ) -> None:
        obs, _ = combined_result
        assert obs.sizes["epoch"] == obs_ds.sizes["epoch"]

    def test_obs_sid_count_matches_to_ds(
        self,
        combined_result: tuple[xr.Dataset, dict],
        obs_ds: xr.Dataset,
    ) -> None:
        obs, _ = combined_result
        assert obs.sizes["sid"] == obs_ds.sizes["sid"]

    def test_obs_epoch_values_match_to_ds(
        self,
        combined_result: tuple[xr.Dataset, dict],
        obs_ds: xr.Dataset,
    ) -> None:
        obs, _ = combined_result
        np.testing.assert_array_equal(obs.epoch.values, obs_ds.epoch.values)

    def test_obs_file_hash_attr(self, combined_result: tuple[xr.Dataset, dict]) -> None:
        obs, _ = combined_result
        assert "File Hash" in obs.attrs

    def test_meta_ds_dims(self, combined_result: tuple[xr.Dataset, dict]) -> None:
        _, aux = combined_result
        meta = aux["sbf_obs"]
        assert set(meta.dims) == {"epoch", "sid"}

    def test_meta_ds_has_broadcast_theta_phi(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        _, aux = combined_result
        meta = aux["sbf_obs"]
        assert "broadcast_theta" in meta.data_vars
        assert "broadcast_phi" in meta.data_vars

    def test_keep_data_vars_raw_observables_does_not_raise(
        self, reader: SbfReader
    ) -> None:
        """Regression test: requesting raw observables via keep_data_vars must
        not raise, as long as store_raw_observables=True is also passed —
        validation previously ran before the raw variables were created.
        """
        obs, _ = reader.to_ds_and_auxiliary(
            keep_data_vars=["SNR", "Pseudorange_raw", "Phase_raw", "SNR_raw"],
            store_raw_observables=True,
            pad_global_sid=False,
            strip_fillval=False,
        )
        assert set(obs.data_vars) == {"SNR", "Pseudorange_raw", "Phase_raw", "SNR_raw"}

    def test_keep_data_vars_raw_observables_without_store_raises(
        self, reader: SbfReader
    ) -> None:
        """Requesting a raw observable without store_raw_observables=True must
        still raise — the raw variables genuinely don't exist in that case.
        """
        with pytest.raises(ValueError, match="Missing required data variable"):
            reader.to_ds_and_auxiliary(
                keep_data_vars=["SNR", "Pseudorange_raw"],
                store_raw_observables=False,
                pad_global_sid=False,
                strip_fillval=False,
            )

    def test_meta_sid_matches_obs_sid(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        """meta_ds SID dimension must be identical to obs_ds SID dimension."""
        obs, aux = combined_result
        np.testing.assert_array_equal(
            aux["sbf_obs"].sid.values,
            obs.sid.values,
            err_msg="sbf_obs and obs_ds SID dimensions differ",
        )

    def test_obs_ds_no_leaked_metadata_coords(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        """obs_ds must not contain epoch-level coords leaked from sbf_obs."""
        obs, _ = combined_result
        leaked = {
            "pdop",
            "hdop",
            "vdop",
            "n_sv",
            "pvt_mode",
            "h_accuracy_m",
            "v_accuracy_m",
            "mean_corr_age_s",
            "cpu_load",
            "temperature_c",
            "rx_error",
        } & set(obs.coords)
        assert not leaked, f"Leaked metadata coords in obs_ds: {leaked}"

    def test_meta_epoch_count_matches_obs_epoch_count(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        obs, aux = combined_result
        meta = aux["sbf_obs"]
        assert meta.sizes["epoch"] == obs.sizes["epoch"]

    def test_meta_file_hash_matches_obs(
        self, combined_result: tuple[xr.Dataset, dict]
    ) -> None:
        obs, aux = combined_result
        meta = aux["sbf_obs"]
        assert meta.attrs.get("File Hash") == obs.attrs.get("File Hash")
