"""Tests for GnssResearchSite's VOD-analysis config handling (GH #66).

reference_receiver on VodAnalysisConfig must always be the bare receiver
name (matches a 'receivers' config key) -- never the paired Icechunk store
group name. These tests exercise the three GnssResearchSite methods that
read/derive it, bypassing __init__ (which loads the global config and opens
real Icechunk stores) since none of them need a live store.
"""

from __future__ import annotations

import unittest.mock

import pytest
from canvod.config.models import ReceiverConfig, SiteConfig, VodAnalysisConfig

from canvod.store.manager import GnssResearchSite


def _make_site(site_config: SiteConfig) -> GnssResearchSite:
    """Construct a GnssResearchSite without __init__'s config load / store open."""
    site = object.__new__(GnssResearchSite)
    site.site_name = "test_site"
    site._site_config = site_config
    site._logger = unittest.mock.MagicMock()
    return site


def _paired_site_config(**overrides) -> SiteConfig:
    defaults = {
        "gnss_site_data_root": "/data/site",
        "receivers": {
            "canopy_01": ReceiverConfig(type="canopy", directory="can/raw"),
            "reference_01": ReceiverConfig(
                type="reference", directory="ref/raw", paired_canopies="all"
            ),
        },
    }
    defaults.update(overrides)
    return SiteConfig(**defaults)


class TestGetAutoVodAnalyses:
    def test_produces_bare_reference_name(self):
        # vod_analyses left unset so SiteConfig's own auto-derivation fills
        # it in already (with bare names) -- force get_auto_vod_analyses's
        # own derivation path directly to check its output shape too.
        site = _make_site(_paired_site_config())
        analyses = site.get_auto_vod_analyses()
        cfg = analyses["canopy_01_vs_reference_01"]
        assert cfg.reference_receiver == "reference_01"
        assert cfg.canopy_receiver == "canopy_01"

    def test_matches_site_config_auto_derivation_convention(self):
        """get_auto_vod_analyses and SiteConfig._auto_derive_vod_analyses
        must agree on the bare-name convention -- previously they didn't
        (this method emitted the paired name instead).
        """
        site_config = _paired_site_config()
        site = _make_site(site_config)

        from_manager = site.get_auto_vod_analyses()["canopy_01_vs_reference_01"]
        from_config = site_config.vod_analyses["canopy_01_vs_reference_01"]

        assert from_manager.reference_receiver == from_config.reference_receiver


class TestValidateSiteConfig:
    def test_valid_bare_reference_passes(self):
        site = _make_site(_paired_site_config())
        assert site.validate_site_config() is True

    def test_unknown_reference_receiver_raises(self):
        site_config = _paired_site_config(
            vod_analyses={
                "bad": VodAnalysisConfig(
                    canopy_receiver="canopy_01", reference_receiver="nonexistent"
                )
            }
        )
        site = _make_site(site_config)
        with pytest.raises(ValueError, match="unknown reference receiver"):
            site.validate_site_config()

    def test_paired_store_group_name_no_longer_accepted(self):
        """The old validator tolerated a store-group-shaped name (a design
        smell in itself); now that reference_receiver is unambiguously bare,
        a group-shaped value should be rejected as an unknown receiver.
        """
        site_config = _paired_site_config(
            vod_analyses={
                "bad": VodAnalysisConfig(
                    canopy_receiver="canopy_01",
                    reference_receiver="reference_01_canopy_01",
                )
            }
        )
        site = _make_site(site_config)
        with pytest.raises(ValueError, match="unknown reference receiver"):
            site.validate_site_config()

    def test_wrong_receiver_type_raises(self):
        site_config = _paired_site_config(
            vod_analyses={
                "bad": VodAnalysisConfig(
                    canopy_receiver="reference_01", reference_receiver="reference_01"
                )
            }
        )
        site = _make_site(site_config)
        with pytest.raises(ValueError, match="used as canopy"):
            site.validate_site_config()


class TestPrepareVodInputData:
    def test_reads_reference_data_from_paired_store_group(self):
        """This path had no fallback -- it used to read the bare receiver
        name directly, which the store never actually writes to (reference
        data always lands under the paired group). Confirms the fix.
        """
        site = _make_site(_paired_site_config())
        seen_names: list[str] = []

        def _fake_read(receiver_name, time_range=None):
            seen_names.append(receiver_name)
            return unittest.mock.MagicMock()

        with unittest.mock.patch.object(
            site, "read_receiver_data", side_effect=_fake_read
        ):
            site.prepare_vod_input_data("canopy_01_vs_reference_01")

        assert seen_names == ["canopy_01", "reference_01_canopy_01"]
