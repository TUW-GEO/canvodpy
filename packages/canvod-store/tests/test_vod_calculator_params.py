"""D2 (#355): a VOD group records its calculator parameters and refuses others.

ADR 0019 D2. The first write to a VOD group records the calculator and its
parameters in the group's attributes; every later write compares them, so a
group never holds results computed with other parameters silently.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from _helpers import make_synthetic_vod_dataset, new_vod_store

from canvod.store import MyIcechunkStore
from canvod.store.store import VodWriteItem


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "vl"
    store_path.mkdir()
    return new_vod_store(store_path)


GROUP = "tau_omega/canopy_01_vs_reference_01"


def _write(store: MyIcechunkStore, params: dict | None, day: str) -> bool:
    ds = make_synthetic_vod_dataset(slot=0, day=day, seed=hash(day) % 1000)
    item = VodWriteItem(
        group_name=GROUP,
        dataset=ds,
        source_file_hashes={"canopy_01": f"hash_{day}"},
        source_gnss_stores={"canopy_01": "/fake/gnss_store"},
        calculator_name="tau_omega",
        calculator_params=params,
        cadences={np.datetime64(day, "D"): 5.0},
    )
    return store.write_or_append_vod_groups_batch([item])[GROUP].written


def test_the_same_parameters_write_twice(store: MyIcechunkStore) -> None:
    assert _write(store, {"alpha": 1.0}, "2025-03-28")
    assert _write(store, {"alpha": 1.0}, "2025-03-29")


def test_other_parameters_stop_and_are_named(store: MyIcechunkStore) -> None:
    assert _write(store, {"alpha": 1.0, "beta": 2}, "2025-03-28")
    with pytest.raises(ValueError, match="alpha") as caught:
        _write(store, {"alpha": 2.0, "beta": 3}, "2025-03-29")
    message = str(caught.value)
    assert "alpha" in message
    assert "beta" in message
    assert "new analysis name" in message


def test_a_group_without_a_record_accepts_any_first_write(
    store: MyIcechunkStore,
) -> None:
    # A store written before this change has a group but no recorded params.
    _write(store, None, "2025-03-28")
    # A second write with no record to compare against is recorded too.
    assert _write(store, None, "2025-03-29")
