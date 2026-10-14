"""``read_group_deduplicated`` keeps one entry per epoch, the last written."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import new_gnss_store


def _with_duplicates() -> xr.Dataset:
    """Epochs 0, 5 and 10 s, then 5 and 10 s again with new values.

    The order an ``unsafe_append`` store returns a file appended twice in.
    """
    epochs = np.datetime64("2025-01-01T00:00:00", "ns") + np.array(
        [0, 5, 10, 5, 10], dtype="timedelta64[s]"
    )
    return xr.Dataset(
        {"S1C": (("epoch",), np.array([1.0, 2.0, 3.0, 20.0, 30.0]))},
        coords={"epoch": epochs},
    )


def test_keeps_the_last_written_entry_of_each_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = new_gnss_store(tmp_path / "store")
    # Both writes of the file in the log book, as the store records them.
    for written in ("first", "again"):
        store.append_metadata(
            group_name="canopy_01",
            rinex_hash="fangorn-hash",
            start=np.datetime64("2025-01-01T00:00:00", "ns"),
            end=np.datetime64("2025-01-01T00:00:10", "ns"),
            snapshot_id="",
            action="append",
            commit_msg=f"write {written}",
            dataset_attrs={},
        )
    monkeypatch.setattr(store, "read_group", lambda *a, **k: _with_duplicates())

    ds = store.read_group_deduplicated("canopy_01")

    assert ds.sizes["epoch"] == 3
    assert ds["S1C"].values.tolist() == [1.0, 20.0, 30.0]


def test_refuses_other_keep_strategies(tmp_path: Path) -> None:
    store = new_gnss_store(tmp_path / "store")
    with pytest.raises(ValueError, match="'last'"):
        store.read_group_deduplicated("canopy_01", keep="first")
