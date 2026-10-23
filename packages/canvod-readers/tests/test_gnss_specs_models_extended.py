"""Extended tests for canvod.readers.gnss_specs.models — covers VodDataValidator,
RINEX304ComplianceValidator, Rnxv3ObsEpochRecordLineModel, Quantity wrapper,
and deeper Observation/Satellite/Epoch exercising.
"""

from datetime import datetime

import pint
import pytest
import xarray as xr

from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.models import (
    INDICATOR_MAX,
    INDICATOR_MIN,
    RINEX_VERSION_MAX,
    RINEX_VERSION_MIN,
    Epoch,
    Observation,
    RINEX304ComplianceValidator,
    Rnxv3ObsEpochRecord,
    Rnxv3ObsEpochRecordLineModel,
    RnxVersion3Model,
    Satellite,
    VodDataValidator,
)

# ---------------------------------------------------------------------------
# Observation — extended
# ---------------------------------------------------------------------------


class TestObservationExtended:
    """Extended validation of Observation model."""

    def test_valid_galileo_observation(self):
        obs = Observation(
            obs_type="S",
            value=42.3,
            lli=None,
            ssi=7,
        )
        assert obs.ssi == 7

    def test_valid_glonass_observation(self):
        obs = Observation(
            obs_type="C",
            value=23456789.0,
            lli=0,
            ssi=None,
        )
        assert obs.value == 23456789.0

    def test_valid_beidou_observation(self):
        obs = Observation(
            obs_type="L",
            value=123456789.0,
            lli=1,
            ssi=5,
        )
        assert obs.obs_type == "L"

    def test_valid_irnss_observation(self):
        obs = Observation(
            obs_type="S",
            value=35.0,
            lli=None,
            ssi=None,
        )
        assert obs.value == 35.0

    def test_lli_out_of_range(self):
        with pytest.raises(ValueError, match="Indicator"):
            Observation(
                obs_type="L",
                value=1.0,
                lli=10,
                ssi=None,
            )

    def test_ssi_out_of_range(self):
        with pytest.raises(ValueError, match="Indicator"):
            Observation(
                obs_type="L",
                value=1.0,
                lli=None,
                ssi=-1,
            )

    def test_lli_boundary_values(self):
        obs_min = Observation(
            obs_type="L",
            value=1.0,
            lli=INDICATOR_MIN,
            ssi=None,
        )
        obs_max = Observation(
            obs_type="L",
            value=1.0,
            lli=INDICATOR_MAX,
            ssi=None,
        )
        assert obs_min.lli == INDICATOR_MIN
        assert obs_max.lli == INDICATOR_MAX

    def test_frequency_validation_valid(self):
        freq = 1575.42 * UREG.MHz
        obs = Observation(
            obs_type="L",
            value=1.0,
            lli=None,
            ssi=None,
            frequency=freq,
        )
        assert obs.frequency is not None

    def test_frequency_validation_none(self):
        obs = Observation(
            obs_type="L",
            value=1.0,
            lli=None,
            ssi=None,
            frequency=None,
        )
        assert obs.frequency is None

    def test_none_value_and_obs_type(self):
        obs = Observation(
            obs_type=None,
            value=None,
            lli=None,
            ssi=None,
        )
        assert obs.value is None
        assert obs.obs_type is None


# ---------------------------------------------------------------------------
# Satellite — extended
# ---------------------------------------------------------------------------


class TestSatelliteExtended:
    """Extended Satellite tests."""

    def test_add_and_retrieve_observations(self):
        sat = Satellite(sv="G01")
        obs = Observation(
            obs_type="L",
            value=100.0,
            lli=None,
            ssi=None,
        )
        sat.add_observation(obs)
        assert len(sat.observations) == 1
        assert sat.observations[0] is obs

    def test_all_constellation_svs(self):
        """All GNSS constellation prefixes should be valid."""
        for prefix in ["G", "R", "E", "C", "J", "S", "I"]:
            sat = Satellite(sv=f"{prefix}01")
            assert sat.sv == f"{prefix}01"


# ---------------------------------------------------------------------------
# Epoch — extended
# ---------------------------------------------------------------------------


class TestEpochExtended:
    """Extended Epoch tests."""

    def test_get_satellite(self):
        ep = Epoch(timestamp=datetime(2024, 1, 1), num_satellites=1)
        sat = Satellite(sv="G01")
        ep.add_satellite(sat)

        assert ep.get_satellite("G01") is sat
        assert ep.get_satellite("G02") is None

    def test_get_satellites_by_system(self):
        ep = Epoch(timestamp=datetime(2024, 1, 1), num_satellites=3)
        ep.add_satellite(Satellite(sv="G01"))
        ep.add_satellite(Satellite(sv="G02"))
        ep.add_satellite(Satellite(sv="E01"))

        gps_sats = ep.get_satellites_by_system("G")
        assert len(gps_sats) == 2

        gal_sats = ep.get_satellites_by_system("E")
        assert len(gal_sats) == 1

        glo_sats = ep.get_satellites_by_system("R")
        assert len(glo_sats) == 0


# ---------------------------------------------------------------------------
# RnxVersion3Model
# ---------------------------------------------------------------------------


class TestRnxVersion3Model:
    """Tests for RnxVersion3Model."""

    def test_valid_version_3_04(self):
        m = RnxVersion3Model(version=3.04)
        assert m.version == 3.04

    def test_valid_version_3_0(self):
        m = RnxVersion3Model(version=3.0)
        assert m.version == 3.0

    def test_invalid_version_2(self):
        with pytest.raises(ValueError, match=r"3\.0x"):
            RnxVersion3Model(version=2.11)

    def test_invalid_version_4(self):
        with pytest.raises(ValueError, match=r"3\.0x"):
            RnxVersion3Model(version=4.0)


# ---------------------------------------------------------------------------
# Rnxv3ObsEpochRecordLineModel
# ---------------------------------------------------------------------------


class TestRnxv3ObsEpochRecordLineModel:
    """Tests for RINEX v3 epoch record line parsing."""

    def test_valid_epoch_line(self):
        epoch_str = "> 2024 10 29 00 00  0.0000000  0 12"
        m = Rnxv3ObsEpochRecordLineModel(epoch=epoch_str)
        assert m.year == 2024
        assert m.month == 10
        assert m.day == 29
        assert m.hour == 0
        assert m.minute == 0
        assert m.seconds == pytest.approx(0.0)
        assert m.epoch_flag == 0
        assert m.num_satellites == 12

    def test_epoch_with_clock_offset(self):
        epoch_str = "> 2024 10 29 12 30 30.0000000  0  8  0.123456789"
        m = Rnxv3ObsEpochRecordLineModel(epoch=epoch_str)
        assert m.receiver_clock_offset == pytest.approx(0.123456789)

    def test_invalid_epoch_format(self):
        with pytest.raises(ValueError, match="Invalid epoch format"):
            Rnxv3ObsEpochRecordLineModel(epoch="INVALID EPOCH LINE")


# ---------------------------------------------------------------------------
# Rnxv3ObsEpochRecord
# ---------------------------------------------------------------------------


class TestRnxv3ObsEpochRecord:
    """Tests for complete epoch record validation."""

    def test_valid_record(self):
        info = Rnxv3ObsEpochRecordLineModel(epoch="> 2024 10 29 00 00  0.0000000  0  2")
        sats = [Satellite(sv="G01"), Satellite(sv="G02")]
        record = Rnxv3ObsEpochRecord(info=info, data=sats)
        assert len(record.data) == 2

    def test_satellite_count_mismatch(self):
        from canvod.readers.gnss_specs.exceptions import IncompleteEpochError

        info = Rnxv3ObsEpochRecordLineModel(epoch="> 2024 10 29 00 00  0.0000000  0  3")
        sats = [Satellite(sv="G01"), Satellite(sv="G02")]
        with pytest.raises(IncompleteEpochError):
            Rnxv3ObsEpochRecord(info=info, data=sats)

    def test_get_satellites_by_system(self):
        info = Rnxv3ObsEpochRecordLineModel(epoch="> 2024 10 29 00 00  0.0000000  0  3")
        sats = [Satellite(sv="G01"), Satellite(sv="E01"), Satellite(sv="G02")]
        record = Rnxv3ObsEpochRecord(info=info, data=sats)

        gps = record.get_satellites_by_system("G")
        assert len(gps) == 2


# ---------------------------------------------------------------------------
# VodDataValidator
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::FutureWarning")
class TestVodDataValidator:
    """Tests for VodDataValidator."""

    def _make_valid_vod_ds(self) -> xr.Dataset:
        import numpy as np

        return xr.Dataset(
            {
                "Elevation": (["Epoch", "SV"], [[30.0, 45.0]]),
                "Azimuth": (["Epoch", "SV"], [[120.0, 200.0]]),
                "VOD": (
                    ["Epoch", "SV", "Frequency"],
                    [[[0.5], [0.6]]],
                ),
            },
            coords={
                "Epoch": [np.datetime64("2024-01-01")],
                "SV": ["G01", "G02"],
                "Frequency": [1575.42],
            },
        )

    def test_valid_vod_data(self):
        ds = self._make_valid_vod_ds()
        m = VodDataValidator(vod_data=ds)
        assert m.vod_data is ds

    def test_none_vod_data(self):
        with pytest.raises(ValueError, match="has not been calculated"):
            VodDataValidator(vod_data=None)

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="must be an instance"):
            VodDataValidator(vod_data="not a dataset")

    def test_missing_elevation(self):
        ds = self._make_valid_vod_ds().drop_vars("Elevation")
        with pytest.raises(ValueError, match="Elevation"):
            VodDataValidator(vod_data=ds)

    def test_missing_azimuth(self):
        ds = self._make_valid_vod_ds().drop_vars("Azimuth")
        with pytest.raises(ValueError, match="Azimuth"):
            VodDataValidator(vod_data=ds)

    def test_missing_vod_variable(self):
        ds = self._make_valid_vod_ds().drop_vars("VOD")
        with pytest.raises(ValueError, match="VOD"):
            VodDataValidator(vod_data=ds)


# ---------------------------------------------------------------------------
# RINEX304ComplianceValidator
# ---------------------------------------------------------------------------


class TestRINEX304ComplianceValidator:
    """Tests for RINEX304ComplianceValidator."""

    def _make_ds(self) -> xr.Dataset:
        import numpy as np

        return xr.Dataset(
            {"SNR": (["epoch", "sid"], [[45.0, 43.0]])},
            coords={
                "epoch": [np.datetime64("2024-01-01")],
                "sid": ["G01|L1C", "G02|L1C"],
            },
        )

    def test_validate_all_no_issues(self):
        ds = self._make_ds()
        header = {
            "obs_codes_per_system": {"G": ["C1C", "L1C", "S1C"]},
        }
        results = RINEX304ComplianceValidator.validate_all(ds, header)
        assert isinstance(results, dict)
        assert "observation_codes" in results

    def test_validate_all_with_glonass(self):
        ds = self._make_ds()
        header = {
            "obs_codes_per_system": {
                "G": ["C1C"],
                "R": ["C1C"],
            },
            "GLONASS SLOT / FRQ #": {"R01": 1},
            "GLONASS COD/PHS/BIS": {"C1C": 0.0},
        }
        results = RINEX304ComplianceValidator.validate_all(ds, header)
        assert isinstance(results, dict)

    def test_print_validation_report_no_issues(self, capsys):
        results = {
            "observation_codes": [],
            "glonass_fields": [],
            "phase_shifts": [],
            "value_ranges": [],
        }
        RINEX304ComplianceValidator.print_validation_report(results)
        captured = capsys.readouterr()
        assert "no issues found" in captured.out

    def test_print_validation_report_with_issues(self, capsys):
        results = {
            "observation_codes": ["bad code X9Z"],
            "glonass_fields": [],
            "phase_shifts": [],
            "value_ranges": [],
        }
        RINEX304ComplianceValidator.print_validation_report(results)
        captured = capsys.readouterr()
        assert "bad code X9Z" in captured.out


# ---------------------------------------------------------------------------
# Quantity wrapper
# ---------------------------------------------------------------------------


class TestQuantityWrapper:
    """Tests for Pydantic-compatible Quantity wrapper."""

    def test_from_pint_quantity(self):
        q = 1575.42 * UREG.MHz
        assert isinstance(q, pint.Quantity)

    def test_constants(self):
        assert INDICATOR_MIN == 0
        assert INDICATOR_MAX == 9
        assert RINEX_VERSION_MIN == 3
        assert RINEX_VERSION_MAX == 4
