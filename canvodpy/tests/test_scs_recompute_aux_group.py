"""The SCS recompute reads the aux data from the group wave A read.

Two receivers on one data folder at different positions: the second one
takes the first one's parsed files and only gets new theta and phi
(``_recompute_scs_for_position``). With ``shared_aux_cache_dir`` set, the
aux data of the day are a group (``{fingerprint}/{date}``) in the shared
cache, not its root.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.auxiliary.position.position import ECEFPosition

EPOCHS = np.array(
    ["2025-01-01T00:00:00", "2025-01-01T00:00:30", "2025-01-01T00:01:00"],
    dtype="datetime64[ns]",
)
SIDS = ["G01|L1|C", "G02|L1|C"]
GROUP = "0123abcd/2025001"
POSITION = ECEFPosition(x=4_075_580.0, y=931_853.0, z=4_801_568.0)


@pytest.fixture
def shared_cache(tmp_path: Path) -> Path:
    rng = np.random.default_rng(3)
    shape = (len(EPOCHS), len(SIDS))
    aux = xr.Dataset(
        {name: (("epoch", "sid"), rng.uniform(1e7, 2e7, shape)) for name in "XYZ"},
        coords={"epoch": EPOCHS, "sid": SIDS},
    )
    path = tmp_path / "aux_cache.zarr"
    aux.to_zarr(path, group=GROUP, mode="w", consolidated=False)
    return path


def _parsed_file() -> tuple[Path, xr.Dataset]:
    ds = xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((len(EPOCHS), len(SIDS)), 40.0))},
        coords={"epoch": EPOCHS, "sid": SIDS},
    )
    return Path("ROSA01TUW_R_20250010000_01D_30S_AA.rnx"), ds


def test_recompute_reads_the_group_of_the_shared_cache(shared_cache: Path):
    processor = object.__new__(RinexDataProcessor)

    [(_, ds)] = processor._recompute_scs_for_position(
        [_parsed_file()], shared_cache, POSITION, aux_group=GROUP
    )

    assert {"theta", "phi"} <= set(ds.data_vars)
    assert np.isfinite(ds["theta"].values).all()
