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
