"""The ``aggregate_glonass_fdma`` setting in the readers (A20 #20)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from canvod.readers.nmea.v4_00 import NmeaObs
from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.readers.sbf.reader import SbfReader

_VALID = Path(__file__).parent / "test_data" / "valid"
RINEX3 = (
    _VALID
    / "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
    / "ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)
SBF = _VALID / "sbf/01_Rosalia/02_canopy/25001/ROSA01TUW_R_20250012300_15M_05S_AA.sbf"
NMEA = _VALID / "nmea/02_Hainich/02_canopy/HAIA02MPI_R_20260010000_01H_01S_AA.nmea"

# The test-data submodule; CI runs without it for now.
pytestmark = pytest.mark.skipif(
    not all(f.exists() for f in (RINEX3, SBF, NMEA)),
    reason="test data not available",
)


def _glonass_with_data(aggregate: bool, pad: bool) -> list[str]:
    reader = Rnxv3Obs(fpath=RINEX3, aggregate_glonass_fdma=aggregate)
    ds, _ = reader.to_ds_and_auxiliary(keep_data_vars=["SNR"], pad_global_sid=pad)
    glonass = [s for s in ds.sid.values if s.startswith("R")]
    has_data = (~np.isnan(ds.SNR.sel(sid=glonass))).any("epoch")
    return [s for s, ok in zip(glonass, has_data.values, strict=True) if ok]


@pytest.mark.parametrize("aggregate", [True, False])
def test_padding_keeps_glonass_data(aggregate: bool) -> None:
    """Padding to all signal IDs used to drop every non-aggregated GLONASS ID."""
    unpadded = _glonass_with_data(aggregate, pad=False)
    assert unpadded
    assert _glonass_with_data(aggregate, pad=True) == unpadded


def test_without_aggregation_glonass_ids_name_fdma_bands() -> None:
    sids = _glonass_with_data(aggregate=False, pad=True)
    assert all("_FDMA|" in s for s in sids if "|G1" in s or "|G2" in s)
    assert any("|G1_FDMA|" in s for s in sids)


@pytest.mark.parametrize(("reader", "fpath"), [(SbfReader, SBF), (NmeaObs, NMEA)])
def test_aggregation_only_readers_refuse_it_off(reader, fpath) -> None:
    """Readers that do not declare per_channel_glonass refuse False."""
    assert not reader.per_channel_glonass
    assert reader(fpath=fpath).aggregate_glonass_fdma is True
    assert reader(fpath=fpath, aggregate_glonass_fdma=True)
    with pytest.raises(
        ValidationError, match=f"The reader {reader.__name__} gives GLONASS"
    ):
        reader(fpath=fpath, aggregate_glonass_fdma=False)
