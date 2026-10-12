"""
Public API tests — validates the three-tier API surface.

Tests the Site, Pipeline, and process_date public API along with
convenience functions, exports, configuration, and subpackage access.
"""

from unittest.mock import MagicMock, patch

import canvodpy.orchestrator.processor  # noqa: F401  # Force-import so module-level load_config binds before patches
import pytest


class TestSiteAPI:
    """Test Site class."""

    def test_site_import(self):
        """Should be able to import Site."""
        from canvodpy import Site

        assert Site is not None

    def test_site_creation(self):
        """Should create Site with name."""
        from canvodpy import Site

        mock_gnss_site = MagicMock()
        mock_gnss_site.receivers = {"canopy_01": {}}
        mock_gnss_site.active_receivers = {"canopy_01": {}}
        mock_gnss_site.active_vod_analyses = {}

        with patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site):
            site = Site("Fangorn")
            assert site.name == "Fangorn"

    def test_site_has_receivers(self):
        """Site should have receivers property."""
        from canvodpy import Site

        mock_gnss_site = MagicMock()
        mock_gnss_site.receivers = {"canopy_01": {"active": True}}

        with patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site):
            site = Site("Fangorn")
            assert hasattr(site, "receivers")
            assert isinstance(site.receivers, dict)

    def test_site_has_active_receivers(self):
        """Site should have active_receivers property."""
        from canvodpy import Site

        mock_gnss_site = MagicMock()
        mock_gnss_site.active_receivers = {"canopy_01": {"active": True}}

        with patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site):
            site = Site("Fangorn")
            assert hasattr(site, "active_receivers")


class TestPipelineAPI:
    """Test Pipeline class."""

    def test_pipeline_import(self):
        """Should be able to import Pipeline."""
        from canvodpy import Pipeline

        assert Pipeline is not None

    def test_pipeline_creation_from_site(self):
        """Should create Pipeline from Site."""
        from canvodpy import Pipeline, Site

        mock_gnss_site = MagicMock()
        mock_gnss_site.receivers = {"canopy_01": {}}
        mock_gnss_site.active_receivers = {"canopy_01": {}}
        mock_gnss_site.active_vod_analyses = {}

        with (
            patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site),
            patch("canvod.config.load_config") as mock_config,
            patch("canvodpy.orchestrator.PipelineOrchestrator"),
        ):
            # Set up config mock
            mock_proc = MagicMock()
            mock_proc.keep_gnss_observables = ["SNR"]
            mock_proc.days_per_batch = 1
            mock_proc.resolve_resources.return_value = {
                "n_workers": 2,
                "max_memory_gb": 8.0,
                "cpu_affinity": None,
                "nice_priority": 0,
                "threads_per_worker": 1,
            }
            mock_config.return_value.processing.params = mock_proc
            mock_config.return_value.processing.aux_data.agency = "COD"

            site = Site("Fangorn")
            pipeline = Pipeline(site)
            assert pipeline.site.name == "Fangorn"

    def test_pipeline_creation_from_string(self):
        """Should create Pipeline from site name."""
        from canvodpy import Pipeline

        mock_gnss_site = MagicMock()

        with (
            patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site),
            patch("canvod.config.load_config") as mock_config,
            patch("canvodpy.orchestrator.PipelineOrchestrator"),
        ):
            mock_proc = MagicMock()
            mock_proc.keep_gnss_observables = ["SNR"]
            mock_proc.days_per_batch = 1
            mock_proc.resolve_resources.return_value = {
                "n_workers": 2,
                "max_memory_gb": 8.0,
                "cpu_affinity": None,
                "nice_priority": 0,
                "threads_per_worker": 1,
            }
            mock_config.return_value.processing.params = mock_proc
            mock_config.return_value.processing.aux_data.agency = "COD"

            pipeline = Pipeline("Fangorn")
            assert pipeline.site.name == "Fangorn"

    def test_pipeline_has_process_date(self):
        """Pipeline should have process_date method."""
        from canvodpy import Pipeline

        mock_gnss_site = MagicMock()

        with (
            patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site),
            patch("canvod.config.load_config") as mock_config,
            patch("canvodpy.orchestrator.PipelineOrchestrator"),
        ):
            mock_proc = MagicMock()
            mock_proc.keep_gnss_observables = ["SNR"]
            mock_proc.days_per_batch = 1
            mock_proc.resolve_resources.return_value = {
                "n_workers": 2,
                "max_memory_gb": 8.0,
                "cpu_affinity": None,
                "nice_priority": 0,
                "threads_per_worker": 1,
            }
            mock_config.return_value.processing.params = mock_proc
            mock_config.return_value.processing.aux_data.agency = "COD"

            pipeline = Pipeline("Fangorn")
            assert hasattr(pipeline, "process_date")
            assert callable(pipeline.process_date)


class TestNoEffectResourceArguments:
    """The resource arguments that have no effect are deprecated."""

    @pytest.fixture
    def mocked_pipeline_setup(self):
        mock_gnss_site = MagicMock()
        with (
            patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site),
            patch("canvod.config.load_config") as mock_config,
            patch("canvodpy.orchestrator.PipelineOrchestrator") as mock_orch,
        ):
            mock_proc = MagicMock()
            mock_proc.keep_gnss_observables = ["SNR"]
            mock_proc.days_per_batch = 1
            mock_proc.resolve_resources.return_value = {
                "n_workers": 2,
                "threads_per_worker": 1,
            }
            mock_config.return_value.processing.params = mock_proc
            mock_config.return_value.processing.aux_data.agency = "COD"
            yield mock_orch

    @pytest.mark.parametrize(
        ("name", "value"),
        [("max_memory_gb", 16.0), ("cpu_affinity", [0, 1]), ("nice_priority", 10)],
    )
    def test_pipeline_argument_warns(self, mocked_pipeline_setup, name, value):
        from canvodpy import Pipeline

        with pytest.warns(FutureWarning, match=rf"'{name}' argument of Pipeline\(\)"):
            Pipeline("Fangorn", **{name: value})
        kwargs = mocked_pipeline_setup.call_args.kwargs
        assert name not in kwargs

    @pytest.mark.parametrize(
        ("name", "value"),
        [("max_memory_gb", 16.0), ("cpu_affinity", [0, 1]), ("nice_priority", 10)],
    )
    def test_site_pipeline_argument_warns_once(
        self, mocked_pipeline_setup, name, value
    ):
        import warnings

        from canvodpy import Site

        site = Site("Fangorn")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            site.pipeline(**{name: value})
        messages = [
            str(w.message) for w in caught if issubclass(w.category, FutureWarning)
        ]
        assert len(messages) == 1
        assert f"'{name}' argument of Site.pipeline()" in messages[0]

    def test_pipeline_without_them_does_not_warn(self, mocked_pipeline_setup):
        import warnings

        from canvodpy import Pipeline

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            Pipeline("Fangorn", n_workers=2)

    def test_orchestrator_argument_warns(self):
        from canvodpy.orchestrator.pipeline import PipelineOrchestrator

        site = MagicMock()
        with (
            patch("canvodpy.orchestrator.pipeline.ensure_file_logging"),
            patch("canvodpy.orchestrator.pipeline.clear_discovery_cache"),
            patch("canvodpy.orchestrator.pipeline.check_receivers"),
            pytest.warns(
                FutureWarning,
                match=r"'nice_priority' argument of PipelineOrchestrator\(\)",
            ),
        ):
            PipelineOrchestrator(site, nice_priority=10).close()


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_process_date_import(self):
        """Should import process_date function."""
        from canvodpy import process_date

        assert process_date is not None
        assert callable(process_date)

    def test_calculate_vod_import(self):
        """Should import calculate_vod function."""
        from canvodpy import calculate_vod

        assert calculate_vod is not None
        assert callable(calculate_vod)

    def test_preview_processing_import(self):
        """Should import preview_processing function."""
        from canvodpy import preview_processing

        assert preview_processing is not None
        assert callable(preview_processing)


class TestDeprecatedVodForDay:
    """Pipeline.calculate_vod and canvodpy.calculate_vod delegate to site.vod."""

    @staticmethod
    def _site():
        from types import SimpleNamespace

        site = MagicMock()
        site.vod_analyses = {
            "canopy_01_vs_reference_01": SimpleNamespace(
                canopy_receiver="canopy_01", reference_receiver="reference_01"
            )
        }
        return site

    def test_pipeline_calculate_vod_delegates_to_compute_bulk(self):
        from datetime import datetime
        from types import SimpleNamespace

        from canvodpy import Pipeline

        site = self._site()
        with pytest.warns(FutureWarning, match="Site\\(<site>\\).vod.compute_bulk"):
            result = Pipeline.calculate_vod(
                SimpleNamespace(site=site), "canopy_01", "reference_01", "2025001"
            )

        site.vod.compute_bulk.assert_called_once()
        args, kwargs = site.vod.compute_bulk.call_args
        assert args == ("canopy_01_vs_reference_01",)
        assert kwargs["start"] == datetime(2025, 1, 1)
        assert kwargs["end"] == datetime(2025, 1, 1, 23, 59, 59, 999999)
        assert kwargs["write"] is True
        assert result is site.vod.compute_bulk.return_value

    def test_unconfigured_pair_raises(self):
        from types import SimpleNamespace

        from canvodpy import Pipeline

        site = self._site()
        with (
            pytest.warns(FutureWarning),
            pytest.raises(ValueError, match="No VOD analysis configured"),
        ):
            Pipeline.calculate_vod(
                SimpleNamespace(site=site), "canopy_01", "reference_02", "2025001"
            )
        site.vod.compute_bulk.assert_not_called()

    def test_top_level_calculate_vod_delegates(self):
        import canvodpy

        site = self._site()
        with (
            patch("canvodpy.api.Site", return_value=site),
            pytest.warns(FutureWarning) as record,
        ):
            canvodpy.calculate_vod(
                "Fangorn", "canopy_01", "reference_01", "2025001", write_to_store=False
            )

        assert len(record) == 1
        assert site.vod.compute_bulk.call_args.kwargs["write"] is False


class TestAPICoexistence:
    """Test that all API tiers can coexist."""

    def test_both_site_and_workflow_importable(self):
        """Should import both Site and VODWorkflow."""
        from canvodpy import Site, VODWorkflow

        assert Site is not None
        assert VODWorkflow is not None

    def test_both_apis_work_together(self):
        """Should use both APIs in same code."""
        from canvodpy import Site, VODWorkflow

        mock_gnss_site = MagicMock()
        mock_gnss_site.receivers = {"canopy_01": {}}
        mock_gnss_site.active_receivers = {"canopy_01": {}}
        mock_gnss_site.active_vod_analyses = {}

        with patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site):
            site = Site("Fangorn")
            workflow = VODWorkflow(site=site, keep_vars=["SNR"])
            assert site.name == workflow.site.name

    def test_pipeline_uses_factories(self):
        """Pipeline should use factory components."""
        from canvodpy import Pipeline

        mock_gnss_site = MagicMock()

        with (
            patch("canvod.store.GnssResearchSite", return_value=mock_gnss_site),
            patch("canvod.config.load_config") as mock_config,
            patch("canvodpy.orchestrator.PipelineOrchestrator"),
        ):
            mock_proc = MagicMock()
            mock_proc.keep_gnss_observables = ["SNR"]
            mock_proc.days_per_batch = 1
            mock_proc.resolve_resources.return_value = {
                "n_workers": 2,
                "max_memory_gb": 8.0,
                "cpu_affinity": None,
                "nice_priority": 0,
                "threads_per_worker": 1,
            }
            mock_config.return_value.processing.params = mock_proc
            mock_config.return_value.processing.aux_data.agency = "COD"

            pipeline = Pipeline("Fangorn")
            assert pipeline is not None


class TestAPIExports:
    """Test __all__ exports include all public API."""

    def test_all_contains_core_api(self):
        """__all__ should export core classes."""
        import canvodpy

        assert "Site" in canvodpy.__all__
        assert "Pipeline" in canvodpy.__all__
        assert "process_date" in canvodpy.__all__
        assert "calculate_vod" in canvodpy.__all__

    def test_all_contains_factory_api(self):
        """__all__ should export factory classes."""
        import canvodpy

        assert "VODWorkflow" in canvodpy.__all__
        assert "ReaderFactory" in canvodpy.__all__
        assert "GridFactory" in canvodpy.__all__
        assert "VODFactory" in canvodpy.__all__

    def test_all_contains_functional_api(self):
        """__all__ should export functional API."""
        import canvodpy

        assert "read_rinex" in canvodpy.__all__
        assert "create_grid" in canvodpy.__all__
        assert "assign_grid_cells" in canvodpy.__all__


class TestConfigurationCompatibility:
    """Test configuration access via public API."""

    def test_keep_gnss_observables_available_via_config(self):
        """keep_gnss_observables should be available via load_config()."""
        from canvod.config import load_config

        try:
            cfg = load_config()
        except (FileNotFoundError, Exception) as e:
            pytest.skip(f"Config not available: {e}")
        else:
            keep_vars = cfg.processing.params.keep_gnss_observables
            assert keep_vars is not None
            assert isinstance(keep_vars, list)


class TestSubpackageCompatibility:
    """Test subpackage imports still work."""

    def test_lazy_import_readers(self):
        """Should lazy import readers."""
        import canvodpy

        readers = canvodpy.readers
        assert readers is not None

    def test_lazy_import_grids(self):
        """Should lazy import grids."""
        import canvodpy

        grids = canvodpy.grids
        assert grids is not None

    def test_lazy_import_vod(self):
        """Should lazy import vod."""
        import canvodpy

        vod = canvodpy.vod
        assert vod is not None

    def test_all_contains_subpackages(self):
        """__all__ should list subpackages."""
        import canvodpy

        assert "readers" in canvodpy.__all__
        assert "grids" in canvodpy.__all__
        assert "vod" in canvodpy.__all__
        assert "viz" in canvodpy.__all__
        assert "store" in canvodpy.__all__
