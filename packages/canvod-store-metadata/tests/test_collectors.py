"""Test runtime collectors."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from canvod.store_metadata.collectors import (
    collect_config_snapshot,
    collect_creator,
    collect_environment,
    collect_metadata,
    collect_python_info,
    collect_references,
    collect_software_versions,
    collect_spatial,
)


class TestCollectors:
    def test_collect_software_versions(self):
        versions = collect_software_versions()
        assert isinstance(versions, dict)
        assert "pydantic" in versions

    def test_collect_software_versions_has_every_canvod_package(self):
        # Every package of the repository is installed in its environment.
        versions = collect_software_versions()
        for pkg in [
            "canvodpy",
            "canvod-utils",
            "canvod-config",
            "canvod-readers",
            "canvod-auxiliary",
            "canvod-preflight",
            "canvod-vod",
            "canvod-grids",
            "canvod-ops",
            "canvod-store-metadata",
            "canvod-store",
            "canvod-viz",
        ]:
            assert pkg in versions

    def test_collect_python_info(self):
        info = collect_python_info()
        assert "3." in info
        assert "CPython" in info

    def test_collect_environment(self):
        env = collect_environment()
        assert env.hostname is not None
        assert env.os is not None
        assert env.cpu_count is not None and env.cpu_count > 0

    def test_collect_environment_with_path(self, tmp_path):
        env = collect_environment(store_path=tmp_path)
        assert env.disk_free_gb is not None

    def test_collect_environment_uv_env(self):
        env = collect_environment()
        # When run from the monorepo, raw files should be captured
        if env.uv_lock_hash is not None:
            assert len(env.uv_lock_hash) == 64
        if env.uv_lock_text is not None:
            assert "[[package]]" in env.uv_lock_text
            assert "pydantic" in env.uv_lock_text
        if env.pyproject_toml_text is not None:
            assert "[tool" in env.pyproject_toml_text

    def test_collect_creator(self):
        meta_cfg = MagicMock()
        meta_cfg.author = "Test"
        meta_cfg.email = "test@example.com"
        meta_cfg.institution = "TestU"
        meta_cfg.orcid = None
        meta_cfg.institution_ror = None
        meta_cfg.department = "Dept"
        meta_cfg.research_group = None
        meta_cfg.website = None

        creator = collect_creator(meta_cfg)
        assert creator.name == "Test"
        assert creator.department == "Dept"

    def test_collect_spatial(self):
        site_cfg = MagicMock()
        site_cfg.latitude = 47.7
        site_cfg.longitude = 16.3
        site_cfg.altitude_m = 400.0
        site_cfg.description = "Test site"
        site_cfg.country = "AT"

        spatial = collect_spatial(site_cfg, "Rosalia")
        assert spatial.site.name == "Rosalia"
        assert spatial.geospatial_lat == 47.7
        assert spatial.bbox == [16.3, 47.7, 16.3, 47.7]

    def test_collect_config_snapshot(self):
        config = {
            "processing": {"batch_hours": 24},
            "preprocessing": {"enabled": True},
            "aux_data": {"agency": "COD"},
            "compression": {"zlib": True},
            "icechunk": {"compression_level": 5},
            "sids": {"mode": "all"},
        }

        snap = collect_config_snapshot(config)
        assert snap.config_hash is not None
        assert len(snap.config_hash) == 64
        assert snap.processing == {"batch_hours": 24}

    def test_collect_references_none_config(self):
        config = MagicMock(spec=["processing"])
        config.processing = MagicMock(spec=[])  # no `references` attribute

        refs = collect_references(config)
        assert refs.software_repository is None
        assert refs.documentation is None
        assert refs.access_url is None
        assert refs.related_stores == []
        assert refs.publications == []
        assert refs.funding == []

    def test_collect_references_full(self):
        refs_cfg = MagicMock(
            spec=[
                "software_repository",
                "documentation",
                "access_url",
                "related_stores",
                "publications",
                "funding",
            ]
        )
        refs_cfg.software_repository = "https://github.com/nfb2021/canvodpy"
        refs_cfg.documentation = "https://github.com/nfb2021/canvodpy/tree/main/docs"
        refs_cfg.access_url = "https://example.org/store"
        refs_cfg.related_stores = ["rosalia_v3_04/vod_store"]
        refs_cfg.publications = []

        funding_entry = MagicMock(
            spec=["funder", "funder_ror", "grant_number", "award_title"]
        )
        funding_entry.funder = "European Space Agency (ESA)"
        funding_entry.funder_ror = "https://ror.org/03wd9za21"
        funding_entry.grant_number = "4000146954/24/I-LR"
        funding_entry.award_title = "SIRENE"
        refs_cfg.funding = [funding_entry]

        proc = MagicMock(spec=["references"])
        proc.references = refs_cfg
        config = MagicMock(spec=["processing"])
        config.processing = proc

        refs = collect_references(config)
        assert refs.software_repository == "https://github.com/nfb2021/canvodpy"
        assert (
            refs.documentation == "https://github.com/nfb2021/canvodpy/tree/main/docs"
        )
        assert refs.access_url == "https://example.org/store"
        assert refs.related_stores == ["rosalia_v3_04/vod_store"]
        assert refs.funding[0].funder == "European Space Agency (ESA)"
        assert refs.funding[0].award_title == "SIRENE"

    def test_collect_metadata_full(self):
        meta_cfg = MagicMock(
            spec=[
                "author",
                "email",
                "institution",
                "orcid",
                "institution_ror",
                "department",
                "research_group",
                "website",
                "publisher",
                "publisher_url",
                "license",
                "naming_authority",
                "store_description",
            ]
        )
        meta_cfg.author = "Test"
        meta_cfg.email = "test@example.com"
        meta_cfg.institution = "TestU"
        meta_cfg.orcid = None
        meta_cfg.institution_ror = None
        meta_cfg.department = None
        meta_cfg.research_group = None
        meta_cfg.website = None
        meta_cfg.publisher = None
        meta_cfg.publisher_url = None
        meta_cfg.license = None
        meta_cfg.naming_authority = None
        meta_cfg.store_description = "A test store for TestSite."

        proc = MagicMock(spec=["metadata", "references"])
        proc.metadata = meta_cfg
        proc.references = None

        config = MagicMock(spec=["processing", "sids"])
        config.processing = proc
        config.sids = MagicMock(spec=[])

        site_cfg = MagicMock(
            spec=[
                "latitude",
                "longitude",
                "altitude_m",
                "description",
                "country",
                "receivers",
            ]
        )
        site_cfg.latitude = 47.7
        site_cfg.longitude = 16.3
        site_cfg.altitude_m = 400.0
        site_cfg.description = None
        site_cfg.country = None
        site_cfg.receivers = {}

        with patch(
            "canvod.store_metadata.collectors.collect_config_snapshot"
        ) as mock_snap:
            from canvod.store_metadata.schema import ConfigSnapshot

            mock_snap.return_value = ConfigSnapshot(config_hash="abc123")
            meta = collect_metadata(
                config=config,
                site_name="TestSite",
                site_config=site_cfg,
                store_type="gnss_store",
                source_format="rinex3",
                store_path=Path("/tmp/test"),
            )
        assert meta.identity.id == "TestSite/gnss_store"
        assert meta.identity.description == "A test store for TestSite."
        assert meta.creator.name == "Test"
        assert meta.processing.python is not None

    def test_collect_metadata_description_defaults_to_none(self):
        """meta_cfg without store_description set must not raise, and
        identity.description must stay None (regression guard for the
        getattr(..., None) fallback in collect_metadata)."""
        meta_cfg = MagicMock(
            spec=[
                "author",
                "email",
                "institution",
                "orcid",
                "institution_ror",
                "department",
                "research_group",
                "website",
                "publisher",
                "publisher_url",
                "license",
                "naming_authority",
                # store_description intentionally omitted from spec
            ]
        )
        meta_cfg.author = "Test"
        meta_cfg.email = "test@example.com"
        meta_cfg.institution = "TestU"
        meta_cfg.orcid = None
        meta_cfg.institution_ror = None
        meta_cfg.department = None
        meta_cfg.research_group = None
        meta_cfg.website = None
        meta_cfg.publisher = None
        meta_cfg.publisher_url = None
        meta_cfg.license = None
        meta_cfg.naming_authority = None

        proc = MagicMock(spec=["metadata", "references"])
        proc.metadata = meta_cfg
        proc.references = None

        config = MagicMock(spec=["processing", "sids"])
        config.processing = proc
        config.sids = MagicMock(spec=[])

        site_cfg = MagicMock(
            spec=[
                "latitude",
                "longitude",
                "altitude_m",
                "description",
                "country",
                "receivers",
            ]
        )
        site_cfg.latitude = 47.7
        site_cfg.longitude = 16.3
        site_cfg.altitude_m = 400.0
        site_cfg.description = None
        site_cfg.country = None
        site_cfg.receivers = {}

        with patch(
            "canvod.store_metadata.collectors.collect_config_snapshot"
        ) as mock_snap:
            from canvod.store_metadata.schema import ConfigSnapshot

            mock_snap.return_value = ConfigSnapshot(config_hash="abc123")
            meta = collect_metadata(
                config=config,
                site_name="TestSite",
                site_config=site_cfg,
                store_type="gnss_store",
                source_format="rinex3",
                store_path=Path("/tmp/test"),
            )
        assert meta.identity.description is None
