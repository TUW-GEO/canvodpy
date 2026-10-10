# canvod.grids API Reference

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

## Grid Core

::: canvod.grids.core.grid_builder
::: canvod.grids.core.grid_data
::: canvod.grids.core.grid_types

## Grid Builders

### Equal-Area Grid

::: canvod.grids.grids_impl.equal_area_grid

### Equal-Angle Grid

::: canvod.grids.grids_impl.equal_angle_grid

### Equirectangular Grid

::: canvod.grids.grids_impl.equirectangular_grid

### HEALPix Grid

::: canvod.grids.grids_impl.healpix_grid

### Geodesic Grid

::: canvod.grids.grids_impl.geodesic_grid

### Fibonacci Grid

::: canvod.grids.grids_impl.fibonacci_grid

### HTM Grid

::: canvod.grids.grids_impl.htm_grid

## Grid Operations

::: canvod.grids.operations

## Aggregation

::: canvod.grids.aggregation

## Analysis

### Filtering

::: canvod.grids.analysis.filtering

### Per-Cell Filtering

::: canvod.grids.analysis.per_cell_filtering

### Masking

::: canvod.grids.analysis.masking

### Weighting

::: canvod.grids.analysis.weighting

### Solar Geometry

::: canvod.grids.analysis.solar

### Temporal Analysis

::: canvod.grids.analysis.temporal

### Spatial Analysis

::: canvod.grids.analysis.spatial

### Per-Cell VOD Analysis

::: canvod.grids.analysis.per_cell_analysis
