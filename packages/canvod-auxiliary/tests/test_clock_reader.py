"""CLK clock bias is read in seconds (RINEX clock 3.04, Table A16)."""

from pathlib import Path

import numpy as np
import pytest

from canvod.auxiliary.clock.reader import ClkFile

CLK = (
    Path(__file__).parents[2]
    / "canvod-readers/tests/test_data/valid/aux_data/02_CLK"
    / "COD0MGXFIN_20250010000_01D_30S_CLK.CLK"
)

pytestmark = pytest.mark.skipif(not CLK.exists(), reason="CLK test data not available")


def _first_record(sv: str) -> tuple[np.datetime64, float]:
    """Epoch and clock bias of the first ``AS`` record of ``sv``, as written."""
    with CLK.open() as f:
        for line in f:
            parts = line.split()
            if line.startswith("AS") and parts[1] == sv:
                epoch = np.datetime64(
                    f"{parts[2]}-{parts[3]}-{parts[4]}T{parts[5]}:{parts[6]}", "ns"
                ) + np.timedelta64(int(float(parts[7])), "s")
                return epoch, float(parts[9])
    raise LookupError(sv)


@pytest.mark.parametrize("sv", ["C06", "G01", "E02", "R01"])
def test_clock_bias_is_kept_in_seconds(sv):
    epoch, bias = _first_record(sv)
    ds = ClkFile.from_file(CLK).data
    assert ds["clock_offset"].attrs["units"] == "seconds"
    assert float(ds["clock_offset"].sel(epoch=epoch, sv=sv)) == bias


def _clk_copy(tmp_path: Path, name: str, edit) -> Path:
    """The test CLK file under another name, each line passed through ``edit``."""
    out = tmp_path / name
    with CLK.open() as src:
        out.write_text("".join(edit(line) for line in src))
    return out


def test_left_aligned_satellite_count_in_the_header(tmp_path):
    # JPL writes the "# OF SOLN SATS" count left-aligned, not as I6.
    def edit(line: str) -> str:
        if "# OF SOLN SATS" in line:
            return line[:6].strip().ljust(60) + line[60:]
        return line

    ds = ClkFile.from_file(_clk_copy(tmp_path, CLK.name, edit)).data
    expected = ClkFile.from_file(CLK).data
    np.testing.assert_array_equal(ds["clock_offset"], expected["clock_offset"])


def test_fortran_d_exponents(tmp_path):
    # IAC writes the clock bias with Fortran exponents: 0.612319549885D-03.
    def edit(line: str) -> str:
        if line.startswith("AS"):
            return line.replace("E-", "D-").replace("E+", "D+")
        return line

    ds = ClkFile.from_file(_clk_copy(tmp_path, CLK.name, edit)).data
    expected = ClkFile.from_file(CLK).data
    np.testing.assert_array_equal(ds["clock_offset"], expected["clock_offset"])
