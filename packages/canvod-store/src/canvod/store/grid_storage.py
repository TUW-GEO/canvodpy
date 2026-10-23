"""Store hemisphere grids in an Icechunk store and read them back.

A grid is written to the ``grids/{grid_name}`` group of the store as an
xarray Dataset with the cell centers, vertices and solid angles
(``canvod.grids.grid_to_dataset``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import structlog
import xarray as xr
from canvod.grids import grid_to_dataset
from canvod.grids.core import GridData
from canvod.store_metadata.io import commit_with_rebase

if TYPE_CHECKING:
    from canvod.store.store import MyIcechunkStore

logger = structlog.get_logger(__name__)


def store_grid(
    grid: GridData,
    store: MyIcechunkStore,
    grid_name: str,
) -> str:
    """Store grid in unified xarray format to Icechunk store.

    Converts the grid to an xarray Dataset with vertex information
    and writes it to the ``grids/`` group in the store.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance to store.
    store : MyIcechunkStore
        Icechunk store to write to.
    grid_name : str
        Grid identifier for storage path (e.g., 'equal_area_4deg').

    Returns
    -------
    str
        Snapshot ID from the commit.

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.store import store_grid
    >>> grid = create_hemigrid(angular_resolution=4, grid_type='equal_area')
    >>> snapshot_id = store_grid(grid, my_store, 'equal_area_4deg')

    """
    # Convert to unified xarray format
    ds_grid = grid_to_dataset(grid)

    # Store in grids/ directory
    group_path = f"grids/{grid_name}"

    with store.writable_session() as session:
        from icechunk.xarray import to_icechunk

        to_icechunk(ds_grid, session, group=group_path, mode="w")
        snapshot_id = commit_with_rebase(
            session, f"Stored {grid_name} grid structure", store_path=store.store_path
        )

    logger.info(
        "grid_stored",
        group=group_path,
        snapshot=snapshot_id,
        ncells=grid.ncells,
        grid_type=grid.grid_type,
    )

    return snapshot_id


def load_grid(
    store: MyIcechunkStore,
    grid_name: str,
) -> GridData:
    """Load a grid from Icechunk store.

    Loads the grid structure from ``grids/{grid_name}`` and reconstructs
    a GridData object.

    Parameters
    ----------
    store : MyIcechunkStore
        Icechunk store to read from.
    grid_name : str
        Grid identifier (e.g., 'equal_area_4deg').

    Returns
    -------
    GridData
        Reconstructed grid instance.

    Examples
    --------
    >>> from canvod.store import load_grid
    >>> grid = load_grid(my_store, 'equal_area_4deg')
    >>> print(f"Loaded {grid.ncells} cells")

    """
    import polars as pl

    group_path = f"grids/{grid_name}"

    # Load from store
    with store.readonly_session() as session:
        ds_grid = xr.open_zarr(session.store, group=group_path, consolidated=False)

    # Extract metadata (support both old and new attr names)
    grid_type = ds_grid.attrs.get("grid_type")
    angular_resolution = ds_grid.attrs.get(
        "angular_resolution_deg",
        ds_grid.attrs.get("angular_resolution", 0.0),
    )
    cutoff_theta = ds_grid.attrs.get(
        "cutoff_theta_deg",
        ds_grid.attrs.get("cutoff_theta", 0.0),
    )

    if not grid_type:
        raise ValueError(f"Grid '{grid_name}' missing grid_type attribute")

    # Reconstruct grid DataFrame from cell centers
    cell_phi = ds_grid["cell_phi"].values
    cell_theta = ds_grid["cell_theta"].values
    n_cells = len(cell_phi)

    # Build basic grid DataFrame
    grid_data = {
        "cell_id": np.arange(n_cells),
        "phi": cell_phi,
        "theta": cell_theta,
    }

    # Add grid-type-specific columns
    if grid_type in ("equal_area", "equal_angle", "equirectangular"):
        # Reconstruct boundaries from vertices
        vertices_phi = ds_grid["vertices_phi"].values
        vertices_theta = ds_grid["vertices_theta"].values

        phi_min = vertices_phi[:, 0]  # All 4 vertices are corners
        phi_max = vertices_phi[:, 1]
        theta_min = vertices_theta[:, 0]
        theta_max = vertices_theta[:, 2]

        grid_data.update(
            {
                "phi_min": phi_min,
                "phi_max": phi_max,
                "theta_min": theta_min,
                "theta_max": theta_max,
            }
        )

    elif grid_type == "htm":
        # Reconstruct HTM vertices from spherical to Cartesian
        vertices_phi = ds_grid["vertices_phi"].values
        vertices_theta = ds_grid["vertices_theta"].values

        htm_v0 = []
        htm_v1 = []
        htm_v2 = []

        for i in range(n_cells):
            vertices = []
            for j in range(3):
                phi_v = vertices_phi[i, j]
                theta_v = vertices_theta[i, j]
                x = np.sin(theta_v) * np.cos(phi_v)
                y = np.sin(theta_v) * np.sin(phi_v)
                z = np.cos(theta_v)
                vertices.append([x, y, z])

            htm_v0.append(vertices[0])
            htm_v1.append(vertices[1])
            htm_v2.append(vertices[2])

        grid_data.update(
            {
                "htm_vertex_0": htm_v0,
                "htm_vertex_1": htm_v1,
                "htm_vertex_2": htm_v2,
            }
        )

    # Create Polars DataFrame
    df_grid = pl.DataFrame(grid_data)

    # Reconstruct theta_lims, phi_lims, and cell_ids from grid
    # These are required for GridData but not critical for basic usage
    unique_theta = sorted(df_grid["theta"].unique().to_list())
    theta_lims = np.array(unique_theta)

    # Group cells by theta bin
    phi_lims_list = []
    cell_ids_list = []
    for theta_val in unique_theta:
        theta_cells = df_grid.filter(pl.col("theta") == theta_val)
        phi_vals = sorted(theta_cells["phi"].to_list())
        cell_ids = theta_cells["cell_id"].to_list()

        phi_lims_list.append(np.array(phi_vals))
        cell_ids_list.append(np.array(cell_ids))

    # Create GridData instance
    grid = GridData(
        grid=df_grid,
        theta_lims=theta_lims,
        phi_lims=phi_lims_list,
        cell_ids=cell_ids_list,
        grid_type=grid_type,
        metadata={
            "angular_resolution": angular_resolution,
            "cutoff_theta": cutoff_theta,
            "phi_rotation": ds_grid.attrs.get("phi_rotation_deg", 0.0),
        },
    )

    logger.info(
        "grid_loaded",
        group=group_path,
        ncells=grid.ncells,
        grid_type=grid.grid_type,
    )

    return grid
