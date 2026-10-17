"""FluentWorkflow.to_store gives a new store its metadata first (#214).

The store records the format of the reader that read the files, as a run
records it (#328).
"""

from __future__ import annotations

from types import SimpleNamespace

import icechunk
import numpy as np
import pytest
import xarray as xr
from canvodpy.fluent import FluentWorkflow

from canvod.utils import testing


def _observations(receiver: str, source_format: str | None = "rinex3") -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(4) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((4, 2), 40.0, np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C"],
        },
        attrs={"File Hash": f"hash-{receiver}", "receiver": receiver}
        | ({} if source_format is None else {"Source Format": source_format}),
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


class _Rinex2Reader:
    """A reader of the registry name ``rinex_v2`` whose format is ``rinex2``."""

    source_format = "rinex2"

    def __init__(self, fpath) -> None:
        self.receiver = fpath

    def to_ds(self, write_global_attrs: bool = True) -> xr.Dataset:
        return _observations(self.receiver, source_format=None)


class TestSourceFormat:
    def test_a_new_store_records_the_readers_format_not_its_name(
        self, site_settings, monkeypatch
    ):
        import canvodpy.fluent
        import canvodpy.workflows.tasks

        monkeypatch.setattr(
            canvodpy.workflows.tasks,
            "_day_files",
            lambda *args: {"canopy_01": [SimpleNamespace(path="canopy_01")]},
        )
        monkeypatch.setattr(
            canvodpy.fluent.ReaderFactory,
            "create",
            lambda name, fpath: _Rinex2Reader(fpath),
        )
        workflow = FluentWorkflow(
            site=testing.SITE_KEY, reader="rinex_v2", keep_vars=["SNR"]
        )

        workflow.read("2025001", receivers=["canopy_01"]).to_store()

        repository = _repository(workflow._site.gnss_store.store_path)
        assert repository["identity"]["source_format"] == "rinex2"

    def test_data_without_its_readers_format_is_refused_naming_the_receiver(
        self, site_settings
    ):
        workflow = _workflow(canopy_01=1)
        workflow._datasets["canopy_01"].attrs.pop("Source Format")

        with pytest.raises(ValueError, match="canopy_01"):
            workflow.to_store()


class TestVodStore:
    def test_vod_goes_to_the_listed_analysis_of_the_pair(self, site_settings):
        # A VOD store records the content-settings hash of the GNSS store it
        # is computed from, so write GNSS data first (that store gets content
        # settings) before the VOD store.
        _workflow(canopy_01=1, reference_01=1).to_store()

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
