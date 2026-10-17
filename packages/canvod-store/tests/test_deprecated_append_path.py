"""The append path is deprecated and still works on stores written by appending (#280).

Runs write files into day blocks (ADR 0016). The old writers and the
deduplicating read warn, name what to use instead, and keep working on
groups written by appending until v2.0.0.
"""

from __future__ import annotations

import unittest.mock
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import (
    make_synthetic_dataset,
    make_synthetic_vod_dataset,
    new_gnss_store,
    new_vod_store,
)

from canvod.store import MyIcechunkStore
from canvod.store.manager import GnssResearchSite

GROUP = "canopy_01"
RUN = "canvodpy run"


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    return new_gnss_store(tmp_path / "gnss_store")


def _epochs(store: MyIcechunkStore) -> int:
    return store.read_group(GROUP).sizes["epoch"]


def test_write_initial_group_warns_and_writes(store: MyIcechunkStore) -> None:
    with pytest.warns(FutureWarning, match=RUN):
        store.write_initial_group(make_synthetic_dataset(0), GROUP)

    assert _epochs(store) == 180


def test_append_to_group_warns_and_appends(store: MyIcechunkStore) -> None:
    with pytest.warns(FutureWarning):
        store.write_initial_group(make_synthetic_dataset(0), GROUP)

    with pytest.warns(FutureWarning, match=RUN):
        store.append_to_group(make_synthetic_dataset(1), GROUP, action="append")

    assert _epochs(store) == 360


def test_write_or_append_group_warns_and_writes(store: MyIcechunkStore) -> None:
    with pytest.warns(FutureWarning, match=RUN):
        store.write_or_append_group(make_synthetic_dataset(0), GROUP)
    with pytest.warns(FutureWarning, match=RUN):
        store.write_or_append_group(make_synthetic_dataset(1), GROUP)

    assert _epochs(store) == 360


def test_overwrite_file_in_group_warns_and_replaces(store: MyIcechunkStore) -> None:
    first = make_synthetic_dataset(0)
    with pytest.warns(FutureWarning):
        store.write_or_append_group(first, GROUP)
    again = make_synthetic_dataset(0, seed=1)

    with pytest.warns(FutureWarning, match=RUN):
        store.overwrite_file_in_group(
            again,
            GROUP,
            rinex_hash=first.attrs["File Hash"],
            start=first.epoch.values[0],
            end=first.epoch.values[-1],
        )

    stored = store.read_group(GROUP)
    np.testing.assert_array_equal(stored["S1C"].values, again["S1C"].values)


def test_read_group_deduplicated_warns_and_reads(store: MyIcechunkStore) -> None:
    with pytest.warns(FutureWarning):
        store.write_or_append_group(make_synthetic_dataset(0), GROUP)

    with pytest.warns(FutureWarning, match="read_group"):
        ds = store.read_group_deduplicated(GROUP)

    assert ds.sizes["epoch"] == 180


def test_write_or_append_vod_group_warns_and_writes(tmp_path: Path) -> None:
    vod_store = new_vod_store(tmp_path / "vod_store")

    with pytest.warns(FutureWarning, match="write_or_append_vod_groups_batch"):
        written = vod_store.write_or_append_vod_group(
            make_synthetic_vod_dataset(slot=0),
            "tau_omega/canopy_01_vs_reference_01",
            source_file_hashes={"canopy_01": "a", "reference_01": "b"},
            source_gnss_stores={},
            calculator_name="tau_omega",
        )

    assert written


def test_site_reads_an_unsafe_append_group_once_per_epoch_without_warning(
    store: MyIcechunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``read_receiver_data`` keeps the entry of an epoch written last."""
    epochs = np.datetime64("2025-01-01T00:00:00", "ns") + np.array(
        [0, 5, 10, 5, 10], dtype="timedelta64[s]"
    )
    with_duplicates = xr.Dataset(
        {"S1C": (("epoch",), np.array([1.0, 2.0, 3.0, 20.0, 30.0]))},
        coords={"epoch": epochs},
    )
    monkeypatch.setattr(store, "group_exists", lambda *a, **k: True)
    monkeypatch.setattr(store, "read_group", lambda *a, **k: with_duplicates)
    monkeypatch.setattr(store, "_gnss_store_strategy", "unsafe_append")
    site = object.__new__(GnssResearchSite)
    site.gnss_store = store
    site._logger = unittest.mock.MagicMock()

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        ds = site.read_receiver_data(GROUP)

    assert ds["S1C"].values.tolist() == [1.0, 20.0, 30.0]
