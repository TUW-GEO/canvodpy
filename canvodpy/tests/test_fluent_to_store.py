"""FluentWorkflow.to_store gives a new store its metadata first (#214)."""

from __future__ import annotations

import icechunk
import numpy as np
import pytest
import xarray as xr
from canvodpy.fluent import FluentWorkflow

from canvod.utils import testing


def _observations(receiver: str) -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(4) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((4, 2), 40.0, np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C"],
        },
        attrs={"File Hash": f"hash-{receiver}", "receiver": receiver},
    )


def _repository(store_path) -> dict:
    return icechunk.Repository.open(
        icechunk.local_filesystem_storage(str(store_path))
    ).get_metadata()


def _workflow(**datasets) -> FluentWorkflow:
    workflow = FluentWorkflow(site=testing.SITE_KEY, keep_vars=["SNR"])
    # What .read() leaves behind
    workflow._datasets = {name: _observations(name) for name in datasets}
    return workflow


class TestGnssStore:
    def test_a_new_store_gets_its_metadata_before_the_data(self, site_settings):
        workflow = _workflow(canopy_01=1)

        workflow.to_store()

        store = workflow._site.gnss_store
        assert _repository(store.store_path)["identity"]["id"] == (
            f"{testing.SITE_KEY}-gnss"
        )
        assert "canopy_01" in store.list_groups()

    def test_an_unlisted_receiver_is_refused_with_the_amend_command(
        self, site_settings
    ):
        _workflow(canopy_01=1).to_store()

        with pytest.raises(ValueError, match="--add-receiver canopy_02"):
            _workflow(canopy_02=1).to_store()


class TestVodStore:
    def test_vod_goes_to_the_listed_analysis_of_the_pair(self, site_settings):
        workflow = _workflow()
        workflow._vod_result = xr.Dataset(
            {"VOD": (("epoch",), np.zeros(4, np.float32))},
            coords={"epoch": _observations("x").epoch},
        )
        workflow._vod_pair = ("canopy_01", "reference_01")

        workflow.to_store()

        store = workflow._site.vod_store
        repository = _repository(store.store_path)
        assert set(repository["vod_analyses"]) == {"canopy_01_vs_reference_01"}
        written = store.read_group("tau_omega/canopy_01_vs_reference_01")
        assert written.sizes["epoch"] == 4

    def test_a_pair_without_a_vod_analysis_is_refused(self, site_settings):
        workflow = _workflow()
        workflow._vod_result = xr.Dataset({"VOD": (("epoch",), np.zeros(1))})
        workflow._vod_pair = ("canopy_01", "canopy_01")

        with pytest.raises(ValueError, match=r"sites\.fangorn\.vod_analyses"):
            workflow.to_store()
