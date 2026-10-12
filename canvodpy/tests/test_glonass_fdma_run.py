"""``aggregate_glonass_fdma`` reaches the per-file read of a run (A20 #20)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import (
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition
from canvod.auxiliary.preprocessing import prep_aux_ds
from canvod.readers.rinex.v3_04 import Rnxv3Obs

RINEX3 = (
    Path(__file__).parents[2]
    / "packages/canvod-readers/tests/test_data/valid/rinex_v3_04/01_Rosalia"
    / "02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)
# The test-data submodule; CI runs without it for now.
needs_test_data = pytest.mark.skipif(
    not RINEX3.exists(), reason="test data not available"
)
EPOCHS = np.array(["2025-01-01T00:00:00"], dtype="datetime64[ns]")
SIDS = ["G01|L1|C"]
POSITION = ECEFPosition(x=4194304.0, y=1162205.0, z=4647245.0)


class _FakeReader:
    file_hash = "deadbeef"

    def to_ds_and_auxiliary(self, **_kwargs):
        ds = xr.Dataset(
            {"SNR": (("epoch", "sid"), [[40.0]])},
            coords={"epoch": EPOCHS, "sid": SIDS},
        )
        return ds, {}


def _aux() -> xr.Dataset:
    xyz = (("epoch", "sid"), [[2e7]])
    return xr.Dataset(
        {"X": xyz, "Y": xyz, "Z": xyz}, coords={"epoch": EPOCHS, "sid": SIDS}
    )


@pytest.mark.parametrize("aggregate", [True, False])
@pytest.mark.parametrize("fanout", [False, True])
def test_reader_gets_the_setting(tmp_path: Path, aggregate: bool, fanout: bool) -> None:
    with (
        mock.patch(
            "canvodpy.factories.ReaderFactory.create", return_value=_FakeReader()
        ) as create,
        mock.patch("xarray.open_zarr", return_value=_aux()),
    ):
        if fanout:
            preprocess_reference_with_hermite_aux_fanout(
                RINEX3,
                None,
                tmp_path,
                {"reference_01_canopy_01": POSITION},
                "reference",
                aggregate_glonass_fdma=aggregate,
            )
        else:
            preprocess_with_hermite_aux(
                RINEX3,
                None,
                tmp_path,
                POSITION,
                "canopy",
                aggregate_glonass_fdma=aggregate,
            )
    assert create.call_args.kwargs["aggregate_glonass_fdma"] is aggregate


def _glonass_sids(aggregate_reader: bool, aggregate_aux: bool) -> set[str]:
    """GLONASS signal IDs with data that the run's SID join keeps."""
    reader = Rnxv3Obs(fpath=RINEX3, aggregate_glonass_fdma=aggregate_reader)
    ds, _ = reader.to_ds_and_auxiliary(keep_data_vars=["SNR"], pad_global_sid=True)
    with_data = ds.sid.values[(~np.isnan(ds.SNR)).any("epoch").values]
    svs = sorted({s.split("|")[0] for s in with_data if s.startswith("R")})
    aux = xr.Dataset(
        {"X": (("epoch", "sv"), np.ones((1, len(svs))))},
        coords={"epoch": EPOCHS, "sv": svs},
    )
    aux_sids = set(prep_aux_ds(aux, aggregate_glonass_fdma=aggregate_aux).sid.values)
    return {s for s in with_data if s.startswith("R")} & aux_sids


@needs_test_data
@pytest.mark.parametrize("aggregate", [True, False])
def test_glonass_survives_the_join_when_both_sides_agree(aggregate: bool) -> None:
    assert _glonass_sids(aggregate, aggregate)


@needs_test_data
def test_mismatched_settings_lose_glonass_signals() -> None:
    """Why reader and aux data must share the setting."""
    assert _glonass_sids(True, True) - _glonass_sids(False, True)
