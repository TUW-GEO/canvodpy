"""Epoch records with blank-padded month, day, hour, and minute (#702).

RINEX 3.04 and 3.05 (Table A3, EPOCH record) write month, day, hour and
minute as ``4(1X,I2.2)``, zero-padded. Some receivers write them as ``I2``,
blank-padded (``" 1"``). The fields stay unambiguous, so both parsers read
both forms.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from canvod.readers.gnss_specs.models import Rnxv3ObsEpochRecordLineModel
from canvod.readers.rinex.v3_04 import Rnxv3Obs, UnvalidatedParserWarning
from canvod.utils import testing


def _h(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


_HEADER = "".join(
    [
        _h("     3.04           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
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
        _h("  2025     1     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        _h("DBHZ", "SIGNAL STRENGTH UNIT"),
        _h("", "END OF HEADER"),
    ]
)

_SAT = (
    "{}  21144290.617 7 111114043.962 7        46.300    "
    "21144292.457 8  86582356.164 8        40.100\n"
)

# Three epochs, one minute apart; the clock offset has no leading zero.
_EPOCH_LINES = {
    "blank": "> 2025  1  1  0 {:2d}  0.0000000  0  2        .000126616000\n",
    "zero": "> 2025 01 01 00 {:02d}  0.0000000  0  2        .000126616000\n",
}
_EXPECTED = np.array(
    ["2025-01-01T00:00", "2025-01-01T00:01", "2025-01-01T00:02"],
    dtype="datetime64[ns]",
)


def _write(path: Path, padding: str) -> Path:
    epochs = "".join(
        _EPOCH_LINES[padding].format(minute) + _SAT.format("G01") + _SAT.format("G02")
        for minute in range(3)
    )
    path.write_text(_HEADER + epochs)
    return path


@pytest.mark.parametrize("padding", ["blank", "zero"])
def test_epoch_line_model_reads_both_paddings(padding):
    info = Rnxv3ObsEpochRecordLineModel.model_validate(
        {"epoch": _EPOCH_LINES[padding].format(2).rstrip("\n")}
    )
    assert (info.year, info.month, info.day, info.hour, info.minute) == (
        2025,
        1,
        1,
        0,
        2,
    )
    assert info.num_satellites == 2


@pytest.mark.parametrize("padding", ["blank", "zero"])
@pytest.mark.parametrize("parser", ["validated", "unvalidated_fast"])
def test_file_reads_every_epoch(tmp_path, padding, parser):
    """The default completeness check passes and no epoch is dropped."""
    obs = Rnxv3Obs(fpath=_write(tmp_path / "f.rnx", padding))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnvalidatedParserWarning)
        ds = obs.to_ds(keep_data_vars=["SNR"], parser=parser)
    np.testing.assert_array_equal(ds.epoch.values, _EXPECTED)
    snr = ds["SNR"].sel(sid="G01|L1|C").values
    np.testing.assert_allclose(snr, [46.3, 46.3, 46.3])
