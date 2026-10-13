"""Test the description of a stored group."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
from canvod.store_metadata.location import open_repository
from canvod.store_metadata.testing import create_test_store
from icechunk.xarray import to_icechunk

from canvod.store import open_gnss_store

_DAY = np.timedelta64(1, "D")


def test_group_info_gives_each_days_cadence(tmp_path: Path):
    t0 = np.datetime64("2025-01-01T00:00:00", "ns")
    # Day 2 at 5 s was written before day 1 at 1 s.
    epochs = np.concatenate(
        [
            t0 + _DAY + np.arange(0, 600, 5).astype("m8[s]"),
            t0 + np.arange(0, 600, 1).astype("m8[s]"),
        ]
    )
    ds = xr.Dataset(
        {"SNR": (("epoch", "sid"), np.ones((epochs.size, 1), dtype="f4"))},
        coords={"epoch": epochs, "sid": ["G01|L1|C"]},
    )
    store_path = create_test_store(tmp_path / "store")
    session = open_repository(store_path).writable_session("main")
    to_icechunk(ds, session, group="canopy_01")
    session.commit("data")

    info = open_gnss_store(store_path).get_group_info("canopy_01")

    assert info["temporal_info"]["cadences"] == [
        {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T00:09:59Z",
            "cadence_s": 1.0,
        },
        {
            "start": "2025-01-02T00:00:00Z",
            "end": "2025-01-02T00:09:55Z",
            "cadence_s": 5.0,
        },
    ]
    assert info["temporal_info"]["resolution"] == "1 s"
