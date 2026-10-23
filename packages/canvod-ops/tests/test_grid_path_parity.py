"""Parity of every cell-assignment entry point on the same points.

``add_cell_ids_to_ds_fast`` (eager and dask), the ``GridAssignment`` op
(used by the runs) and the deprecated ``add_cell_ids_to_vod_fast`` and
``add_cell_ids_to_vod`` must assign the same cell, as float64, to every
observation, for every grid type, whether ``phi``/``theta`` are data
variables (as written by ``add_spherical_coords_to_dataset``) or
coordinates.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from canvod.grids import create_hemigrid
from canvod.grids.operations import (
    add_cell_ids_to_ds_fast,
    add_cell_ids_to_vod,
    add_cell_ids_to_vod_fast,
)
from canvod.ops.grid import GridAssignment

GRID_TYPES = [
    "equal_area",
    "equal_angle",
    "rectangular",
    "equirectangular",
    "HTM",
    "geodesic",
    "healpix",
    "fibonacci",
]
RES = 10.0


def _points() -> tuple[np.ndarray, np.ndarray]:
    """Random hemisphere points plus edge cases, shaped (epoch, sid)."""
    rng = np.random.default_rng(0)
    n = 40 * 25
    phi = rng.uniform(0, 2 * np.pi, n)
    theta = np.arccos(rng.uniform(0, 1, n))  # uniform on the hemisphere
    edges_phi = [0.0, 2 * np.pi, np.pi, 0.0, 1.0, np.nan, 1.0, np.nan]
    edges_theta = [0.0, np.pi / 2, np.pi / 2, 1e-9, np.nan, 0.5, 0.0, np.nan]
    phi[: len(edges_phi)] = edges_phi
    theta[: len(edges_theta)] = edges_theta
    return phi.reshape(40, 25), theta.reshape(40, 25)


def _dataset(as_coords: bool) -> xr.Dataset:
    phi, theta = _points()
    ds = xr.Dataset(
        {"VOD": (("epoch", "sid"), np.ones_like(phi))},
        coords={
            "epoch": np.arange(phi.shape[0]),
            "sid": [f"s{i}" for i in range(phi.shape[1])],
        },
    )
    ds = ds.assign(phi=(("epoch", "sid"), phi), theta=(("epoch", "sid"), theta))
    return ds.set_coords(["phi", "theta"]) if as_coords else ds


@pytest.mark.parametrize("as_coords", [False, True], ids=["data_vars", "coords"])
@pytest.mark.parametrize("grid_type", GRID_TYPES)
def test_cell_assignment_paths_agree(grid_type, as_coords):
    if grid_type == "healpix":
        pytest.importorskip("healpy")
    grid = create_hemigrid(grid_type, angular_resolution=RES)
    name = f"{grid_type}_{RES}deg"
    var = f"cell_id_{name}"

    with pytest.warns(FutureWarning):
        vod_fast = add_cell_ids_to_vod_fast(_dataset(as_coords), grid, name)[var]
    with pytest.warns(FutureWarning):
        vod = add_cell_ids_to_vod(_dataset(as_coords), grid, name)[var]
    results = {
        "ds_fast_eager": add_cell_ids_to_ds_fast(_dataset(as_coords), grid, name)[var],
        "ds_fast_dask": add_cell_ids_to_ds_fast(
            _dataset(as_coords).chunk({"epoch": 7}), grid, name
        )[var].compute(),
        "vod_fast": vod_fast,
        "vod_elementwise": vod,
    }
    problems = []
    op = GridAssignment(grid_type=grid_type, angular_resolution=RES)
    op._grid = grid  # same grid instance as the other paths
    out, result = op(_dataset(as_coords))
    if var in out:
        results["ops_GridAssignment"] = out[var]
    else:
        problems.append(f"ops_GridAssignment: {result.notes}")

    ref = results.pop("ds_fast_eager")
    assert ref.dtype == np.float64
    assert np.isfinite(ref.values).sum() > 0
    for label, arr in results.items():
        vals = arr.values.astype(np.float64)
        if not np.array_equal(vals, ref.values, equal_nan=True):
            n = int(
                (
                    ~((vals == ref.values) | (np.isnan(vals) & np.isnan(ref.values)))
                ).sum()
            )
            problems.append(f"{label}: {n} cell ids differ")
        if arr.dtype != ref.dtype:
            problems.append(f"{label}: dtype {arr.dtype} != {ref.dtype}")
    assert not problems, "; ".join(problems)
