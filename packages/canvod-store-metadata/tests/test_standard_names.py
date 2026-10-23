"""Data carry only standard names from the CF standard name table (#208)."""

from pathlib import Path

import pytest

from canvod.store_metadata.validate import cf_standard_names

_DATA = (
    Path(__file__).resolve().parents[2]
    / "canvod-readers"
    / "tests"
    / "test_data"
    / "valid"
)
_RINEX = next(iter(sorted((_DATA / "rinex_v3_04").rglob("*.rnx"))), None)
_SBF = next(iter(sorted((_DATA / "sbf").rglob("*.sbf"))), None)
_SP3 = _DATA / "aux_data" / "01_SP3" / "COD0MGXFIN_20250010000_01D_05M_ORB.SP3"
_CLK = _DATA / "aux_data" / "02_CLK" / "COD0MGXFIN_20250010000_01D_30S_CLK.CLK"


def _standard_names(ds) -> dict[str, str]:
    return {
        name: var.attrs["standard_name"]
        for name, var in ds.variables.items()
        if "standard_name" in var.attrs
    }


def _read(source: str):
    if source == "rinex":
        from canvod.readers import Rnxv3Obs

        return Rnxv3Obs(fpath=_RINEX).to_ds()
    if source == "sbf":
        from canvod.readers.sbf.reader import SbfReader

        ds, auxiliary = SbfReader(fpath=_SBF).to_ds_and_auxiliary()
        return (ds, *auxiliary.values())
    if source == "sp3":
        from canvod.auxiliary.ephemeris.reader import Sp3File

        return Sp3File.from_file(_SP3).data
    from canvod.auxiliary.clock.reader import ClkFile

    return ClkFile.from_file(_CLK).data


def test_the_vendored_table_holds_cf_names():
    names = cf_standard_names()
    assert "time" in names
    assert "air_temperature" in names
    assert "pseudorange" not in names


@pytest.mark.parametrize("source", ["rinex", "sbf", "sp3", "clk"])
def test_readers_write_only_cf_standard_names(source):
    paths = {"rinex": _RINEX, "sbf": _SBF, "sp3": _SP3, "clk": _CLK}
    if paths[source] is None or not Path(paths[source]).exists():
        pytest.skip("test data not available")
    result = _read(source)
    datasets = result if isinstance(result, tuple) else (result,)

    invented = {
        name: standard_name
        for ds in datasets
        for name, standard_name in _standard_names(ds).items()
        if standard_name not in cf_standard_names()
    }
    assert invented == {}
