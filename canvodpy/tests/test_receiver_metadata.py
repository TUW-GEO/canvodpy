"""A receiver's ``metadata`` setting goes into the attributes of its data."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from canvod.store import GnssResearchSite
from canvod.utils import testing


def _observations() -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(2) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((2, 1), 40.0, np.float32))},
        coords={"epoch": epochs, "sid": ["G01|L1|C"]},
        attrs={"File Hash": "hash-canopy_01", "antenna_height": 1.5},
    )


def _site(monkeypatch, metadata) -> GnssResearchSite:
    site = GnssResearchSite(testing.SITE_KEY)
    monkeypatch.setattr(site, "get_receiver_metadata", lambda name: metadata)
    return site


def test_the_setting_is_added_to_the_attributes(site_settings, monkeypatch):
    site = _site(monkeypatch, {"species": "Fagus sylvatica"})

    ds = site.add_receiver_metadata(_observations(), "canopy_01")

    assert ds.attrs["species"] == "Fagus sylvatica"
    assert ds.attrs["File Hash"] == "hash-canopy_01"


def test_attributes_the_data_has_are_kept(site_settings, monkeypatch):
    site = _site(monkeypatch, {"antenna_height": 20.0, "species": "Fagus sylvatica"})

    ds = site.add_receiver_metadata(_observations(), "canopy_01")

    assert ds.attrs["antenna_height"] == 1.5
    assert ds.attrs["species"] == "Fagus sylvatica"


def test_the_given_dataset_is_not_changed(site_settings, monkeypatch):
    # Receivers that read the same files share their datasets.
    site = _site(monkeypatch, {"species": "Fagus sylvatica"})
    original = _observations()

    site.add_receiver_metadata(original, "canopy_01")

    assert "species" not in original.attrs


def test_without_a_setting_the_dataset_is_returned_as_it_is(site_settings, monkeypatch):
    site = _site(monkeypatch, None)
    original = _observations()

    assert site.add_receiver_metadata(original, "canopy_01") is original


def test_a_reference_group_gets_the_reference_receivers_setting(
    site_settings, monkeypatch
):
    # The reference's data go to one group per paired canopy.
    site = GnssResearchSite(testing.SITE_KEY)
    settings = {"reference_01": {"mount": "reference mast"}}
    monkeypatch.setattr(site, "get_receiver_metadata", settings.get)

    ds = site.add_receiver_metadata(_observations(), "reference_01_canopy_01")

    assert ds.attrs["mount"] == "reference mast"


@pytest.mark.integration
def test_a_run_stores_the_setting_of_canopy_and_reference(fangorn_site) -> None:
    # A reference receiver's data go to a group named after the receiver
    # and its canopy (reference_01_canopy_01); the setting is the receiver's.
    from canvod.store import MyIcechunkStore
    from canvodpy import Site

    config, test_site = fangorn_site
    site = config.sites.sites[testing.SITE_KEY]
    site.receivers = {
        name: cfg.model_copy(update={"metadata": {"mount": f"{name} mast"}})
        for name, cfg in test_site._site_config.receivers.items()
    }

    with Site(testing.SITE_KEY).pipeline(n_workers=1) as pipeline:
        pipeline.process_date("2025001")

    store = MyIcechunkStore(
        config.processing.storage.get_gnss_store_path(testing.SITE_KEY)
    )
    assert store.read_group("canopy_01").attrs["mount"] == "canopy_01 mast"
    assert (
        store.read_group("reference_01_canopy_01").attrs["mount"] == "reference_01 mast"
    )
