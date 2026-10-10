# canvod-grids

## Purpose

The `canvod-grids` package provides spatial grid implementations for hemispheric GNSS signal analysis. It discretizes the hemisphere visible from a ground-based receiver into cells, a prerequisite for spatially resolved VOD estimation.

---

## Grid types

Seven implementations are available, all inheriting from `BaseGridBuilder`:

<div class="grid cards" markdown>

-   :fontawesome-solid-border-all: &nbsp; **`EqualAreaBuilder`** *(recommended)*

    ---

    Cells of approximately equal solid angle. Ensures uniform spatial
    sampling across the hemisphere, avoiding zenith over-weighting.

-   :fontawesome-solid-table-cells: &nbsp; **`EqualAngleBuilder`**

    ---

    Regular angular spacing in $\theta$ and $\varphi$. Cells near zenith are smaller.
    Use it when you want uniform angular resolution.

-   :fontawesome-solid-grip: &nbsp; **`EquirectangularBuilder`**

    ---

    The same number of azimuth sectors in every $\theta$ band, no zenith cap.
    Fast to compute; cells shrink strongly toward the zenith.

-   :fontawesome-solid-dice-d20: &nbsp; **`GeodesicBuilder`**

    ---

    Icosahedron subdivision. Near-uniform cell area with triangular
    cell boundaries.

-   :fontawesome-solid-seedling: &nbsp; **`FibonacciBuilder`**

    ---

    Fibonacci-sphere sampling: nearly uniform points, each the center
    of its Voronoi cell.

-   :fontawesome-solid-globe: &nbsp; **`HEALPixBuilder`**

    ---

    Hierarchical Equal Area isoLatitude Pixelization. All pixels of the
    full sphere have the same area; the hemisphere keeps the pixels
    whose center is at least as high as the outer edge.
    Requires the optional `healpy` dependency, which is not installed by
    default (see [Optional dependencies](#optional-dependencies)
    below).

-   :fontawesome-solid-triangle-exclamation: &nbsp; **`HTMBuilder`**

    ---

    Hierarchical Triangular Mesh. Recursive triangular decomposition
    of the sphere; supports efficient spatial indexing.

</div>

All builders accept `angular_resolution` (degrees), `cutoff_theta` and
`phi_rotation` (degrees) and return a `GridData` object. `cutoff_theta`
(default 0) leaves out the sky within that many degrees of the horizon.
A run's grid assignment uses `cutoff_theta = 0`.

Where a grid ends depends on its type:

| Grid type | Outer edge | Observations near the horizon |
|---|---|---|
| `equal_area`, `equal_angle`, `equirectangular` | exactly $\theta = 90^\circ -$ `cutoff_theta`; the last band is narrower when the band width does not divide the range (half a band for `equal_area` and `equal_angle` at a cutoff that is a multiple of the resolution) | all get a cell up to the outer edge, none beyond |
| `htm`, `geodesic` | the triangles whose center is higher than the outer edge; some extend below it | all observations higher than the horizon get a cell (with `cutoff_theta = 0`) |
| `healpix` | the pixels whose center is at least as high as the outer edge; some extend below it | all observations higher than the horizon get a cell (with `cutoff_theta = 0`) |
| `fibonacci` | the Voronoi cells whose lattice point is higher than the outer edge | some low observations get no cell: up to about $1^\circ$, $3^\circ$ and $6^\circ$ elevation at $2^\circ$, $5^\circ$ and $10^\circ$ resolution |

So the solid angles of the ring grids add up to the hemisphere ($2\pi$ sr
with `cutoff_theta = 0`); those of the triangle and pixel grids add up to
somewhat more (geodesic $1.01 \times 2\pi$ to $1.05 \times 2\pi$, HEALPix $1.01 \times 2\pi$ to $1.08 \times 2\pi$ at
$2^\circ$ to $10^\circ$).

### Optional dependencies

!!! warning "HEALPix requires an explicit install"

    `HEALPixBuilder` delegates pixel geometry entirely to
    [`healpy`](https://healpy.readthedocs.io/), which is **not** installed
    by `uv sync --dev`, because it's declared in `canvod-grids`' own `optional`
    dependency group, not the workspace's `dev` group. Install it with:

    ```bash
    uv sync --dev --group optional
    ```

    `healpy` publishes no Windows wheels on PyPI (Linux and macOS only),
    which is the main reason it's kept optional rather than a hard
    dependency. Every other grid type only needs `numpy`/`scipy`, which
    install everywhere. Calling `create_hemigrid("healpix", ...)` without
    `healpy` installed raises `ImportError` with the same install
    instructions.

    CI installs the `optional` group on Linux/macOS runners so HEALPix is
    covered by `canvod-grids`' correctness suite
    (`test_grid_correctness_all_types.py`); it's skipped on the Windows
    CI leg for the same wheel-availability reason.

---

## Usage

=== "Factory function"

    ```python
    from canvod.grids import create_hemigrid

    grid = create_hemigrid("equal_area", angular_resolution=5.0)
    print(grid.ncells)  # 1051
    print(len(grid.theta_lims))  # 19 θ bands
    ```

=== "Builder pattern"

    ```python
    from canvod.grids import EqualAreaBuilder

    builder = EqualAreaBuilder(angular_resolution=5.0)
    grid = builder.build()
    ```

=== "canvodpy factory"

    ```python
    from canvodpy import GridFactory

    builder = GridFactory.create("equal_area", angular_resolution=5.0)
    grid = builder.build()
    print(grid.grid.head())  # Polars DataFrame with cell geometry
    ```

All three build the same grid. `create_hemigrid` and `GridFactory` take
the builder of each grid type from one table, `canvod.grids.GRID_BUILDERS`.

---

## `GridData`

The `GridData` object returned by all builders provides:

| Attribute | Type | Description |
| --------- | ---- | ----------- |
| `grid` | `polars.DataFrame` | One row per cell: center (`phi`, `theta`), bounds (`phi_min`, `phi_max`, `theta_min`, `theta_max`), `cell_id` |
| `ncells` | `int` | Total number of grid cells |
| `grid_type` | `str` | Grid type, for example `"equal_area"` |
| `theta_lims`, `phi_lims`, `cell_ids` | arrays | Band edges, azimuth edges and cell ids per $\theta$ band |
| `get_solid_angles()` | `np.ndarray` | Solid angle of each cell (sr) |
| `get_grid_stats()` | `dict` | Summary: cell count, solid-angle statistics |

For the Fibonacci, geodesic, HEALPix, and HTM grids the bounds are
bounding boxes, not the true (curved or triangular) cell boundaries.

---

## Grid operations

`canvod.grids.operations` handles the interface between grids and xarray Datasets:

<div class="grid cards" markdown>

-   :fontawesome-solid-map: &nbsp; **Cell Assignment**

    ---

    `add_cell_ids_to_ds_fast` assigns each observation to the cell that
    contains it, eagerly or lazily for Dask arrays: by band and sector
    edges for the ring grids, by spherical triangle for HTM and geodesic,
    by pixel for HEALPix, by Voronoi cell for Fibonacci. Observations
    outside the grid get NaN (see the table in [Grid types](#grid-types)). The nearest cell
    center is not used: near a cell's corner it often belongs to a
    neighboring cell. `canvodpy run` uses the same function when grid
    assignment is set. The lookup needs the grid's full geometry, so use
    a grid built with `create_hemigrid`; a grid read back with
    `canvod.store.load_grid` works for the ring grids only.

-   :fontawesome-solid-floppy-disk: &nbsp; **Grid Persistence**

    ---

    `grid_to_dataset` converts `GridData` to an xarray Dataset.

    To save a grid in a store and read it back, use `store_grid` and
    `load_grid` from [canvod-store](../store/overview.md#grids-and-analysis-results).

-   :fontawesome-solid-chart-pie: &nbsp; **Aggregation**

    ---

    In `canvod.grids.aggregation` (also importable from `canvod.grids`):

    `aggregate_data_to_grid` computes one statistic per cell.

    `compute_percell_timeseries` computes per-cell time series ($\text{cell} \times \text{time}$).

    `compute_hemisphere_percell` computes daily per-cell time series of
    the full hemisphere.

    `compute_zenith_percell` computes daily per-cell time series for
    $\theta \leq 30^\circ$.

</div>

---

## Analysis subpackage

`canvod.grids.analysis` provides filtering, weighting, and pattern analysis:

| Module | Purpose |
| ------ | ------- |
| `filtering` | Global IQR, Z-score, SID pattern filters |
| `per_cell_filtering` | Per-cell variants of the `filtering` filters |
| `masking` | Spatial and temporal mask construction |
| `weighting` | Per-cell weight calculators |
| `solar` | Solar geometry (elevation, azimuth) |
| `temporal` | Diurnal aggregation and analysis |
| `spatial` | Per-cell spatial statistics |

### SIDPatternFilter

`SIDPatternFilter` selects observations by GNSS system, frequency band, and tracking code.
It operates on the `sid` dimension where SIDs have the format `SV|Band|Code` (for example `G01|L1|C`).

=== "Slice (drop non-matching SIDs)"

    ```python
    from canvod.grids.analysis import SIDPatternFilter

    filt = SIDPatternFilter(system="G", band="L1", code="C")
    ds_gps_l1c = filt.filter_dataset(ds)  # returns smaller dataset or None
    ```

=== "Mask (NaN non-matching values)"

    ```python
    filt = SIDPatternFilter(system="E")
    ds_masked = filt.apply(ds, "SNR", output_suffix="galileo")
    ```

### Storing analysis results

To store weights, masks, statistics, and per-cell time series in a VOD
store, use `AnalysisStorage` from
[canvod-store](../store/overview.md#grids-and-analysis-results).

---

## Coordinate convention

!!! note "Angles"

    All grids use standard spherical coordinates:

    - **phi** ($\varphi$): azimuth from 0 to $2\pi$ · 0 = North · $\pi/2$ = East · clockwise
    - **theta** ($\theta$): polar angle from zenith · 0 = zenith · $\pi/2$ = horizon

    This matches the coordinate output of canvod-auxiliary, so no conversion is needed.

---

## Role in the VOD pipeline

```mermaid
flowchart TD
    A["`**Augmented Dataset**
    epoch x sid, with theta, phi`"]
    A --> B["`**Grid Assignment**
    add_cell_ids_to_ds_fast`"]
    B --> C["`**Gridded Dataset**
    + cell_id_* variable`"]
    C --> D["`**VOD per observation**
    tau-omega, carries cell_id_*`"]
    D --> F["`**Per-cell statistics**
    compute_hemisphere_percell`"]
    F --> E["`**Hemispherical Map**
    canvod-viz`"]
```
