"""A receiver's ``metadata`` setting goes into the attributes of its data."""

from __future__ import annotations

import numpy as np
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
