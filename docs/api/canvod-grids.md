# `canvod.grids` API reference

Hemispheric grid implementations and spatial analysis tools.

## Package

::: canvod.grids
    options:
      members:
        - BaseGridBuilder
        - GridData
        - GridType
        - create_hemigrid
        - EqualAreaBuilder
        - EqualAngleBuilder
        - EquirectangularBuilder
        - HEALPixBuilder
        - GeodesicBuilder
        - FibonacciBuilder
        - HTMBuilder
        - CellAggregator

## Grid core

::: canvod.grids.core.grid_builder
::: canvod.grids.core.grid_data
::: canvod.grids.core.grid_types

## Grid builders

### Equal-area grid

::: canvod.grids.grids_impl.equal_area_grid

### Equal-angle grid

::: canvod.grids.grids_impl.equal_angle_grid

### Equirectangular grid

::: canvod.grids.grids_impl.equirectangular_grid

### HEALPix grid

::: canvod.grids.grids_impl.healpix_grid

### Geodesic grid

::: canvod.grids.grids_impl.geodesic_grid

### Fibonacci grid

::: canvod.grids.grids_impl.fibonacci_grid

### HTM grid

::: canvod.grids.grids_impl.htm_grid

## Grid operations

::: canvod.grids.operations

## Aggregation

::: canvod.grids.aggregation

## Analysis

### Filtering

::: canvod.grids.analysis.filtering

### Per-cell filtering

::: canvod.grids.analysis.per_cell_filtering

### Masking

::: canvod.grids.analysis.masking

### Weighting

::: canvod.grids.analysis.weighting

### Solar geometry

::: canvod.grids.analysis.solar

### Temporal analysis

::: canvod.grids.analysis.temporal

### Spatial analysis

::: canvod.grids.analysis.spatial

### Per-cell VOD analysis

::: canvod.grids.analysis.per_cell_analysis
