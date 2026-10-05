"""Orbits and clocks must be in GPS time, the time scale of the epochs."""

from itertools import islice
from pathlib import Path

import pytest

from canvod.auxiliary.clock.parser import parse_clk_file
from canvod.auxiliary.ephemeris.parser import Sp3Parser

AUX_DATA = Path(__file__).parents[2] / "canvod-readers/tests/test_data/valid/aux_data"
SP3 = AUX_DATA / "01_SP3/COD0MGXFIN_20250010000_01D_05M_ORB.SP3"
CLK = AUX_DATA / "02_CLK/COD0MGXFIN_20250010000_01D_30S_CLK.CLK"

pytestmark = pytest.mark.skipif(
    not (SP3.exists() and CLK.exists()), reason="aux test data not available"
)


def _head(src: Path, n: int, tmp_path: Path, old: str = "", new: str = "") -> Path:
    """The first ``n`` lines of ``src``, with ``old`` replaced by ``new`` once."""
    with src.open() as f:
        text = "".join(islice(f, n))
    if old:
        assert old in text
        text = text.replace(old, new, 1)
    out = tmp_path / src.name
    out.write_text(text)
    return out


class TestSp3:
    def test_gps_time_is_read(self, tmp_path):
        ds = Sp3Parser(_head(SP3, 400, tmp_path)).parse()
        assert ds.sizes["epoch"] >= 1

    @pytest.mark.parametrize("scale", ["UTC", "GLO", "TAI"])
    def test_other_time_systems_are_refused(self, scale, tmp_path):
        fpath = _head(SP3, 400, tmp_path, "%c M  cc GPS", f"%c M  cc {scale}")
        with pytest.raises(ValueError, match=f"SP3 time system is '{scale}'"):
            Sp3Parser(fpath).parse()


class TestClk:
    def test_gps_time_is_read(self, tmp_path):
        epochs, _, _ = parse_clk_file(_head(CLK, 2000, tmp_path))
        assert epochs

    @pytest.mark.parametrize("scale", ["UTC", "GAL"])
    def test_other_time_systems_are_refused(self, scale, tmp_path):
        with CLK.open() as f:
            record = next(line for line in f if "TIME SYSTEM ID" in line)
        assert record.startswith("   GPS")
        fpath = _head(CLK, 2000, tmp_path, record, f"   {scale}{record[6:]}")
        with pytest.raises(ValueError, match=f"{CLK.name}: CLK time system is"):
            parse_clk_file(fpath)
