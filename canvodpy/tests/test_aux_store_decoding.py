"""The auxiliary store is read with its variables as stored.

``clock_offset`` is a float in seconds with CF ``units: seconds``. Decoded as
a timedelta it would be rounded to the nanosecond (30 cm of range), and its
gaps (NaN) would go through an int64 cast that xarray warns about.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import (
    _open_aux_store,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition

EPOCHS = np.array(
    ["2025-01-01T00:00:00", "2025-01-01T00:00:30", "2025-01-01T00:01:00"],
    dtype="datetime64[ns]",
)
SIDS = ["G01|L1|C", "G02|L1|C", "G03|L1|C"]
# Sub-nanosecond digits that a timedelta64[ns] would lose.
CLOCK = np.array(
    [
        [1.23456789012e-4, np.nan, -3.0000000004e-5],
        [1.23456789513e-4, np.nan, -3.0000000009e-5],
        [np.nan, 2.5e-6, -3.0000000013e-5],
    ]
)


@pytest.fixture
def aux_zarr(tmp_path: Path) -> Path:
    rng = np.random.default_rng(7)
    shape = (len(EPOCHS), len(SIDS))
    ds = xr.Dataset(
        {
            "X": (("epoch", "sid"), rng.uniform(1e7, 2e7, shape)),
            "Y": (("epoch", "sid"), rng.uniform(1e7, 2e7, shape)),
            "Z": (("epoch", "sid"), rng.uniform(1e7, 2e7, shape)),
            "clock_offset": (("epoch", "sid"), CLOCK, {"units": "seconds"}),
        },
        coords={"epoch": EPOCHS, "sid": SIDS},
    )
    path = tmp_path / "aux_2025001.zarr"
    ds.to_zarr(path, mode="w", consolidated=False)
    return path


def test_clock_offset_stays_seconds(aux_zarr: Path):
    aux = _open_aux_store(aux_zarr)

    assert aux["clock_offset"].dtype == np.float64
    np.testing.assert_array_equal(aux["clock_offset"].values, CLOCK)


class _FakeReader:
    file_hash = "deadbeef"
    source_format = "rinex3"

    def to_ds_and_auxiliary(self, **_kwargs):
        rng = np.random.default_rng(42)
        ds = xr.Dataset(
            {"SNR": (("epoch", "sid"), rng.uniform(30, 50, CLOCK.shape))},
            coords={
                "epoch": EPOCHS,
                "sid": SIDS,
                "sv": ("sid", [s.split("|")[0] for s in SIDS]),
            },
        )
        return ds, {}


def test_a_file_read_opens_the_aux_store_as_stored(aux_zarr: Path, tmp_path: Path):
    rnx_file = tmp_path / "REF001AUT_R_20250010000_01D_30S_MO.rnx"
    rnx_file.touch()
    opened: list[xr.Dataset] = []
    real_open_zarr = xr.open_zarr

    def recording_open_zarr(*args, **kwargs):
        ds = real_open_zarr(*args, **kwargs)
        opened.append(ds)
        return ds

    with (
        mock.patch(
            "canvodpy.factories.ReaderFactory.create", return_value=_FakeReader()
        ),
        mock.patch("xarray.open_zarr", side_effect=recording_open_zarr),
    ):
        preprocess_with_hermite_aux(
            rnx_file,
            None,
            aux_zarr,
            ECEFPosition(x=4_075_580.0, y=931_853.0, z=4_801_568.0),
            "reference",
        )

    assert len(opened) == 1
    assert opened[0]["clock_offset"].dtype == np.float64
