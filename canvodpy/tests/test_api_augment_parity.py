"""API ephemeris augmentation vs the orchestrator on the single-day test data.

The fluent API augments through ``AgencyEphemerisProvider``; the
orchestrator through ``_preprocess_aux_data_with_hermite`` and
``preprocess_with_hermite_aux``. Both interpolate the day onto the grid at
the observations' sampling interval (``interpolate_aux_day``); given the
same products, observations and receiver position they must produce the
same sids and the same angles.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from canvodpy.orchestrator.discovery import parse_sampling_interval_from_filename
from canvodpy.orchestrator.processor import preprocess_with_hermite_aux

from canvod.auxiliary.clock.reader import ClkFile
from canvod.auxiliary.ephemeris.provider import AgencyEphemerisProvider
from canvod.auxiliary.ephemeris.reader import Sp3File
from canvod.auxiliary.interpolation import (
    aux_epoch_grid,
    interpolate_aux_day,
    sampling_interval_from_epochs,
)
from canvod.auxiliary.position.position import ECEFPosition
from canvod.auxiliary.preprocessing import prep_aux_ds
from canvod.readers.rinex.v3_04 import Rnxv3Obs

VALID = Path(__file__).parents[2] / "packages/canvod-readers/tests/test_data/valid"
SP3 = VALID / "aux_data/01_SP3/COD0MGXFIN_20250010000_01D_05M_ORB.SP3"
CLK = VALID / "aux_data/02_CLK/COD0MGXFIN_20250010000_01D_30S_CLK.CLK"
RNX = (
    VALID
    / "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
    / "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
)

pytestmark = pytest.mark.skipif(
    not (SP3.exists() and CLK.exists() and RNX.exists()),
    reason="test data not available",
)


def test_provider_augment_matches_orchestrator(tmp_path):
    ds = Rnxv3Obs(fpath=RNX).to_ds(keep_data_vars=["SNR"], write_global_attrs=True)
    pos = ECEFPosition.from_ds_metadata(ds)
    ephem = prep_aux_ds(Sp3File.from_file(SP3).data)
    clock = prep_aux_ds(ClkFile.from_file(CLK).data)

    # The run takes the interval from the file name, the API from the data.
    interval = parse_sampling_interval_from_filename(RNX.name)
    assert sampling_interval_from_epochs(ds["epoch"].values) == interval

    # API: preprocess_day() would download; give it the products directly.
    provider = AgencyEphemerisProvider(aux_data_dir=tmp_path)
    provider._date = "2025001"
    provider._aux_dir = tmp_path
    provider._ephem_ds = ephem
    provider._clock_ds = clock
    api = provider.augment_dataset(ds, pos)

    # Orchestrator: the aux store _preprocess_aux_data_with_hermite writes.
    aux_zarr = tmp_path / "aux_orchestrator.zarr"
    grid = aux_epoch_grid(np.datetime64("2025-01-01"), interval)
    interpolate_aux_day(ephem, clock, grid).to_zarr(
        aux_zarr, mode="w", consolidated=False
    )
    _f, orch, _aux, _sids = preprocess_with_hermite_aux(
        RNX, ["SNR"], aux_zarr, pos, "canopy"
    )

    np.testing.assert_array_equal(api["epoch"].values, orch["epoch"].values)
    assert set(api["sid"].values) == set(orch["sid"].values), (
        f"{len(api.sid)} sids via the API, {len(orch.sid)} via the orchestrator"
    )
    api = api.sel(sid=orch["sid"].values)
    for v in ("SNR", "phi", "theta"):
        np.testing.assert_array_equal(
            api[v].values, orch[v].values, err_msg=f"{v} differs"
        )
