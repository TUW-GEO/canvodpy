"""Every stored epoch is GPS time.

The epoch coordinate carries ``time_system: GPS`` (and ``time_system_name``).
RINEX and SBF are written in GPS time; RINEX files declaring another time
system (``TIME OF FIRST OBS``) are refused; NMEA times (UTC) are converted
to GPS time with the leap seconds of the date.
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from canvod.readers.gnss_specs.leap_seconds import (
    LEAP_SECONDS_KNOWN_UNTIL,
    gps_minus_utc,
    utc_to_gps,
)
from canvod.readers.gnss_specs.metadata import epoch_coord_attrs

TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_V3 = (
    TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/"
    "ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)
RINEX_V2 = (
    TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/01_reference/25001/"
    "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
)
# Septentrio NMEA of the 00:00 GPS-time file: first RMC at 23:59:42 UTC.
NMEA = (
    TEST_DATA_DIR / "valid/nmea/01_Rosalia/02_canopy/"
    "ROSA01TUW_R_20250010000_15M_05S_AA.nmea"
)
SBF = (
    TEST_DATA_DIR / "valid/sbf/01_Rosalia/02_canopy/25001/"
    "ROSA01TUW_R_20250010000_15M_05S_AA.sbf"
)


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"Test file not found: {path}")
    return path


def _declaring(src: Path, scale: str, tmp_path: Path) -> Path:
    """Copy of ``src`` whose TIME OF FIRST OBS declares ``scale``."""
    text = src.read_text()
    old = "     GPS         TIME OF FIRST OBS"
    assert old in text
    out = tmp_path / src.name
    out.write_text(text.replace(old, f"     {scale}         TIME OF FIRST OBS", 1))
    return out


def test_rinex_v3_epochs_are_gps_time():
    from canvod.readers.rinex.v3_04 import Rnxv3Obs

    obs = Rnxv3Obs(fpath=_require(RINEX_V3), completeness_mode="off")
    ds = obs.to_ds(keep_data_vars=["SNR"], parser="validated")
    assert obs.header.time_system == "GPS"
    assert ds["epoch"].attrs["time_system"] == "GPS"
    assert ds["epoch"].attrs["time_system_name"] == "GPS time"


def test_rinex_v2_epochs_are_gps_time():
    from canvod.readers.rinex.v2_11 import Rnxv2Obs

    ds = Rnxv2Obs(fpath=_require(RINEX_V2)).to_ds(keep_data_vars=["SNR"])
    assert ds["epoch"].attrs["time_system"] == "GPS"


@pytest.mark.parametrize("scale", ["GLO", "GAL", "BDT"])
def test_rinex_v3_in_another_time_system_is_refused(scale, tmp_path):
    from canvod.readers.rinex.v3_04 import Rnxv3Obs

    fpath = _declaring(_require(RINEX_V3), scale, tmp_path)
    obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
    with pytest.raises(ValueError, match=f"{fpath.name}: epochs are in time system"):
        obs.to_ds(keep_data_vars=["SNR"])


def test_rinex_v2_in_another_time_system_is_refused(tmp_path):
    from canvod.readers.rinex.v2_11 import Rnxv2Obs

    fpath = _declaring(_require(RINEX_V2), "GLO", tmp_path)
    with pytest.raises(ValueError, match="'GLO'"):
        Rnxv2Obs(fpath=fpath).to_ds(keep_data_vars=["SNR"])


def test_nmea_utc_is_converted_to_gps_time():
    from canvod.readers.nmea.v4_00 import NmeaObs

    obs = NmeaObs(fpath=_require(NMEA))
    ds = obs.to_ds()
    assert ds["epoch"].attrs["time_system"] == "GPS"
    # 23:59:42 UTC on 2024-12-31 + 18 leap seconds
    assert ds.epoch.values[0] == np.datetime64("2025-01-01T00:00:00", "ns")
    assert obs.start_time == datetime(2025, 1, 1, tzinfo=UTC)


def test_sbf_epochs_are_gps_time():
    from canvod.readers.sbf.reader import SbfReader

    ds = SbfReader(fpath=_require(SBF)).to_ds(keep_data_vars=["SNR"])
    assert ds["epoch"].attrs["time_system"] == "GPS"
    assert ds.epoch.values[0] == np.datetime64("2025-01-01T00:00:00", "ns")


@pytest.mark.parametrize("scale", ["UTC", "GLO", "GAL", "BDT", "TAI"])
def test_epochs_in_another_time_system_are_refused(scale):
    with pytest.raises(ValueError, match="stores every epoch in GPS time"):
        epoch_coord_attrs(scale)


class TestLeapSeconds:
    @pytest.mark.parametrize(
        ("utc", "n"),
        [
            (datetime(1980, 1, 6), 0),
            (datetime(1981, 6, 30, 23, 59, 59), 0),
            (datetime(1981, 7, 1), 1),
            (datetime(2016, 12, 31, 23, 59, 59), 17),
            (datetime(2017, 1, 1), 18),
            (datetime(2026, 10, 5, tzinfo=UTC), 18),
        ],
    )
    def test_gps_minus_utc(self, utc, n):
        assert gps_minus_utc(utc) == n

    def test_utc_to_gps(self):
        utc = datetime(2024, 12, 31, 23, 59, 42, tzinfo=UTC)
        assert utc_to_gps(utc) == datetime(2025, 1, 1, tzinfo=UTC)

    def test_before_gps_time_is_refused(self):
        with pytest.raises(ValueError, match="before GPS time started"):
            gps_minus_utc(datetime(1980, 1, 5))

    def test_after_the_known_leap_seconds_is_refused(self):
        with pytest.raises(ValueError, match="Update canVODpy"):
            gps_minus_utc(LEAP_SECONDS_KNOWN_UNTIL)
