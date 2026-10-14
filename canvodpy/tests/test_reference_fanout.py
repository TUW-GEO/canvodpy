"""Bit-identical regression test for the §47 reference-receiver fan-out.

``preprocess_reference_with_hermite_aux_fanout`` reads+SID-filters a shared
reference file once, then computes geometry per canopy pairing. This must
produce byte-for-byte the same per-pairing datasets as calling the original
``preprocess_with_hermite_aux`` once per pairing (the old, redundant-parse
behavior) -- see dev/todo_later.md §47. Coordinate-transform code is
CLAUDE.md-guarded; this test is the required verification before wiring the
fan-out into ``prepare_batch_tasks``.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import (
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition

EPOCHS = np.array(
    ["2025-01-01T00:00:00", "2025-01-01T00:00:30", "2025-01-01T00:01:00"],
    dtype="datetime64[ns]",
)
SIDS = ["G01|L1|C", "G02|L1|C", "G03|L1|C"]


def _fake_rinex_ds() -> xr.Dataset:
    rng = np.random.default_rng(42)
    return xr.Dataset(
        {
            "S1C": (("epoch", "sid"), rng.uniform(30, 50, (len(EPOCHS), len(SIDS)))),
        },
        coords={"epoch": EPOCHS, "sid": SIDS},
    )


def _fake_aux_ds() -> xr.Dataset:
    rng = np.random.default_rng(7)
    n_e, n_s = len(EPOCHS), len(SIDS)
    # Roughly GPS-orbit-scale ECEF coordinates so the geometry math sees
    # realistic magnitudes rather than degenerate near-zero vectors.
    return xr.Dataset(
        {
            "X": (("epoch", "sid"), rng.uniform(1e7, 2e7, (n_e, n_s))),
            "Y": (("epoch", "sid"), rng.uniform(1e7, 2e7, (n_e, n_s))),
            "Z": (("epoch", "sid"), rng.uniform(1e7, 2e7, (n_e, n_s))),
            "clock": (("epoch", "sid"), rng.uniform(-1e-5, 1e-5, (n_e, n_s))),
        },
        coords={"epoch": EPOCHS, "sid": SIDS},
    )


class _FakeReader:
    file_hash = "deadbeef"
    source_format = "rinex3_stripped"

    def to_ds_and_auxiliary(self, **_kwargs):
        return _fake_rinex_ds(), {"sbf_obs": xr.Dataset()}


@pytest.fixture(autouse=True)
def _mock_io(tmp_path: Path):
    aux_zarr_path = tmp_path / "aux_hermite.zarr"
    aux_ds = _fake_aux_ds()

    with (
        mock.patch(
            "canvodpy.factories.ReaderFactory.create",
            return_value=_FakeReader(),
        ),
        mock.patch("xarray.open_zarr", return_value=aux_ds),
    ):
        yield aux_zarr_path


@pytest.fixture
def rnx_file(tmp_path: Path) -> Path:
    f = tmp_path / "REF001AUT_R_20250010000_01D_30S_MO.rnx"
    f.touch()
    return f


POSITION_A = ECEFPosition(x=4_075_580.0, y=931_853.0, z=4_801_568.0)
POSITION_B = ECEFPosition(x=4_075_600.0, y=931_900.0, z=4_801_500.0)


def test_fanout_matches_old_path_per_pairing(rnx_file: Path, tmp_path: Path):
    aux_zarr_path = tmp_path / "aux_hermite.zarr"

    _fname_a, ds_old_a, aux_old_a, sids_old_a = preprocess_with_hermite_aux(
        rnx_file,
        None,
        aux_zarr_path,
        POSITION_A,
        "reference",
    )
    _fname_b, ds_old_b, aux_old_b, sids_old_b = preprocess_with_hermite_aux(
        rnx_file,
        None,
        aux_zarr_path,
        POSITION_B,
        "reference",
    )

    _fname_new, ds_by_pairing, aux_new, sids_new = (
        preprocess_reference_with_hermite_aux_fanout(
            rnx_file,
            None,
            aux_zarr_path,
            {"reference_01_canopy_A": POSITION_A, "reference_01_canopy_B": POSITION_B},
            "reference",
        )
    )

    assert set(ds_by_pairing) == {"reference_01_canopy_A", "reference_01_canopy_B"}
    xr.testing.assert_identical(ds_by_pairing["reference_01_canopy_A"], ds_old_a)
    xr.testing.assert_identical(ds_by_pairing["reference_01_canopy_B"], ds_old_b)
    assert sids_new == sids_old_a == sids_old_b
    assert aux_new.keys() == aux_old_a.keys() == aux_old_b.keys()


def test_fanout_preserves_radial_distance_flag(rnx_file: Path, tmp_path: Path):
    aux_zarr_path = tmp_path / "aux_hermite.zarr"

    _fname_old, ds_old, _aux, _sids = preprocess_with_hermite_aux(
        rnx_file,
        None,
        aux_zarr_path,
        POSITION_A,
        "reference",
        store_radial_distance=True,
    )
    _fname_new, ds_by_pairing, _aux2, _sids2 = (
        preprocess_reference_with_hermite_aux_fanout(
            rnx_file,
            None,
            aux_zarr_path,
            {"reference_01_canopy_A": POSITION_A},
            "reference",
            store_radial_distance=True,
        )
    )

    assert "r" in ds_old
    xr.testing.assert_identical(ds_by_pairing["reference_01_canopy_A"], ds_old)


def test_fanout_single_pairing_is_a_degenerate_case(rnx_file: Path, tmp_path: Path):
    """A reference receiver paired with exactly one canopy is a valid input."""
    aux_zarr_path = tmp_path / "aux_hermite.zarr"

    _fname, ds_by_pairing, _aux, _sids = preprocess_reference_with_hermite_aux_fanout(
        rnx_file,
        None,
        aux_zarr_path,
        {"reference_01_canopy_A": POSITION_A},
        "reference",
    )

    assert list(ds_by_pairing) == ["reference_01_canopy_A"]


def test_each_dataset_names_the_format_of_its_reader(rnx_file: Path, tmp_path: Path):
    """The worker records the reader's own format, not the name it was given."""
    aux_zarr_path = tmp_path / "aux_hermite.zarr"

    _fname, ds_by_pairing, _aux, _sids = preprocess_reference_with_hermite_aux_fanout(
        rnx_file,
        None,
        aux_zarr_path,
        {"reference_01_canopy_A": POSITION_A, "reference_01_canopy_B": POSITION_B},
        "reference",
        reader_name="rinex3",
    )

    assert {ds.attrs["Source Format"] for ds in ds_by_pairing.values()} == {
        "rinex3_stripped"
    }
