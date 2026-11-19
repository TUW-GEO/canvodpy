"""``LEAP SECONDS`` is optional in the RINEX 3 header (#703).

RINEX 3.04 Table A2 marks the record optional. Without it, the global
attributes leave out ``Leap Seconds``, as the RINEX 2.11 reader does.
"""

from pathlib import Path

from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.utils import testing


def _h(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


def _header(*extra: str) -> str:
    return "".join(
        [
            _h(
                "     3.04           OBSERVATION DATA    G (GPS)",
                "RINEX VERSION / TYPE",
            ),
            _h(
                "TEST                TEST                20250101 000000 UTC",
                "PGM / RUN BY / DATE",
            ),
            _h(testing.CANOPY_SITE.upper(), "MARKER NAME"),
            _h("TEST                TEST", "OBSERVER / AGENCY"),
            _h("1                   TEST RECEIVER       1.0", "REC # / TYPE / VERS"),
            _h("1                   TEST ANTENNA", "ANT # / TYPE"),
            _h(
                f"{testing.ECEF_X:14.4f}{testing.ECEF_Y:14.4f}{testing.ECEF_Z:14.4f}",
                "APPROX POSITION XYZ",
            ),
            _h("        0.0000        0.0000        0.0000", "ANTENNA: DELTA H/E/N"),
            _h("G    6 C1C L1C S1C C2W L2W S2W", "SYS / # / OBS TYPES"),
            _h("    60.000", "INTERVAL"),
            _h(
                "  2025     1     1     0     0    0.0000000     GPS",
                "TIME OF FIRST OBS",
            ),
            _h("DBHZ", "SIGNAL STRENGTH UNIT"),
            *extra,
            _h("", "END OF HEADER"),
        ]
    )


_SAT = (
    "{}  21144290.617 7 111114043.962 7        46.300    "
    "21144292.457 8  86582356.164 8        40.100\n"
)


def _write(path: Path, header: str) -> Path:
    epochs = "".join(
        f"> 2025 01 01 00 {minute:02d}  0.0000000  0  2\n"
        + _SAT.format("G01")
        + _SAT.format("G02")
        for minute in range(3)
    )
    path.write_text(header + epochs)
    return path


def test_global_attrs_without_leap_seconds_record(tmp_path):
    obs = Rnxv3Obs(fpath=_write(tmp_path / "f.rnx", _header()))
    ds = obs.to_ds(keep_data_vars=["SNR"], write_global_attrs=True)
    assert ds.sizes["epoch"] == 3
    assert "Leap Seconds" not in ds.attrs


def test_global_attrs_keep_leap_seconds_record(tmp_path):
    header = _header(_h("    18", "LEAP SECONDS"))
    obs = Rnxv3Obs(fpath=_write(tmp_path / "f.rnx", header))
    ds = obs.to_ds(keep_data_vars=["SNR"], write_global_attrs=True)
    assert ds.attrs["Leap Seconds"] == "18 s"
