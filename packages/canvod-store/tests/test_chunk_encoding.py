"""Tests for MyIcechunkStore.chunk_encoding_for (chunk-mismatch fix, 2026-07-18).

``chunk_strategies`` config was only ever applied as a *read*-side hint
(the ``chunks=`` passed to ``xr.open_zarr`` elsewhere in this class) --
nothing set write-time ``encoding["chunks"]``, so the physical on-disk
chunk shape was left to Zarr's own default, producing the persistent
"specified chunks separate the stored chunks" UserWarning on every read.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvod.store_metadata.testing import create_test_store

from canvod.store import MyIcechunkStore, open_vod_store


def _ds(n_epoch: int, n_sid: int) -> xr.Dataset:
    return xr.Dataset(
        {
            "VOD": (
                ("epoch", "sid"),
                np.random.default_rng(0).uniform(0, 1, (n_epoch, n_sid)),
            ),
        },
        coords={
            "epoch": np.arange(n_epoch),
            "sid": [f"G{i:02d}|L1|C" for i in range(n_sid)],
        },
    )


def test_no_chunk_strategy_configured_returns_empty(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {}
    assert store.chunk_encoding_for(_ds(10, 5)) == {}


def test_unknown_store_type_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown store_type 'vod'"):
        MyIcechunkStore(tmp_path / "site" / "vod_store", store_type="vod")


def test_configured_dim_uses_config_size_not_write_size(tmp_path: Path) -> None:
    # The whole point of the fix: a small first write (100 epochs) still
    # gets the FULL configured chunk size (17280) -- Zarr supports writing
    # less than one chunk and filling the rest on later appends, which is
    # exactly how a receiver's first (partial-day) file should behave.
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {"epoch": 17280, "sid": -1}
    encoding = store.chunk_encoding_for(_ds(n_epoch=100, n_sid=5))
    assert encoding["VOD"]["chunks"] == (17280, 5)


def test_unspecified_dim_chunk_size_matches_current_dim_size(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {"epoch": 17280}  # no "sid" entry at all
    encoding = store.chunk_encoding_for(_ds(n_epoch=100, n_sid=7))
    assert encoding["VOD"]["chunks"] == (17280, 7)


def test_minus_one_means_one_chunk_spanning_current_size(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {"epoch": 17280, "sid": -1}
    encoding = store.chunk_encoding_for(_ds(n_epoch=17280, n_sid=321))
    assert encoding["VOD"]["chunks"] == (17280, 321)


def test_applies_to_coordinates_sharing_a_configured_dim(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {"epoch": 17280, "sid": -1}
    encoding = store.chunk_encoding_for(_ds(n_epoch=100, n_sid=5))
    assert "epoch" in encoding
    assert encoding["epoch"]["chunks"] == (17280,)


def test_scalar_variable_is_skipped_not_crashed(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store.chunk_strategy = {"epoch": 17280, "sid": -1}
    ds = _ds(10, 5)
    ds["scalar_attr"] = 42  # 0-d variable, no dims
    encoding = store.chunk_encoding_for(ds)
    assert "scalar_attr" not in encoding
    assert encoding["VOD"]["chunks"] == (17280, 5)
