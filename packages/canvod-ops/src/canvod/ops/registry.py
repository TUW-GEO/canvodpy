"""Pipeline construction from configuration."""

from __future__ import annotations

from canvod.config.models import PreprocessingConfig
from canvod.ops.grid import GridAssignment
from canvod.ops.pipeline import Pipeline
from canvod.ops.temporal import TemporalAggregate


def build_default_pipeline(
    config: PreprocessingConfig | None = None,
) -> Pipeline:
    """Build the pipeline that ``processing.preprocessing`` describes.

    Temporal aggregation runs first, then the grid cell assignment; each
    only if its section is set and enabled.

    Parameters
    ----------
    config : PreprocessingConfig | None
        Explicit config. If ``None``, reads ``processing.preprocessing`` via
        ``load_config()``; an unset section gives an empty pipeline.

    Returns
    -------
    Pipeline
        Ready-to-call pipeline (empty if nothing is set).
    """
    if config is None:
        from canvod.config import load_config

        config = load_config().processing.preprocessing

    pipeline = Pipeline()
    if config is None:
        return pipeline

    temporal = config.temporal_aggregation
    if temporal is not None and temporal.enabled:
        pipeline.add(
            TemporalAggregate(
                freq=temporal.freq,
                method=temporal.method,
                integer_method=temporal.integer_method,
            )
        )

    grid = config.grid_assignment
    if grid is not None and grid.enabled:
        pipeline.add(
            GridAssignment(
                grid_type=grid.grid_type,
                angular_resolution=grid.angular_resolution,
            )
        )

    return pipeline
