"""canvod.ops: Preprocessing operations pipeline for GNSS VOD data."""

from importlib.metadata import version as _version

__version__ = _version("canvod-ops")

from canvod.ops.base import Op, OpResult
from canvod.ops.files import preprocess_files
from canvod.ops.grid import GridAssignment, assign_grid_cells_in_store, grid_assign
from canvod.ops.pipeline import Pipeline, PipelineResult
from canvod.ops.registry import build_default_pipeline, planned_settings
from canvod.ops.temporal import TemporalAggregate, temporal_aggregate
