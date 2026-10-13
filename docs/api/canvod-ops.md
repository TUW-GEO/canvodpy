# `canvod.ops` API reference

Configurable preprocessing pipeline for GNSS observation datasets.

## Pipeline

::: canvod.ops
    options:
      members:
        - Op
        - OpResult
        - Pipeline
        - PipelineResult
        - build_default_pipeline
        - preprocess_files

## Temporal

::: canvod.ops.temporal
    options:
      members:
        - TemporalAggregate
        - temporal_aggregate

## Grid

::: canvod.ops.grid
    options:
      members:
        - GridAssignment
        - grid_assign
