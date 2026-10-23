"""Tests for the preprocessing pipeline."""

import xarray as xr

from canvod.config.models import (
    GridAssignmentConfig,
    PreprocessingConfig,
    TemporalAggregationConfig,
)
from canvod.ops.base import Op, OpResult
from canvod.ops.pipeline import Pipeline, PipelineResult
from canvod.ops.registry import build_default_pipeline
from canvod.ops.temporal import TemporalAggregate


class _NoOp(Op):
    """Trivial op for testing."""

    @property
    def name(self) -> str:
        return "noop"

    @property
    def settings(self) -> dict:
        return {}

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]:
        return ds, OpResult(
            op_name=self.name,
            parameters={},
            input_shape=dict(ds.sizes),
            output_shape=dict(ds.sizes),
            duration_seconds=0.0,
        )


class TestPipeline:
    def test_empty_pipeline(self, sample_ds: xr.Dataset):
        """Empty pipeline should pass dataset through unchanged."""
        pipe = Pipeline()
        out, pr = pipe(sample_ds)

        xr.testing.assert_identical(out, sample_ds)
        assert len(pr.results) == 0

    def test_single_op(self, sample_ds: xr.Dataset):
        """Pipeline with one op should produce one result."""
        pipe = Pipeline([_NoOp()])
        out, pr = pipe(sample_ds)

        assert len(pr.results) == 1
        assert pr.results[0].op_name == "noop"

    def test_chained_ops(self, sample_ds: xr.Dataset):
        """Pipeline.add() should chain ops."""
        pipe = Pipeline()
        pipe.add(_NoOp()).add(_NoOp())
        _, pr = pipe(sample_ds)

        assert len(pr.results) == 2

    def test_total_duration(self, sample_ds: xr.Dataset):
        """PipelineResult should track total wall time."""
        pipe = Pipeline([_NoOp()])
        _, pr = pipe(sample_ds)

        assert pr.total_duration_seconds >= 0


class TestPipelineResult:
    def test_to_metadata_dict(self):
        """to_metadata_dict should produce the expected structure."""
        r = OpResult(
            op_name="test",
            parameters={"a": 1},
            input_shape={"epoch": 100},
            output_shape={"epoch": 50},
            duration_seconds=0.5,
        )
        pr = PipelineResult(results=[r], total_duration_seconds=0.5)
        d = pr.to_metadata_dict()

        assert "preprocessing_ops" in d
        assert len(d["preprocessing_ops"]) == 1
        assert d["preprocessing_ops"][0]["op_name"] == "test"
        assert d["preprocessing_total_seconds"] == 0.5


TEMPORAL = {"freq": "1min", "method": "mean", "integer_method": "first"}
GRID = {"grid_type": "equal_area", "angular_resolution": 2.0}


class TestBuildDefaultPipeline:
    def test_nothing_set_is_empty(self):
        """No operation runs unless its section is set."""
        assert len(build_default_pipeline(PreprocessingConfig())) == 0

    def test_both_set(self):
        """Temporal aggregation runs first, then the grid assignment."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(**TEMPORAL),
            grid_assignment=GridAssignmentConfig(**GRID),
        )
        pipe = build_default_pipeline(config)
        assert [op.name for op in pipe._ops] == ["temporal_aggregate", "grid_assign"]

    def test_disabled_temporal(self):
        """A set but disabled section is skipped."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(**TEMPORAL, enabled=False),
            grid_assignment=GridAssignmentConfig(**GRID),
        )
        pipe = build_default_pipeline(config)
        assert [op.name for op in pipe._ops] == ["grid_assign"]

    def test_only_temporal_set(self):
        """Setting only the aggregation does not add a grid assignment."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(**TEMPORAL)
        )
        pipe = build_default_pipeline(config)
        assert [op.name for op in pipe._ops] == ["temporal_aggregate"]

    def test_custom_freq(self):
        """Custom freq from config should propagate to the op."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(
                freq="5min", method="mean", integer_method="first"
            ),
        )
        pipe = build_default_pipeline(config)
        temporal_op = pipe._ops[0]
        assert isinstance(temporal_op, TemporalAggregate)
        assert temporal_op._freq == "5min"
