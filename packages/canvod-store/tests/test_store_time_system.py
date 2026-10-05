"""Every stored epoch is GPS time; groups of another or unknown scale are refused."""

import numpy as np
import pytest
import xarray as xr
from zarr.storage import MemoryStore

from canvod.store.prepare import EpochTimeSystemError, prepare_write

GROUP = "canopy_01"


def _ds(start: str, time_system: str | None) -> xr.Dataset:
    epochs = np.datetime64(start, "ns") + np.arange(3) * np.timedelta64(5, "s")
    attrs = {} if time_system is None else {"time_system": time_system}
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((3, 1), 40.0, dtype=np.float32))},
        coords={"epoch": ("epoch", epochs, attrs), "sid": ["G01|L1|C"]},
    )


def _write(ds: xr.Dataset, store: MemoryStore, *, append: bool) -> None:
    out = prepare_write(ds, store, GROUP, append_dim="epoch" if append else None)
    kwargs = {"append_dim": "epoch"} if append else {"mode": "w"}
    out.to_zarr(store, group=GROUP, consolidated=False, **kwargs)


def test_gps_time_is_written_and_appended():
    store = MemoryStore()
    _write(_ds("2025-01-01T00:00", "GPS"), store, append=False)
    _write(_ds("2025-01-01T00:01", "GPS"), store, append=True)
    back = xr.open_zarr(store, group=GROUP, consolidated=False)
    assert back.sizes["epoch"] == 6
    assert back["epoch"].attrs["time_system"] == "GPS"


@pytest.mark.parametrize("time_system", [None, "UTC"])
def test_epochs_not_in_gps_time_are_refused(time_system):
    with pytest.raises(EpochTimeSystemError, match="every stored epoch is GPS"):
        _write(_ds("2025-01-01T00:00", time_system), MemoryStore(), append=False)


@pytest.mark.parametrize(
    ("stored", "match"),
    [(None, "does not record its time scale"), ("UTC", "is in time system 'UTC'")],
)
def test_group_not_in_gps_time_is_refused(stored, match):
    store = MemoryStore()
    # A group as written before every epoch was GPS time
    _ds("2025-01-01T00:00", stored).to_zarr(
        store, group=GROUP, mode="w", consolidated=False
    )
    with pytest.raises(EpochTimeSystemError, match=match):
        _write(_ds("2025-01-01T00:01", "GPS"), store, append=True)


def test_refusal_is_not_a_value_error():
    assert not issubclass(EpochTimeSystemError, ValueError)
