"""Tests for RinexDataProcessor._check_store_vars_consistency.

Optimization: this used to open the whole group via xr.open_zarr() just to
read variable names, which resolves every array's chunk manifest to build a
lazy Dask graph -- cost scales with the group's total manifest count
(confirmed Pearson r=0.99 against a 332-day production run, growing from
~0s to >5s/batch). Fixed to read variable names directly off Zarr array
metadata (name + dimension_names) instead, which stays O(1) in manifest
count. These tests pin the exact same warn/info semantics as before the
optimization -- a data variable is any array (other than the append dim
itself) whose dims include the append dim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.store import MyIcechunkStore
from canvod.store_metadata.testing import create_test_store, give_test_metadata

_SIDS = [f"G{i:02d}|L1|C" for i in range(1, 4)]


def _make_ds(data_vars: list[str], file_hash: str, n_epochs: int = 5) -> xr.Dataset:
    epochs = np.datetime64("2025-03-27T00:00:00") + np.arange(
        n_epochs
    ) * np.timedelta64(5, "s")
    rng = np.random.default_rng(0)
    data = {
        name: xr.DataArray(
            rng.uniform(30.0, 55.0, (n_epochs, len(_SIDS))).astype(np.float32),
            dims=["epoch", "sid"],
        )
        for name in data_vars
    }
    return xr.Dataset(
        data,
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": _SIDS},
        attrs={"File Hash": file_hash},
    )


class _FakeSite:
    def __init__(self, store: MyIcechunkStore) -> None:
        self.gnss_store = store


class _RecordingLogger:
    """Captures warning/info calls without needing structlog plumbing."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []
        self.infos: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))

    def info(self, event: str, **kwargs) -> None:
        self.infos.append((event, kwargs))


class _TestProcessor(RinexDataProcessor):
    """Minimal RinexDataProcessor stand-in for _check_store_vars_consistency only."""

    def __init__(self, store: MyIcechunkStore) -> None:
        self.site = _FakeSite(store)
        self._logger: Any = _RecordingLogger()


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "throwaway_store"
    store_path.mkdir()
    store = MyIcechunkStore(create_test_store(store_path))
    give_test_metadata(store_path)
    return store


def test_new_group_is_a_noop(store: MyIcechunkStore) -> None:
    """A group that doesn't exist yet has nothing to check."""
    proc = _TestProcessor(store)
    batch = [(Path("f.rnx"), _make_ds(["S1C"], "h1"))]

    with store.writable_session("main") as session:
        proc._check_store_vars_consistency(session, "canopy_01", batch)

    assert proc._logger.warnings == []
    assert proc._logger.infos == []


def test_matching_vars_logs_nothing(store: MyIcechunkStore) -> None:
    store.write_initial_group(_make_ds(["S1C", "S2W"], "h0"), "canopy_01")
    proc = _TestProcessor(store)
    batch = [(Path("f.rnx"), _make_ds(["S1C", "S2W"], "h1"))]

    with store.writable_session("main") as session:
        proc._check_store_vars_consistency(session, "canopy_01", batch)

    assert proc._logger.warnings == []
    assert proc._logger.infos == []


def test_stale_vars_in_store_warns(store: MyIcechunkStore) -> None:
    """Store has a variable the current batch no longer produces."""
    store.write_initial_group(_make_ds(["S1C", "S2W"], "h0"), "canopy_01")
    proc = _TestProcessor(store)
    batch = [(Path("f.rnx"), _make_ds(["S1C"], "h1"))]

    with store.writable_session("main") as session:
        proc._check_store_vars_consistency(session, "canopy_01", batch)

    assert len(proc._logger.warnings) == 1
    event, kwargs = proc._logger.warnings[0]
    assert event == "store_has_stale_variables"
    assert kwargs["stale_vars"] == ["S2W"]
    assert proc._logger.infos == []


def test_new_vars_in_batch_logs_info(store: MyIcechunkStore) -> None:
    """Batch introduces a variable the store doesn't have yet."""
    store.write_initial_group(_make_ds(["S1C"], "h0"), "canopy_01")
    proc = _TestProcessor(store)
    batch = [(Path("f.rnx"), _make_ds(["S1C", "S5X"], "h1"))]

    with store.writable_session("main") as session:
        proc._check_store_vars_consistency(session, "canopy_01", batch)

    assert proc._logger.warnings == []
    assert len(proc._logger.infos) == 1
    event, kwargs = proc._logger.infos[0]
    assert event == "store_missing_new_variables"
    assert kwargs["new_vars"] == ["S5X"]


def test_matches_xr_open_zarr_ground_truth_after_many_appends(
    store: MyIcechunkStore,
) -> None:
    """Cross-check against the old xr.open_zarr()-based approach directly.

    Appends many small files first (to build up manifest count, the exact
    condition that made the old approach slow) then asserts the new
    zarr-array-metadata approach reports the identical variable set as
    xr.open_zarr would.
    """
    store.write_initial_group(_make_ds(["S1C", "S2W"], "h0"), "canopy_01")
    for i in range(1, 20):
        ds = _make_ds(["S1C", "S2W"], f"h{i}")
        ds = ds.assign_coords(
            epoch=ds.epoch + i * len(ds.epoch) * np.timedelta64(5, "s")
        )
        store.append_to_group(ds, "canopy_01", action="append")

    with store.readonly_session("main") as session:
        ds_store = xr.open_zarr(session.store, group="canopy_01", consolidated=False)
        ground_truth = set(ds_store.data_vars)

    proc = _TestProcessor(store)
    batch = [(Path("f.rnx"), _make_ds(["S1C", "S2W"], "hN"))]
    with store.writable_session("main") as session:
        proc._check_store_vars_consistency(session, "canopy_01", batch)

    # No mismatch -> no warnings/info logged, matching ground truth exactly.
    assert proc._logger.warnings == []
    assert proc._logger.infos == []
    assert ground_truth == {"S1C", "S2W"}
