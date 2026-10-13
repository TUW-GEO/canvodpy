"""Every path that writes data gives a new store its metadata first (#214).

Runs from the command line, Python and Airflow take the same step: a new
store gets its repository metadata from the settings, and receivers or VOD
analyses the metadata doesn't list are refused with the amend command.
"""

from __future__ import annotations

import icechunk
import numpy as np
import pytest
import xarray as xr

from canvod.store import GnssResearchSite
from canvod.store_metadata.testing import give_test_metadata
from canvod.utils import testing


def _repository(store_path) -> dict:
    return icechunk.Repository.open(
        icechunk.local_filesystem_storage(str(store_path))
    ).get_metadata()


def _observations() -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(4) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((4, 2), 40.0, np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C"],
        },
        attrs={"File Hash": "hash-canopy_01"},
    )


def _no_files() -> dict:
    """The receiver files of a day without files, as check_rinex passes them."""
    return {
        "canopy_01": {"files": [], "count": 0},
        "reference_01": {"files": [], "count": 0},
    }


class TestAirflowTasks:
    @pytest.mark.parametrize("task", ["process_rinex", "process_sbf"])
    def test_a_new_site_gets_its_store_metadata(self, site_settings, task):
        from canvodpy.workflows import tasks

        with pytest.warns(FutureWarning):
            getattr(tasks, task)(
                testing.SITE_KEY,
                "2025001",
                receiver_files=_no_files(),
                aux_zarr_path=str(site_settings / "aux.zarr"),
            )

        repository = _repository(
            GnssResearchSite(testing.SITE_KEY).gnss_store.store_path
        )
        assert set(repository["instruments"]["receivers"]) == {
            "canopy_01",
            "reference_01",
        }

    def test_a_receiver_the_store_does_not_list_is_refused(self, site_settings):
        from canvodpy.workflows import tasks

        site = GnssResearchSite(testing.SITE_KEY)
        give_test_metadata(site.gnss_store_path, receivers={"canopy_01": "canopy"})

        with (
            pytest.warns(FutureWarning),
            pytest.raises(ValueError, match="--add-receiver reference_01"),
        ):
            tasks.process_rinex(
                testing.SITE_KEY,
                "2025001",
                receiver_files=_no_files(),
                aux_zarr_path=str(site_settings / "aux.zarr"),
            )


class TestResearchSite:
    def test_a_new_site_has_no_stores_until_a_run_creates_them(self, site_settings):
        site = GnssResearchSite(testing.SITE_KEY)

        assert not site.gnss_store_path.exists()
        assert not site.vod_store_path.exists()
        with pytest.raises(FileNotFoundError, match="a run creates a store"):
            _ = site.gnss_store

    def test_a_site_names_its_store_paths_and_keeps_them(self, site_settings):
        from canvod.config import load_config
        from canvodpy import Site

        storage = load_config().processing.storage
        site = Site(testing.SITE_KEY)

        assert site.gnss_store_path == storage.get_gnss_store_path(testing.SITE_KEY)
        assert site.vod_store_path == storage.get_vod_store_path(testing.SITE_KEY)
        with pytest.raises(AttributeError):
            site.vod_store_path = site_settings  # ty: ignore[invalid-assignment]

    def test_a_run_creates_the_store_with_the_settings_configuration(
        self, site_settings
    ):
        from canvod.config import load_config

        site = GnssResearchSite(testing.SITE_KEY)

        site.ingest_receiver_data(_observations(), "canopy_01", "first day")

        reopened = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(site.gnss_store_path))
        )
        expected = load_config().processing.icechunk.inline_chunk_threshold_bytes
        assert reopened.config.inline_chunk_threshold_bytes == expected

    def test_ingested_data_lands_in_a_store_with_metadata(self, site_settings):
        site = GnssResearchSite(testing.SITE_KEY)

        site.ingest_receiver_data(_observations(), "canopy_01", "first day")

        repository = _repository(site.gnss_store.store_path)
        assert repository["identity"]["id"] == f"{testing.SITE_KEY}-gnss"
        assert "canopy_01" in site.gnss_store.list_groups()

    def test_vod_of_an_unlisted_analysis_is_refused(self, site_settings):
        site = GnssResearchSite(testing.SITE_KEY)
        give_test_metadata(site.vod_store_path, "vod_store", vod_analyses={})

        with pytest.raises(
            ValueError, match="--add-vod-analysis canopy_01_vs_reference_01"
        ):
            site.store_vod_analysis(
                xr.Dataset({"VOD": (("epoch",), np.zeros(4))}),
                "canopy_01_vs_reference_01",
                "tau_omega",
                source_file_hashes={"canopy_01": "a", "reference_01": "b"},
                source_gnss_stores={},
            )


class TestFirstRun:
    """The checks a run makes before its first write find no store yet."""

    def test_the_preprocessing_check_passes_without_a_vod_store(self, site_settings):
        from canvodpy.vod_computer import VodComputer

        from canvodpy import Site

        site = Site(testing.SITE_KEY)

        VodComputer(site).check_preprocessing(list(site.vod_analyses))

        assert not site.vod_store_path.exists()

    def test_a_new_site_has_no_vod_gaps(self, site_settings):
        from canvodpy.orchestrator.vod_reconcile import find_vod_backfill_gaps

        from canvodpy import Site

        site = Site(testing.SITE_KEY)

        for analysis_name in site.vod_analyses:
            assert find_vod_backfill_gaps(site, analysis_name, "tau_omega") == []
        assert not site.gnss_store_path.exists()

    def test_a_run_without_a_start_date_scans_all_data(self, site_settings):
        from types import SimpleNamespace

        from canvodpy.cli.run import _resolve_date_range

        from canvodpy import Site

        site = Site(testing.SITE_KEY)

        start, end = _resolve_date_range(
            SimpleNamespace(start=None, end="2025002"), site
        )

        assert (start, end) == ("2000001", "2025002")
        assert not site.gnss_store_path.exists()

    def test_the_pipeline_preprocessing_check_passes_without_a_gnss_store(
        self, site_settings
    ):
        from canvodpy.orchestrator.pipeline import PipelineOrchestrator

        from canvod.config import load_config

        orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
        orchestrator.site = GnssResearchSite(testing.SITE_KEY)
        orchestrator._config = load_config()

        orchestrator._check_preprocessing_before_run(
            [("2025001", {"canopy_01": ()})]  # ty: ignore[invalid-argument-type]
        )

        assert not orchestrator.site.gnss_store_path.exists()
