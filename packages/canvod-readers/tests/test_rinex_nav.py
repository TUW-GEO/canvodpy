"""Tests for the RINEX 3.04/3.05 navigation file reader."""

from pathlib import Path

import numpy as np
import pytest

from canvod.readers.rinex.nav import read_rinex_nav

NAV_DIR = "rinex_v3_04_nav_data/02_canopy"

# georinex name of each field the reader gives (RINEX 3.05, Table A6)
GEORINEX_NAMES = {
    "af0": "SVclockBias",
    "af1": "SVclockDrift",
    "af2": "SVclockDriftRate",
    "iode": "IODE",
    "crs": "Crs",
    "delta_n": "DeltaN",
    "m0": "M0",
    "cuc": "Cuc",
    "e": "Eccentricity",
    "cus": "Cus",
    "sqrt_a": "sqrtA",
    "toe": "Toe",
    "cic": "Cic",
    "omega0": "Omega0",
    "cis": "Cis",
    "i0": "Io",
    "crc": "Crc",
    "omega": "omega",
    "omega_dot": "OmegaDot",
    "idot": "IDOT",
    "week": "GPSWeek",
    "health": "health",
    "fit_interval": "FitIntvl",
}


@pytest.fixture
def nav_file(test_data_dir: Path) -> Path:
    path = test_data_dir / "valid" / NAV_DIR / "ract001a00.25p"
    if not path.exists():
        pytest.skip(f"Navigation test file not found: {path}")
    return path


@pytest.mark.integration
def test_gps_records_of_a_file(nav_file: Path) -> None:
    """The file's 11 GPS records, with the values written in the file."""
    nav = read_rinex_nav([nav_file])
    gps = nav.where(nav.sv.str.startswith("G"), drop=True)
    assert gps.sizes["record"] == 11

    g01 = nav.isel(record=int(np.flatnonzero(nav.sv.values == "G01")[0]))
    assert g01.toc.values == np.datetime64("2025-01-01T02:00:00", "ns")
    assert g01.af0.item() == 8.908100426197e-06
    assert g01.sqrt_a.item() == 5.153751745224e03
    assert g01.e.item() == 2.099182456732e-04
    assert g01.toe.item() == 2.664e05
    assert g01.week.item() == 2347
    assert g01.fit_interval.item() == 4.0
    assert nav.toc.attrs["time_system"] == "GPS"


@pytest.mark.integration
def test_records_read_twice_are_kept_once(nav_file: Path) -> None:
    assert (
        read_rinex_nav([nav_file, nav_file]).sizes["record"]
        == read_rinex_nav([nav_file]).sizes["record"]
    )


@pytest.mark.integration
def test_gps_records_agree_with_georinex(nav_file: Path) -> None:
    georinex = pytest.importorskip("georinex")

    ours = read_rinex_nav([nav_file])
    ref = georinex.load(nav_file, use="G")
    for i in range(ours.sizes["record"]):
        rec = ours.isel(record=i)
        if not str(rec.sv.values).startswith("G"):
            continue
        expected = ref.sel(sv=str(rec.sv.values), time=rec.toc.values)
        for ours_name, ref_name in GEORINEX_NAMES.items():
            assert rec[ours_name].item() == pytest.approx(
                expected[ref_name].item(), rel=1e-12, abs=0
            ), (str(rec.sv.values), ours_name)


def test_not_a_navigation_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "obs.rnx"
    path.write_text(
        "     3.04           OBSERVATION DATA    M                   "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
    )
    with pytest.raises(ValueError, match="not a RINEX navigation file"):
        read_rinex_nav([path])


def test_a_file_without_gps_records_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "FANA01INK_R_20250010000_01D_EN.rnx"
    path.write_text(
        "     3.04           N: GNSS NAV DATA    E: GALILEO          "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
        "E01 2025 01 01 00 00 00 1.000000000000D-04 0.000000000000D+00"
        " 0.000000000000D+00\n"
    )
    with pytest.raises(
        ValueError, match=r"FANA01INK_R_20250010000_01D_EN\.rnx.*no GPS"
    ):
        read_rinex_nav([path])
