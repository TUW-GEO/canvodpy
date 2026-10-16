"""The processor's day-block write (ADR 0016): one session, one commit.

A store whose groups were written by appending keeps the cross-group
fork/merge write (``test_cross_group_batch_write.py``); a new store gets
day blocks.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
import zarr
from canvodpy.orchestrator.processor import RinexDataProcessor
from test_cross_group_batch_write import (
    _make_ds,
    _TestProcessor,
    store,  # noqa: F401 (fixture)
)

from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import CadenceError
from canvod.store_metadata.io import read_metadata
from canvod.store_metadata.layout import is_day_block_group

_DAY = "2025-03-28"


def _config(*, aggregation: str | None = None, store_sbf_metadata: bool = True):
    """The settings the write reads, recorded in commits through model_dump."""
    params = SimpleNamespace(store_sbf_metadata=store_sbf_metadata)
    temporal_aggregation = (
        None if aggregation is None else SimpleNamespace(enabled=True, freq=aggregation)
    )
    preprocessing = SimpleNamespace(
        temporal_aggregation=temporal_aggregation,
        grid_assignment=None,
        model_dump=lambda mode: {"temporal_aggregation": aggregation},
    )
    dumped = {"params": {"store_sbf_metadata": store_sbf_metadata}}
    processing = SimpleNamespace(
        params=params, preprocessing=preprocessing, model_dump=lambda mode: dumped
    )
    return SimpleNamespace(processing=processing, sites=SimpleNamespace(sites={}))


def _file(file_id: str, slot: int, sampling: str = "05S", day: str = _DAY):
    """A 10-epoch file at 5 s from the start of 15-minute period ``slot``.

    Its canonical name gives the period and ``sampling``.
    """
    ds = _make_ds(file_id, slot=0, day=day)
    ds = ds.assign_coords(epoch=ds.epoch + np.timedelta64(slot * 15, "m"))
    doy = int(np.datetime64(day, "D").astype(object).strftime("%j"))
    minutes = slot * 15
    ds.attrs["canonical_name"] = (
        f"FANR35INK_R_2025{doy:03d}{minutes // 60:02d}{minutes % 60:02d}"
        f"_15M_{sampling}_AA.rnx"
    )
    return Path(f"{file_id}.rnx"), ds


class _DayBlockProcessor(_TestProcessor):
    """The batch-write stand-in, deciding the layout as a run does."""

    _writes_day_blocks = RinexDataProcessor._writes_day_blocks


def _inputs(name: str, files: list[tuple[Path, xr.Dataset]]):
    return [(name, files, [f for f, _ in files], None, None, "rinex3")]


@pytest.fixture
def proc(store: MyIcechunkStore) -> _DayBlockProcessor:  # noqa: F811
    proc = _DayBlockProcessor(store)
    proc._config = _config()
    return proc


def test_a_new_store_is_written_as_day_blocks(proc, store) -> None:  # noqa: F811
    files = [_file("a", 0), _file("b", 1)]
    n_snapshots = len(list(store.repo.ancestry(branch="main")))

    results = proc._write_day_blocks(_inputs("canopy_01", files))

    assert results["canopy_01"].actions["initial"] == 1
    assert results["canopy_01"].actions["written"] == 1
    # One commit for data, log book and metadata (plus the one-time
    # source_format commit of a new store).
    assert len(list(store.repo.ancestry(branch="main"))) == n_snapshots + 2
    with store.readonly_session("main") as session:
        attrs = zarr.open_group(session.store, mode="r", path="canopy_01").attrs
        assert is_day_block_group(attrs)
    full = store.read_group("canopy_01")
    assert full.sizes["epoch"] == 17280
    ds = store.read_group("canopy_01", drop_empty=True)
    expected = np.concatenate([d.epoch.values for _, d in files])
    np.testing.assert_array_equal(ds.epoch.values, expected)
    with store.readonly_session("main") as session:
        log = store.load_metadata(session.store, "canopy_01")
    assert log["epochs"].to_list() == [10, 10]
    summary = read_metadata(store.store_path).summaries
    assert summary.total_epochs == 20


def test_a_rerun_skips_and_adds_nothing(proc, store) -> None:  # noqa: F811
    files = [_file("a", 0), _file("b", 1)]
    proc._write_day_blocks(_inputs("canopy_01", files))

    results = proc._write_day_blocks(_inputs("canopy_01", files))

    assert results["canopy_01"].actions["skipped"] == 2
    assert store.read_group("canopy_01").sizes["epoch"] == 17280
    assert store.read_group("canopy_01", drop_empty=True).sizes["epoch"] == 20


def test_overwrite_rewrites_the_file_region(store) -> None:  # noqa: F811
    proc = _DayBlockProcessor(store, strategy="overwrite")
    proc._config = _config()
    path, ds = _file("a", 0)
    proc._write_day_blocks(_inputs("canopy_01", [(path, ds)]))
    changed = ds.copy(deep=True)
    changed["S1C"][:] = 11.0

    results = proc._write_day_blocks(_inputs("canopy_01", [(path, changed)]))

    assert results["canopy_01"].actions["overwritten"] == 1
    stored = store.read_group("canopy_01", drop_empty=True)
    assert stored.sizes["epoch"] == 10
    assert float(stored["S1C"].max()) == 11.0
    assert read_metadata(store.store_path).summaries.total_epochs == 10


def test_a_file_written_again_with_fewer_epochs_leaves_nothing_of_before(
    store,  # noqa: F811
) -> None:
    proc = _DayBlockProcessor(store, strategy="overwrite")
    proc._config = _config()
    path, ds = _file("a", 0)
    proc._write_day_blocks(_inputs("canopy_01", [(path, ds)]))
    # The same file, two epochs fewer at the start and three at the end.
    shorter = ds.isel(epoch=slice(2, 7))

    results = proc._write_day_blocks(_inputs("canopy_01", [(path, shorter)]))

    assert results["canopy_01"].actions["overwritten"] == 1
    stored = store.read_group("canopy_01", drop_empty=True)
    np.testing.assert_array_equal(stored.epoch.values, shorter.epoch.values)
    assert read_metadata(store.store_path).summaries.total_epochs == 5


def test_a_first_write_leaves_the_rest_of_its_period_alone(proc, store) -> None:  # noqa: F811
    # A receiver restart: Y starts at 00:10 and is stored first; X, named
    # for 00:00, ends before 00:10 and is written later for the first time.
    y_path, y = _file("y", 0)
    y = y.assign_coords(epoch=y.epoch + np.timedelta64(10, "m"))
    y.attrs["canonical_name"] = y.attrs["canonical_name"].replace(
        "0000_15M", "0010_15M"
    )
    x = _file("x", 0)
    proc._write_day_blocks(_inputs("canopy_01", [(y_path, y)]))

    proc._write_day_blocks(_inputs("canopy_01", [x]))

    stored = store.read_group("canopy_01", drop_empty=True)
    expected = np.concatenate([x[1].epoch.values, y.epoch.values])
    np.testing.assert_array_equal(stored.epoch.values, expected)
    assert read_metadata(store.store_path).summaries.total_epochs == 20


def test_days_out_of_order_and_two_groups(proc, store) -> None:  # noqa: F811
    day_2 = _file("d2", 0, day="2025-03-29")
    day_1 = _file("d1", 0)
    proc._write_day_blocks(
        _inputs("canopy_01", [day_2]) + _inputs("reference_01_canopy_01", [day_2])
    )
    proc._write_day_blocks(_inputs("canopy_01", [day_1]))

    ds = store.read_group("canopy_01", drop_empty=True)
    assert bool(ds.indexes["epoch"].is_monotonic_increasing)
    assert ds.sizes["epoch"] == 20
    assert store.read_group("reference_01_canopy_01").sizes["epoch"] == 17280


def test_the_aggregation_cadence_sets_the_slots(store) -> None:  # noqa: F811
    proc = _DayBlockProcessor(store)
    proc._config = _config(aggregation="30s")
    path, ds = _file("a", 0, sampling="01S")
    aggregated = ds.isel(epoch=slice(0, None, 6))

    proc._write_day_blocks(_inputs("canopy_01", [(path, aggregated)]))

    assert store.read_group("canopy_01").sizes["epoch"] == 2880


def test_a_file_finer_than_its_name_is_not_stored(proc, store) -> None:  # noqa: F811
    # The name says 30 s, the epochs are 5 s apart: 6 epochs per slot. The
    # file is refused (logged, like any file that fails), not thinned.
    results = proc._write_day_blocks(
        _inputs("canopy_01", [_file("a", 0, sampling="30S")])
    )

    assert sum(results["canopy_01"].actions.values()) == 0
    # Nothing to commit: not even the group's empty block is stored.
    assert "canopy_01" not in (store.list_groups() or [])


def test_a_cadence_off_the_chunk_grid_stops_the_run(proc) -> None:
    with pytest.raises(CadenceError):
        proc._write_day_blocks(_inputs("canopy_01", [_file("a", 0, sampling="07S")]))


def test_a_store_written_by_appending_keeps_appending(proc, store) -> None:  # noqa: F811
    proc._write_receiver_batch_forked(_inputs("canopy_01", [_file("a", 0)]))

    assert not proc._writes_day_blocks()


def test_a_store_not_created_yet_gets_day_blocks(proc, tmp_path) -> None:
    proc.site.gnss_store_path = tmp_path / "not_yet"

    assert proc._writes_day_blocks()


def test_without_preprocessing_the_names_set_the_cadence(proc) -> None:
    proc._config.processing.preprocessing = None

    assert proc._day_block_cadence_s("canopy_01", [_file("a", 0)]) == 5.0


def _epoch_axis_reads(monkeypatch, proc, files) -> int:
    """How often writing ``files`` reads a group's whole epoch axis."""
    from canvod.store import day_blocks as module

    reads = []
    original = module._epochs_ns

    def counting(zgroup, group):
        reads.append(group)
        return original(zgroup, group)

    monkeypatch.setattr(module, "_epochs_ns", counting)
    proc._write_day_blocks(_inputs("canopy_01", files))
    return len(reads)


def test_the_epoch_axis_is_read_once_not_per_file(store, monkeypatch) -> None:  # noqa: F811
    # Reading the epoch axis reads every epoch chunk of the group, so a
    # day's files share one read of their day blocks.
    def proc():
        p = _DayBlockProcessor(store)
        p._config = _config()
        return p

    two = _epoch_axis_reads(
        monkeypatch,
        proc(),
        [_file("a", 0, day="2025-03-28"), _file("b", 1, day="2025-03-28")],
    )
    five = _epoch_axis_reads(
        monkeypatch,
        proc(),
        [_file(f"c{i}", i, day="2025-03-29") for i in range(5)],
    )
    assert five == two
