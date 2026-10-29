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


# georinex names of the Galileo fields (RINEX 3.05, Table A8)
GALILEO_GEORINEX_NAMES = {
    name: GEORINEX_NAMES[name]
    for name in GEORINEX_NAMES
    if name not in ("iode", "week", "health", "fit_interval")
} | {
    "iodnav": "IODnav",
    "data_sources": "DataSrc",
    "week": "GALWeek",
    "sisa": "SISA",
    "health": "health",
    "bgd_e5a_e1": "BGDe5a",
    "bgd_e5b_e1": "BGDe5b",
    "transmission_time": "TransTime",
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
    nav = read_rinex_nav([nav_file])["G"]
    assert nav.sizes["record"] == 11

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
def test_glonass_records_of_a_file(nav_file: Path) -> None:
    """The file's 6 GLONASS records, with the values written in the file.

    The time of clock is UTC in the file (RINEX 3.05, Table A10): 00:15:00
    UTC is 00:15:18 GPS time on 2025-01-01 (18 leap seconds).
    """
    nav = read_rinex_nav([nav_file])["R"]
    assert nav.sizes["record"] == 6

    r20 = nav.isel(record=int(np.flatnonzero(nav.sv.values == "R20")[0]))
    assert r20.toc.values == np.datetime64("2025-01-01T00:15:18", "ns")
    assert r20.minus_tau_n.item() == -1.240530982614e-04
    assert r20.frame_time.item() == 2.592e05
    assert r20.x.item() == 1.602356640625e04
    assert r20.vy.item() == 1.888092041016e00
    assert r20.az.item() == 9.313225746155e-10
    assert r20.health.item() == 0.0
    assert r20.frequency_number.item() == 2.0
    assert np.isnan(r20.status_flags.item())  # RINEX 3.04: no fifth line
    assert nav.toc.attrs["time_system"] == "GPS"


def test_glonass_record_of_rinex_3_05_has_a_fifth_line(tmp_path: Path) -> None:
    """RINEX 3.05 adds a fifth line to GLONASS records (Table A10)."""
    path = tmp_path / "FANA01INK_R_20250010000_01D_RN.rnx"
    orbit = "     " + "1.000000000000D+00 " * 3 + "{:.12E}"
    path.write_text(
        "     3.05           N: GNSS NAV DATA    R: GLONASS          "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
        "R07 2025 01 01 00 15 00 1.000000000000D-04 0.000000000000D+00"
        " 2.592000000000D+05\n"
        + "\n".join(orbit.format(v).replace("     ", "    ", 1) for v in (0, -5, 0))
        + "\n     2.000000000000E+00 9.999999999990E+08 1.500000000000E+01"
        " 1.000000000000E+00\n"
    )
    r07 = read_rinex_nav([path])["R"].isel(record=0)
    assert r07.frequency_number.item() == -5.0
    assert r07.status_flags.item() == 2.0
    assert r07.urai.item() == 15.0
    assert r07.health_flags.item() == 1.0


@pytest.mark.integration
def test_records_read_twice_are_kept_once(nav_file: Path) -> None:
    once = read_rinex_nav([nav_file])
    twice = read_rinex_nav([nav_file, nav_file])
    assert set(twice) == set(once) == {"G", "E", "R", "C"}
    for system, records in once.items():
        assert twice[system].sizes["record"] == records.sizes["record"]


@pytest.mark.integration
def test_galileo_records_of_a_file(nav_file: Path) -> None:
    """Galileo records keep their GST times, which equal GPS time.

    The file holds the 23:40 batch of E11 twice: from F/NAV (data sources
    258) and from I/NAV (517). Both are kept.
    """
    nav = read_rinex_nav([nav_file])["E"]
    batch = (nav.sv.values == "E11") & (nav.iodnav.values == 49)
    assert sorted(nav.data_sources.values[batch]) == [258, 517]
    e11 = nav.isel(record=int(np.flatnonzero(batch & (nav.data_sources == 517))[0]))
    assert e11.toc.values == np.datetime64("2024-12-31T23:40:00", "ns")
    assert e11.iodnav.item() == 49
    assert e11.sqrt_a.item() == 5.440609739304e03
    assert e11.toe.item() == 2.58e05
    assert e11.data_sources.item() == 517
    assert e11.week.item() == 2347
    assert e11.transmission_time.item() == 2.59235e05
    assert nav.toc.attrs["time_system"] == "GPS"


@pytest.mark.integration
def test_beidou_records_of_a_file(nav_file: Path) -> None:
    """BeiDou times of clock become GPS time: BDT + 14 s (RINEX 3.05, Table 1)."""
    nav = read_rinex_nav([nav_file])["C"]
    assert nav.sizes["record"] == 10
    c29 = nav.isel(record=int(np.flatnonzero(nav.sv.values == "C29")[0]))
    assert c29.toc.values == np.datetime64("2025-01-01T00:00:14", "ns")
    assert c29.aode.item() == 1
    assert c29.sqrt_a.item() == 5.282626367569e03
    assert c29.toe.item() == 2.592e05  # seconds of the BDT week, as written
    assert c29.week.item() == 991  # BDT week, as written
    assert c29.aodc.item() == 1
    assert nav.toc.attrs["time_system"] == "GPS"


def test_qzss_records(tmp_path: Path) -> None:
    """The QZSS example of RINEX 3.05, Table A13."""
    path = tmp_path / "FANA01INK_R_20141330000_01D_JN.rnx"
    path.write_text(
        "     3.05           N: GNSS NAV DATA    J: QZSS             "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
        "J01 2014 05 13 08 15 12 3.323303535581D-04-1.818989403546D-11"
        " 0.000000000000D+00\n"
        "     6.900000000000D+01-4.927812500000D+02 2.222949737636D-09"
        " 7.641996743610D-01\n"
        "    -1.654587686062D-05 7.542252133135D-02 1.197867095470D-05"
        " 6.492895933151D+03\n"
        "     2.025120000000D+05-8.381903171539D-07-9.211997910060D-01"
        "-2.041459083557D-06\n"
        "     7.082252892260D-01-1.558437500000D+02-1.575843337115D+00"
        "-2.349740733276D-09\n"
        "    -6.793140104410D-10 2.000000000000D+00 1.792000000000D+03"
        " 1.000000000000D+00\n"
        "     2.000000000000D+00 1.000000000000D+00-4.656612873077D-09"
        " 6.900000000000D+01\n"
        "     1.989000000000D+05 0.000000000000D+00\n"
    )
    nav = read_rinex_nav([path])
    assert set(nav) == {"J"}
    j01 = nav["J"].isel(record=0)
    assert str(j01.sv.values) == "J01"
    assert j01.toc.values == np.datetime64("2014-05-13T08:15:12", "ns")
    assert j01.e.item() == 7.542252133135e-02
    assert j01.week.item() == 1792
    assert j01.fit_interval_flag.item() == 0


@pytest.mark.integration
def test_gps_records_agree_with_georinex(nav_file: Path) -> None:
    georinex = pytest.importorskip("georinex")

    ours = read_rinex_nav([nav_file])["G"]
    ref = georinex.load(nav_file, use="G")
    for i in range(ours.sizes["record"]):
        rec = ours.isel(record=i)
        expected = ref.sel(sv=str(rec.sv.values), time=rec.toc.values)
        for ours_name, ref_name in GEORINEX_NAMES.items():
            assert rec[ours_name].item() == pytest.approx(
                expected[ref_name].item(), rel=1e-12, abs=0
            ), (str(rec.sv.values), ours_name)


@pytest.mark.integration
def test_galileo_records_agree_with_georinex(nav_file: Path) -> None:
    georinex = pytest.importorskip("georinex")

    ours = read_rinex_nav([nav_file])["E"]
    # georinex names a second record of a satellite and time "E02_1"
    ref = georinex.load(nav_file, use="E").stack(record=("sv", "time"))
    ref = ref.isel(record=np.flatnonzero(ref["sqrtA"].notnull().values))
    assert ref.sizes["record"] == ours.sizes["record"]
    for i in range(ref.sizes["record"]):
        expected = ref.isel(record=i)
        sv, toc = expected.record.item()
        sv = sv.split("_")[0]
        match = np.flatnonzero(
            (ours.sv.values == sv)
            & (ours.toc.values == toc)
            & (ours.data_sources.values == expected["DataSrc"].item())
        )
        assert match.size == 1, (sv, toc)
        rec = ours.isel(record=int(match[0]))
        for ours_name, ref_name in GALILEO_GEORINEX_NAMES.items():
            assert rec[ours_name].item() == pytest.approx(
                expected[ref_name].item(), rel=1e-12, abs=0
            ), (sv, ours_name)


def test_not_a_navigation_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "obs.rnx"
    path.write_text(
        "     3.04           OBSERVATION DATA    M                   "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
    )
    with pytest.raises(ValueError, match="not a RINEX navigation file"):
        read_rinex_nav([path])


def test_a_file_without_records_of_a_known_system_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "FANA01INK_R_20250010000_01D_SN.rnx"
    path.write_text(
        "     3.04           N: GNSS NAV DATA    S: SBAS             "
        "RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
        "S20 2025 01 01 00 00 00 1.000000000000D-04 0.000000000000D+00"
        " 0.000000000000D+00\n"
    )
    with pytest.raises(ValueError, match=r"_01D_SN\.rnx.*no record"):
        read_rinex_nav([path])


def test_no_files_are_refused() -> None:
    with pytest.raises(ValueError, match="no navigation files given"):
        read_rinex_nav([])
