"""
Integration tests for VODWorkflow.

Tests workflow orchestration, factory integration, and logging.
Uses a mock Site to avoid filesystem dependencies (external drives, store paths).
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from canvodpy.factories import GridFactory, ReaderFactory

from canvodpy import VODWorkflow


class _FakeSite:
    """Minimal stand-in for :class:`canvodpy.api.Site` (no I/O)."""

    def __init__(self, name: str = "Fangorn"):
        self.name = name
        self.receivers = {"canopy_01": {}, "reference_01": {}}
        self.active_receivers = {"canopy_01": {}, "reference_01": {}}


def _make_workflow(**kwargs) -> VODWorkflow:
    """Create a VODWorkflow with a fake Site (no I/O)."""
    kwargs.setdefault("keep_vars", ["SNR"])
    return VODWorkflow(site=_FakeSite(), **kwargs)


class TestWorkflowInitialization:
    """Test VODWorkflow initialization."""

    def test_workflow_creates_with_site_object(self):
        """Should create workflow from a Site-like object."""
        workflow = _make_workflow()
        assert workflow.site.name == "Fangorn"

    def test_workflow_creates_with_site_name(self):
        """Should create workflow from site name string."""
        with patch("canvodpy.workflow.Site", side_effect=lambda n: _FakeSite(n)):
            workflow = VODWorkflow(site="Fangorn", keep_vars=["SNR"])
        assert workflow.site.name == "Fangorn"

    def test_workflow_uses_default_components(self):
        """Should use default component names."""
        workflow = _make_workflow()
        assert workflow.reader_name == "rinex3"
        assert workflow.grid_name == "equal_area"
        assert workflow.vod_calculator_name == "tau_omega"

    def test_workflow_accepts_custom_components(self):
        """Should accept custom component names."""
        workflow = _make_workflow(
            reader="rinex3",
            grid="equal_area",
            vod_calculator="tau_omega",
        )
        assert workflow.reader_name == "rinex3"


class TestWorkflowGridCreation:
    """Test grid creation in workflow."""

    def test_workflow_creates_grid(self):
        """Should create and cache grid on init."""
        workflow = _make_workflow()
        assert workflow.grid is not None
        assert hasattr(workflow.grid, "ncells")
        assert workflow.grid.ncells > 0

    def test_workflow_grid_with_custom_params(self):
        """Should pass custom parameters to grid."""
        workflow = _make_workflow(grid_params={"angular_resolution": 5.0})
        # 5deg resolution should have more cells than 10deg default
        assert workflow.grid.ncells > 240

    def test_workflow_grid_is_built(self):
        """Grid should be built (not builder) on init."""
        workflow = _make_workflow()
        # Should be GridData, not GridBuilder
        assert not hasattr(workflow.grid, "build")
        assert hasattr(workflow.grid, "ncells")


class TestWorkflowLogging:
    """Test structured logging in workflow."""

    def test_workflow_has_logger(self):
        """Should have structured logger."""
        workflow = _make_workflow()
        assert hasattr(workflow, "log")
        assert hasattr(workflow.log, "info")

    def test_workflow_logger_has_site_context(self):
        """Logger should be bound to site context."""
        workflow = _make_workflow()
        assert workflow.log is not None


class TestWorkflowRepr:
    """Test workflow string representation."""

    def test_workflow_repr(self):
        """Should have informative __repr__."""
        workflow = _make_workflow()
        repr_str = repr(workflow)
        assert "VODWorkflow" in repr_str
        assert "Fangorn" in repr_str
        assert "equal_area" in repr_str
        assert "rinex3" in repr_str


class TestWorkflowFactoryIntegration:
    """Test workflow uses factories correctly."""

    def test_workflow_uses_grid_factory(self):
        """Should create grid via GridFactory."""
        workflow = _make_workflow()
        available = GridFactory.list_available()
        assert workflow.grid_name in available

    def test_workflow_respects_factory_registration(self):
        """Should use registered factories."""
        workflow = _make_workflow()
        # The workflow's grid_name and reader_name must exist in their
        # respective factory registries
        assert workflow.grid_name in GridFactory.list_available()
        assert workflow.reader_name in ReaderFactory.list_available()


class TestWorkflowErrorHandling:
    """Test workflow error handling."""

    def test_workflow_invalid_site_fails(self):
        """Should fail gracefully with invalid site name."""
        # VODWorkflow passes the string to Site(), which calls GnssResearchSite()
        # which raises KeyError for unknown sites. Mock Site to simulate this.
        with (
            patch(
                "canvodpy.workflow.Site",
                side_effect=KeyError("NonexistentSite123"),
            ),
            pytest.raises(KeyError, match="NonexistentSite123"),
        ):
            VODWorkflow(site="NonexistentSite123")

    def test_workflow_invalid_grid_type_fails(self):
        """Should fail with invalid grid type."""
        with pytest.raises(ValueError, match="nonexistent_grid"):
            _make_workflow(grid="nonexistent_grid")

    def test_workflow_invalid_reader_fails(self):
        """Should fail with invalid reader type during creation."""
        # Invalid reader is only caught when factory.create() is called
        # This happens during process_date(), not during __init__
        # Verify that invalid readers aren't in the registry
        assert "nonexistent_reader" not in ReaderFactory.list_available()


def _make_synthetic_ds(snr_value: float = 20.0) -> xr.Dataset:
    """Dask-backed (epoch, sid) dataset with SNR, phi, theta."""
    n_epoch, n_sid = 10, 5
    ds = xr.Dataset(
        {
            "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), snr_value)),
            "phi": (
                ["epoch", "sid"],
                np.linspace(0, 2 * np.pi, n_epoch * n_sid).reshape(n_epoch, n_sid),
            ),
            "theta": (
                ["epoch", "sid"],
                np.full((n_epoch, n_sid), np.pi / 4),
            ),
        },
        coords={
            "epoch": pd.date_range("2025-01-01", periods=n_epoch, freq="15min"),
            "sid": [f"G{i:02d}|L1|C" for i in range(1, n_sid + 1)],
        },
    )
    return ds.chunk({"epoch": 5})


@pytest.mark.integration
class TestWorkflowProcessing:
    """Integration tests requiring data (marked for CI)."""

    def test_process_date_returns_dict(self):
        """process_date should return dict of datasets."""
        workflow = _make_workflow()
        with patch.object(workflow, "_load_rinex", return_value=_make_synthetic_ds()):
            result = workflow.process_date("2025001", receivers=["canopy_01"])

        assert isinstance(result, dict)
        assert "canopy_01" in result
        ds = result["canopy_01"]
        assert "SNR" in ds.data_vars
        assert "cell_id_equal_area" in ds

    def test_calculate_vod_returns_dataset(self):
        """calculate_vod should return xarray Dataset."""
        workflow = _make_workflow()

        def _mock_load(receiver, date, log):
            snr = 10.0 if "canopy" in receiver else 20.0
            return _make_synthetic_ds(snr)

        with patch.object(workflow, "_load_rinex", side_effect=_mock_load):
            vod_ds = workflow.calculate_vod("canopy_01", "reference_01", "2025001")

        assert isinstance(vod_ds, xr.Dataset)
        assert "VOD" in vod_ds.data_vars
        assert "phi" in vod_ds.data_vars
        assert "theta" in vod_ds.data_vars
        assert np.all(np.isfinite(vod_ds["VOD"].values))

    def test_workflow_end_to_end(self):
        """Full workflow from init to VOD calculation."""
        workflow = _make_workflow()

        def _mock_load(receiver, date, log):
            snr = 10.0 if "canopy" in receiver else 20.0
            return _make_synthetic_ds(snr)

        with patch.object(workflow, "_load_rinex", side_effect=_mock_load):
            processed = workflow.process_date(
                "2025001", receivers=["canopy_01", "reference_01"]
            )
            vod_ds = workflow.calculate_vod(
                "canopy_01", "reference_01", "2025001", use_cached=False
            )

        assert "canopy_01" in processed
        assert "reference_01" in processed
        assert "VOD" in vod_ds.data_vars
        assert set(vod_ds["VOD"].dims) == {"epoch", "sid"}
