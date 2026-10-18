"""Reading part of a day-block group reads only the days it selects (#418).

The run reads each receiver-day back for VOD. Loading the whole group and
selecting the day afterwards costs time in proportion to the days already
stored; selecting the days' blocks first keeps it constant.
"""

from __future__ import annotations

import icechunk
import numpy as np
import pytest
import xarray as xr
from zarr.storage import WrapperStore

from canvod.store.day_blocks import (
    add_day_block,
    day_blocks,
    load_group,
    stored_epoch_chunk,
    write_file_region,
)

GROUP = "canopy_01"
SIDS = ["G01|L1|C", "G02|L1|C", "E01|E1|C"]
DAY_1 = np.datetime64("2025-01-01", "D")
DAY_2 = np.datetime64("2025-01-02", "D")
DAY_3 = np.datetime64("2025-01-03", "D")


def _file(day: np.datetime64, start_s: float, n: int, cadence_s: float) -> xr.Dataset:
    """A made-up file: ``n`` epochs from ``start_s`` seconds into ``day``."""
    offsets = start_s + np.arange(n) * cadence_s
    epochs = day.astype("M8[ns]") + (offsets * 1e9).astype("m8[ns]")
    snr = 30.0 + np.arange(n * len(SIDS), dtype="f4").reshape(n, len(SIDS))
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), snr),
            "LLI": (("epoch", "sid"), np.ones((n, len(SIDS)), dtype="i1")),
        },
        coords={
            "epoch": xr.Variable("epoch", epochs, {"time_system": "GPS"}),
            "sid": SIDS,
        },
        attrs={"File Hash": str(day)},
    )


class _ReadKeys(WrapperStore):
    """A store that records the key of every read."""

    def __init__(self, store, keys: list[str] | None = None) -> None:
        super().__init__(store)
        self.keys: list[str] = [] if keys is None else keys

    def _with_store(self, store):
        # Zarr reads through copies of the store; they record into one list.
        return type(self)(store, self.keys)

    async def get(self, key, prototype, byte_range=None):
        self.keys.append(key)
        return await self._store.get(key, prototype, byte_range)


@pytest.fixture
def session() -> icechunk.Session:
    repo = icechunk.Repository.create(icechunk.in_memory_storage())
    session = repo.writable_session("main")
    # Days written out of order, the middle one at another cadence.
    for day, start_s, n, cadence_s in [
        (DAY_3, 0, 40, 5),
        (DAY_1, 3600, 40, 5),
        (DAY_2, 86_000, 30, 10),
    ]:
        ds = _file(day, start_s, n, cadence_s)
        add_day_block(session, GROUP, day, cadence_s, template=ds)
        write_file_region(session, GROUP, ds)
    return session


def _epoch_chunks_read(keys: list[str], variable: str) -> set[int]:
    prefix = f"{GROUP}/{variable}/c/"
    return {
        int(key[len(prefix) :].split("/")[0]) for key in keys if key.startswith(prefix)
    }


def test_reading_a_day_reads_only_its_chunks(session):
    blocks = day_blocks(session.store, GROUP)
    chunk = stored_epoch_chunk(session.store, GROUP)
    # DAY_1 was written second: its block lies between the other two.
    block = blocks[DAY_1]
    own = set(range(block.start // chunk, (block.stop - 1) // chunk + 1))
    last = (max(b.stop for b in blocks.values()) - 1) // chunk
    store = _ReadKeys(session.store)

    ds = load_group(store, GROUP, time_slice=slice("2025-01-01", "2025-01-01"))
    ds.load()

    assert ds.sizes["epoch"] == block.slots
    for variable in ("SNR", "LLI"):
        read = _epoch_chunks_read(store.keys, variable)
        assert read, variable
        assert read <= own, variable
    # Decoding the times reads the first and the last epoch of the axis.
    assert _epoch_chunks_read(store.keys, "epoch") <= own | {0, last}


@pytest.mark.parametrize(
    "time_slice",
    [
        slice("2025-01-02", "2025-01-02"),  # one day, as a date string
        slice(
            np.datetime64("2025-01-02T00:00", "ns"),
            np.datetime64("2025-01-03T00:00", "ns") - np.timedelta64(1, "ns"),
        ),  # one day, as the run gives it
        slice("2025-01-01T18:00", "2025-01-02T06:00"),  # across midnight
        slice("2025-01-02T03:00", "2025-01-02T04:00"),  # inside one day
        slice("2025-01-02", None),  # open end
        slice(None, "2025-01-01T12:00"),  # open start
        slice("2025-01", "2025-01"),  # a month, as a partial string
        slice("2024-12-30", "2024-12-31"),  # no day stored
    ],
)
def test_a_selection_reads_the_same_as_selecting_from_the_whole_group(
    session, time_slice
):
    expected = load_group(session.store, GROUP).sel(epoch=time_slice).compute()

    got = load_group(session.store, GROUP, time_slice=time_slice).compute()

    xr.testing.assert_identical(got, expected)
    assert got["LLI"].dtype == np.dtype("i1")
    # The indexes a plain open gives, so selecting by label works as usual.
    plain = xr.open_zarr(session.store, group=GROUP, consolidated=False)
    assert set(got.xindexes) == set(plain.xindexes) == {"epoch", "sid"}
