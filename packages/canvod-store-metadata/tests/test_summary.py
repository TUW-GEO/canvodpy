"""Test the store summary that fills temporal coverage and summaries."""

import icechunk
import numpy as np
import pytest
import zarr
from test_io import _make_metadata

from canvod.store_metadata import (
    apply_updates,
    read_metadata,
    summarize_store,
    update_metadata,
    write_metadata,
)
from canvod.store_metadata.testing import made_up_metadata


def _write_group(
    root: zarr.Group,
    name: str,
    n_epochs: int,
    sids: list[str],
    step_s: int = 5,
    seconds: np.ndarray | None = None,
) -> None:
    """A receiver group with CF-encoded epochs, as xarray writes it.

    ``seconds`` gives the epochs (seconds since 2025-01-01) in their stored
    order instead of ``n_epochs`` epochs ``step_s`` apart.
    """
    if seconds is None:
        seconds = np.arange(n_epochs) * step_s
    n_epochs = seconds.size
    g = root.create_group(name)
    epoch = g.create_array("epoch", shape=(n_epochs,), dtype="i8")
    epoch[:] = seconds
    epoch.attrs["units"] = "seconds since 2025-01-01 00:00:00"
    g.create_array("sid", shape=(len(sids),), dtype=str)[:] = np.array(sids)
    g.create_array("system", shape=(len(sids),), dtype=str)[:] = np.array(
        [s[0] for s in sids]
    )
    g.create_array("SNR", shape=(n_epochs, len(sids)), dtype="f4")
    table = g.create_group("metadata/table")
    table.create_array("rinex_hash", shape=(3,), dtype=str)[:] = np.array(
        ["a", "b", "b"]
    )
    table.create_array("action", shape=(3,), dtype=str)[:] = np.array(
        ["initial", "appended", "skipped"]
    )


def _make_store(path):
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    _write_group(root, "canopy_01", 720, ["G01|L1|C", "E11|E1|C"])
    _write_group(root, "reference_01_canopy_01", 360, ["G01|L1|C", "C11|B1I|I"])
    session.commit("data")
    return path


def test_summarize_store(tmp_path):
    store_path = _make_store(tmp_path / "store")

    with pytest.warns(FutureWarning, match="mapping of receiver name to type"):
        updates = summarize_store(
            store_path, receivers={"canopy_01", "reference_01", "canopy_02"}
        )

    assert updates["temporal.time_coverage_start"] == "2025-01-01T00:00:00Z"
    assert updates["temporal.time_coverage_end"] == "2025-01-01T00:59:55Z"
    assert updates["temporal.time_coverage_duration"] == "PT3595S"
    assert updates["temporal.time_coverage_resolution"] == "PT5S"
    assert updates["summaries.total_epochs"] == 720
    assert updates["summaries.total_sids"] == 3
    assert updates["summaries.constellations"] == ["BeiDou", "GPS", "Galileo"]
    assert updates["summaries.variables"] == ["SNR"]
    assert updates["summaries.file_count"] == 4  # 2 stored files per group
    assert updates["instruments.receivers.canopy_01.epochs"] == 720
    assert updates["instruments.receivers.reference_01.epochs"] == 360
    assert updates["instruments.receivers.reference_01.sids"] == 2
    assert not any(k.startswith("instruments.receivers.canopy_02") for k in updates)


def test_long_durations_are_iso_8601_without_exponents(tmp_path):
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "store"))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    _write_group(root, "canopy_01", 3, ["G01|L1|C"], step_s=15 * 86400)
    session.commit("data")

    updates = summarize_store(tmp_path / "store", receivers={"canopy_01": "canopy"})

    assert updates["temporal.time_coverage_duration"] == "PT2592000S"
    # One epoch per day: no day has a cadence.
    assert updates["temporal.time_coverage_resolution"] is None


def test_summary_keeps_receivers_whose_names_extend_each_other_apart(tmp_path):
    store_path = _make_store(tmp_path / "store")
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store_path)))
    session = repo.writable_session("main")
    _write_group(
        zarr.open_group(session.store, mode="a"), "canopy_01_b", 60, ["G02|L1|C"]
    )
    session.commit("second canopy")

    updates = summarize_store(
        store_path,
        receivers={
            "canopy_01": "canopy",
            "canopy_01_b": "canopy",
            "reference_01": "reference",
        },
    )

    assert updates["instruments.receivers.canopy_01.epochs"] == 720
    assert updates["instruments.receivers.canopy_01.sids"] == 2
    assert updates["instruments.receivers.canopy_01_b.epochs"] == 60
    assert updates["instruments.receivers.reference_01.epochs"] == 360


def test_summary_written_into_metadata(tmp_path):
    store_path = _make_store(tmp_path / "store")
    write_metadata(store_path, _make_metadata())

    update_metadata(store_path, {})

    meta = read_metadata(store_path)
    assert meta.temporal.collected_start == "2025-01-01T00:00:00Z"
    assert meta.summaries.temporal_resolution_s == 5.0
    assert meta.spatial.extent_temporal_interval == [
        ["2025-01-01T00:00:00Z", "2025-01-01T00:59:55Z"]
    ]


def test_empty_store_gives_no_updates(tmp_path):
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "s"))
    )
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")

    updates = summarize_store(tmp_path / "s")

    assert updates == {}
    assert apply_updates(_make_metadata(), updates) == _make_metadata()


_DAY = 86400


def _store_with(tmp_path, groups: dict[str, np.ndarray]):
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "store"))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    for name, seconds in groups.items():
        _write_group(root, name, 0, ["G01|L1|C"], seconds=seconds)
    session.commit("data")
    return tmp_path / "store"


def test_each_day_has_its_own_cadence(tmp_path):
    # Day 2 at 5 s was written before day 1 at 1 s.
    day1 = np.arange(0, 3600, 1)
    day2 = _DAY + np.arange(0, 3600, 5)
    store_path = _store_with(tmp_path, {"canopy_01": np.concatenate([day2, day1])})

    updates = summarize_store(store_path, receivers={"canopy_01": "canopy"})

    assert updates["instruments.receivers.canopy_01.cadences"] == [
        {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T00:59:59Z",
            "cadence_s": 1.0,
        },
        {
            "start": "2025-01-02T00:00:00Z",
            "end": "2025-01-02T00:59:55Z",
            "cadence_s": 5.0,
        },
    ]
    # The store's resolution is its finest cadence.
    assert updates["temporal.time_coverage_resolution"] == "PT1S"
    assert updates["summaries.temporal_resolution_s"] == 1.0


def test_days_at_the_same_cadence_form_one_range(tmp_path):
    # Day 2 has gaps (epochs missing), which do not change its cadence.
    day1 = np.arange(0, _DAY, 30)
    day2 = _DAY + np.concatenate([np.arange(0, 600, 30), np.arange(3000, 3600, 30)])
    store_path = _store_with(tmp_path, {"canopy_01": np.concatenate([day1, day2])})

    updates = summarize_store(store_path, receivers={"canopy_01": "canopy"})

    assert updates["instruments.receivers.canopy_01.cadences"] == [
        {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:59:30Z",
            "cadence_s": 30.0,
        }
    ]


def test_receivers_report_their_own_cadences(tmp_path):
    store_path = _store_with(
        tmp_path,
        {
            "canopy_01": np.arange(0, 600, 1),
            "reference_01_canopy_01": np.arange(0, 600, 5),
        },
    )

    updates = summarize_store(
        store_path, receivers={"canopy_01": "canopy", "reference_01": "reference"}
    )

    assert updates["instruments.receivers.canopy_01.cadences"][0]["cadence_s"] == 1.0
    assert updates["instruments.receivers.reference_01.cadences"][0]["cadence_s"] == 5.0
    assert updates["summaries.temporal_resolution_s"] == 1.0


def test_cadences_written_into_metadata(tmp_path):
    store_path = _store_with(tmp_path, {"canopy_01": np.arange(0, 600, 5)})
    write_metadata(store_path, made_up_metadata())

    update_metadata(store_path, {})

    receiver = read_metadata(store_path).instruments.receivers["canopy_01"]
    assert [(c.start, c.end, c.cadence_s) for c in receiver.cadences] == [
        ("2025-01-01T00:00:00Z", "2025-01-01T00:09:55Z", 5.0)
    ]
