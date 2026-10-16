"""Day blocks: what a group holds and what loading returns (ADR 0016)."""

from __future__ import annotations

import icechunk
import numpy as np
import pytest
import xarray as xr
import zarr
from icechunk.xarray import to_icechunk

from canvod.store.day_blocks import (
    CadenceError,
    LayoutError,
    SlotCollisionError,
    add_day_block,
    day_blocks,
    load_group,
    stored_epoch_chunk,
    write_file_region,
)
from canvod.store.prepare import (
    GroupCoordinatesMismatchError,
    GroupVariablesMismatchError,
)

GROUP = "canopy_01"
SIDS = ["G01|L1|C", "G02|L1|C", "E01|E1|C"]
DAY_1 = np.datetime64("2025-01-01", "D")
DAY_2 = np.datetime64("2025-01-02", "D")


def _file(
    day: np.datetime64,
    start_s: float,
    n: int,
    cadence_s: float,
    *,
    jitter_s: np.ndarray | None = None,
    file_hash: str = "hash",
) -> xr.Dataset:
    """A made-up file: ``n`` epochs from ``start_s`` seconds into ``day``."""
    offsets = start_s + np.arange(n) * cadence_s
    if jitter_s is not None:
        offsets = offsets + jitter_s
    epochs = day.astype("M8[ns]") + (offsets * 1e9).astype("m8[ns]")
    snr = 30.0 + np.arange(n * len(SIDS), dtype="f4").reshape(n, len(SIDS))
    epoch = xr.Variable("epoch", epochs, {"time_system": "GPS"})
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), snr),
            "LLI": (("epoch", "sid"), np.zeros((n, len(SIDS)), dtype="i1")),
        },
        coords={"epoch": epoch, "sid": SIDS},
        attrs={"File Hash": file_hash},
    )


@pytest.fixture
def repo() -> icechunk.Repository:
    return icechunk.Repository.create(icechunk.in_memory_storage())


@pytest.fixture
def session(repo) -> icechunk.Session:
    return repo.writable_session("main")


def _write(session, ds: xr.Dataset, cadence_s: float):
    for day in np.unique(ds.epoch.values.astype("M8[D]")):
        add_day_block(session, GROUP, day, cadence_s, template=ds)
    return write_file_region(session, GROUP, ds)


def test_days_written_out_of_order_load_in_time_order(session):
    _write(session, _file(DAY_2, 0, 10, 5), 5)
    _write(session, _file(DAY_1, 0, 10, 5), 5)

    ds = load_group(session.store, GROUP)

    assert ds.sizes["epoch"] == 2 * 17280
    assert bool(ds.indexes["epoch"].is_monotonic_increasing)
    assert ds.epoch.values[0] == DAY_1.astype("M8[ns]")
    # On disk the blocks keep the order the days were first written in.
    blocks = day_blocks(session.store, GROUP)
    assert blocks[DAY_2].start == 0
    assert blocks[DAY_1].start == 17280


def test_a_1_s_day_and_a_5_s_day_share_a_group(session):
    _write(session, _file(DAY_1, 0, 20, 1), 1)
    _write(session, _file(DAY_2, 0, 20, 5), 5)

    blocks = day_blocks(session.store, GROUP)

    assert blocks[DAY_1].cadence_s == 1
    assert blocks[DAY_1].stop - blocks[DAY_1].start == 86400
    assert blocks[DAY_2].cadence_s == 5
    assert blocks[DAY_2].stop - blocks[DAY_2].start == 17280
    ds = load_group(session.store, GROUP, drop_empty=True)
    assert ds.sizes["epoch"] == 40


def test_a_day_of_mixed_sampling_keeps_every_epoch_at_the_finest_cadence(session):
    fine = _file(DAY_1, 0, 900, 1, file_hash="fine")
    coarse = _file(DAY_1, 900, 180, 5, file_hash="coarse")
    add_day_block(session, GROUP, DAY_1, 1, template=fine)
    write_file_region(session, GROUP, fine)
    write_file_region(session, GROUP, coarse)

    ds = load_group(session.store, GROUP, drop_empty=True)

    assert ds.sizes["epoch"] == 900 + 180
    np.testing.assert_array_equal(
        ds.SNR.sel(epoch=coarse.epoch).values, coarse.SNR.values
    )


def test_a_finer_file_into_a_coarser_day_is_refused(session):
    _write(session, _file(DAY_1, 0, 10, 5), 5)

    with pytest.raises(CadenceError, match="5 s"):
        add_day_block(session, GROUP, DAY_1, 1, template=_file(DAY_1, 0, 10, 1))


def test_two_epochs_in_one_slot_refuse_the_file(session):
    add_day_block(session, GROUP, DAY_1, 5, template=_file(DAY_1, 0, 10, 5))
    crowded = _file(DAY_1, 0, 10, 5, jitter_s=np.r_[0, -4.0, np.zeros(8)])

    with pytest.raises(SlotCollisionError, match="one slot"):
        write_file_region(session, GROUP, crowded)
    assert load_group(session.store, GROUP, drop_empty=True).sizes["epoch"] == 0


def test_writing_a_file_again_gives_no_duplicates(repo, session):
    first = _file(DAY_1, 0, 10, 5)
    _write(session, first, 5)
    session.commit("first")
    session = repo.writable_session("main")
    again = first.copy(deep=True)
    again["SNR"] = again.SNR + 1

    _write(session, again, 5)

    ds = load_group(session.store, GROUP, drop_empty=True)
    assert ds.sizes["epoch"] == 10
    np.testing.assert_array_equal(ds.SNR.values, again.SNR.values)


def test_a_block_grown_for_a_day_that_failed_is_reused(repo, session):
    template = _file(DAY_1, 0, 10, 5)
    add_day_block(session, GROUP, DAY_1, 5, template=template)
    session.commit("grown, then the day failed")
    session = repo.writable_session("main")

    block = add_day_block(session, GROUP, DAY_1, 5, template=template)

    assert block.start == 0
    assert load_group(session.store, GROUP).sizes["epoch"] == 17280


def test_an_empty_slot_reads_as_missing_never_zero(repo, session):
    _write(session, _file(DAY_1, 0, 10, 5), 5)
    session.commit("data")

    ds = load_group(repo.readonly_session("main").store, GROUP)

    empty = ds.isel(epoch=500)
    assert np.isnan(empty.SNR.values).all()
    # Integer variables keep their dtype and read their missing value.
    assert ds.LLI.dtype == np.int8
    assert (empty.LLI.values == -1).all()
    assert (ds.LLI.isel(epoch=0).values == 0).all()


@pytest.mark.parametrize(
    ("cadence_s", "slots", "padded"),
    [(7, 12343, 12420), (45, 1920, 1980), (900, 96, 180), (3600, 24, 180)],
)
def test_every_cadence_is_stored_in_a_block_padded_to_whole_chunks(
    session, cadence_s, slots, padded
):
    # 7 s does not even divide a day: its last slot is 23:59:54.
    ds_in = _file(DAY_1, 0, 10, cadence_s)

    _write(session, ds_in, cadence_s)

    block = day_blocks(session.store, GROUP)[DAY_1]
    assert (block.slots, block.stop - block.start) == (slots, padded)
    ds = load_group(session.store, GROUP)
    assert ds.sizes["epoch"] == slots
    assert bool(ds.indexes["epoch"].is_monotonic_increasing)
    assert ds.epoch.values[-1] == DAY_1.astype("M8[ns]") + np.timedelta64(
        (slots - 1) * cadence_s, "s"
    )
    kept = load_group(session.store, GROUP, drop_empty=True)
    np.testing.assert_array_equal(kept.epoch.values, ds_in.epoch.values)
    np.testing.assert_array_equal(kept.SNR.values, ds_in.SNR.values)


def test_padding_lies_between_the_last_slot_and_the_next_day(session):
    _write(session, _file(DAY_1, 0, 10, 900), 900)
    raw = zarr.open_group(session.store, mode="r", path=GROUP)

    times = np.asarray(raw["epoch"][96:180]).astype("M8[ns]")  # ty: ignore[invalid-argument-type]
    snr = np.asarray(raw["SNR"][96:180])  # ty: ignore[invalid-argument-type]

    assert np.all(np.diff(times.astype(np.int64)) > 0)
    assert times[0] > DAY_1.astype("M8[ns]") + np.timedelta64(95 * 900, "s")
    assert times[-1] < DAY_2.astype("M8[ns]")
    assert np.isnan(snr).all()


def test_days_of_different_cadences_share_a_group_in_any_order(session):
    days = [(DAY_2, 900), (DAY_1, 1), (np.datetime64("2025-01-03", "D"), 7)]
    files = [_file(day, 600, 20, cadence) for day, cadence in days]
    for (_, cadence), ds_in in zip(days, files, strict=True):
        _write(session, ds_in, cadence)

    blocks = day_blocks(session.store, GROUP)
    ds = load_group(session.store, GROUP, drop_empty=True)

    assert [blocks[day].cadence_s for day, _ in days] == [900, 1, 7]
    assert all((b.stop - b.start) % 180 == 0 for b in blocks.values())
    expected = xr.concat(files, dim="epoch").sortby("epoch")
    np.testing.assert_array_equal(ds.epoch.values, expected.epoch.values)
    np.testing.assert_array_equal(ds.SNR.values, expected.SNR.values)
    assert load_group(session.store, GROUP).sizes["epoch"] == 96 + 86400 + 12343


@pytest.mark.parametrize("cadence_s", [0, -5, 86401])
def test_a_cadence_no_day_can_hold_is_refused(session, cadence_s):
    with pytest.raises(CadenceError, match="no longer than one day"):
        add_day_block(session, GROUP, DAY_1, cadence_s, template=_file(DAY_1, 0, 10, 5))


def test_finding_the_blocks_reads_no_epochs(session, monkeypatch):
    # Reading the epoch axis reads every epoch chunk of the group; the block
    # index makes that unnecessary.
    from canvod.store import day_blocks as module

    _write(session, _file(DAY_1, 0, 10, 5), 5)
    original = module._epoch_array

    class _ShapeOnly:
        def __init__(self, array):
            self.shape = array.shape

        def __getitem__(self, key):
            raise AssertionError("the epoch axis was read")

    monkeypatch.setattr(
        module,
        "_epoch_array",
        lambda zgroup, group: _ShapeOnly(original(zgroup, group)),
    )

    assert set(day_blocks(session.store, GROUP)) == {DAY_1}


def test_a_day_block_group_without_its_block_index_is_refused(session):
    _write(session, _file(DAY_1, 0, 10, 5), 5)
    zgroup = zarr.open_group(session.store, mode="r+", path=GROUP)
    del zgroup.attrs["day_block_index"]

    with pytest.raises(LayoutError, match="no block index"):
        day_blocks(session.store, GROUP)


def test_stored_epochs_keep_their_real_times(session):
    jitter = np.r_[0.2, -0.3, np.zeros(8)]
    ds_in = _file(DAY_1, 0, 10, 5, jitter_s=jitter)
    _write(session, ds_in, 5)

    ds = load_group(session.store, GROUP)

    np.testing.assert_array_equal(ds.epoch.values[:10], ds_in.epoch.values)
    # An empty slot holds its grid time.
    assert ds.epoch.values[20] == DAY_1.astype("M8[ns]") + np.timedelta64(100, "s")


def test_drop_empty_keeps_only_slots_with_data(session):
    ds_in = _file(DAY_1, 3600, 10, 5)
    _write(session, ds_in, 5)

    ds = load_group(session.store, GROUP, drop_empty=True)

    np.testing.assert_array_equal(ds.epoch.values, ds_in.epoch.values)
    np.testing.assert_array_equal(ds.SNR.values, ds_in.SNR.values)


def test_a_file_region_reports_its_epochs_with_data(session):
    ds_in = _file(DAY_1, 3600, 10, 5)

    region = _write(session, ds_in, 5)

    assert region.epochs == 10
    assert region.start == ds_in.epoch.values[0]
    assert region.end == ds_in.epoch.values[-1]


def test_a_group_written_by_appending_takes_no_day_blocks(session):
    to_icechunk(_file(DAY_1, 0, 10, 5), session, group=GROUP)

    with pytest.raises(LayoutError, match="appending"):
        add_day_block(session, GROUP, DAY_1, 5, template=_file(DAY_1, 0, 10, 5))


def test_appending_to_a_day_block_group_is_refused(session):
    from canvod.store.prepare import prepare_write

    _write(session, _file(DAY_1, 0, 10, 5), 5)

    with pytest.raises(LayoutError, match="day blocks"):
        prepare_write(_file(DAY_2, 0, 10, 5), session.store, GROUP, append_dim="epoch")


def test_layout_and_cadence_errors_stop_a_run():
    # Not ValueErrors: per-file error handling must not skip past them.
    assert not issubclass(LayoutError, ValueError)
    assert not issubclass(CadenceError, ValueError)


def test_the_layout_stays_in_the_store(session):
    # Datasets read from a group do not carry the layout attribute, so it
    # cannot reach a group written from them (e.g. VOD written by appending).
    _write(session, _file(DAY_1, 0, 10, 5), 5)

    assert "epoch_layout" not in load_group(session.store, GROUP).attrs


def test_drop_empty_leaves_a_group_written_by_appending_as_it_is(session):
    ds = _file(DAY_1, 0, 10, 5)
    ds["SNR"][3] = np.nan
    to_icechunk(ds, session, group=GROUP)

    assert load_group(session.store, GROUP, drop_empty=True).sizes["epoch"] == 10


def test_a_file_with_other_variables_is_refused_as_a_write(session):
    _write(session, _file(DAY_1, 0, 10, 5), 5)
    other = _file(DAY_1, 50, 10, 5).drop_vars("LLI")

    with pytest.raises(GroupVariablesMismatchError, match="Cannot write to group"):
        write_file_region(session, GROUP, other)


def test_a_file_with_other_sids_is_refused_as_a_write(session):
    _write(session, _file(DAY_1, 0, 10, 5), 5)
    other = _file(DAY_1, 50, 10, 5).assign_coords(
        sid=["G01|L1|C", "G03|L1|C", "E01|E1|C"]
    )

    with pytest.raises(GroupCoordinatesMismatchError, match="the write would"):
        write_file_region(session, GROUP, other)


def test_an_existing_group_keeps_its_epoch_chunk(session):
    # Created with chunks of 90 epochs; the settings now say 180. A day at
    # 960 s has 90 slots: one chunk of 90, no padding.
    first = _file(DAY_1, 0, 10, 30)
    add_day_block(session, GROUP, DAY_1, 30, template=first, epoch_chunk=90)

    block = add_day_block(session, GROUP, DAY_2, 960, template=None, epoch_chunk=180)

    assert (block.slots, block.stop - block.start) == (90, 90)
    assert stored_epoch_chunk(session.store, GROUP) == 90


def test_a_block_is_padded_to_the_stored_chunks(session):
    # Created with chunks of 180 epochs; the settings now say 90. The 90
    # slots of a 960 s day are padded to one chunk of 180.
    first = _file(DAY_1, 0, 10, 30)
    add_day_block(session, GROUP, DAY_1, 30, template=first, epoch_chunk=180)

    block = add_day_block(session, GROUP, DAY_2, 960, template=None, epoch_chunk=90)

    assert (block.slots, block.stop - block.start) == (90, 180)


def test_a_new_group_takes_the_signal_chunks(session):
    first = _file(DAY_1, 0, 10, 30)
    add_day_block(session, GROUP, DAY_1, 30, template=first, dim_chunks={"sid": 2})

    snr = zarr.open_group(session.store, mode="r", path=GROUP)["SNR"]
    assert snr.chunks == (180, 2)


def test_signal_chunks_of_minus_one_are_one_chunk(session):
    first = _file(DAY_1, 0, 10, 30)
    add_day_block(
        session, GROUP, DAY_1, 30, template=first, dim_chunks={"epoch": 90, "sid": -1}
    )

    snr = zarr.open_group(session.store, mode="r", path=GROUP)["SNR"]
    # epoch_chunk sets the epoch chunks; dim_chunks only the other dimensions.
    assert snr.chunks == (180, len(SIDS))
