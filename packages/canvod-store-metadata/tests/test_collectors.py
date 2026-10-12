"""Test runtime collectors."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from canvod.utils import testing

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

    def test_config_snapshot_leaves_out_credentials(self):
        with_account = {
            "processing": {
                "batch_hours": 24,
                "credentials": {"nasa_earthdata_acc_mail": "jane@example.org"},
            }
        }
        without = {"processing": {"batch_hours": 24}}

        snap = collect_config_snapshot(with_account)

        assert snap.processing == {"batch_hours": 24}
        assert snap.config_hash == collect_config_snapshot(without).config_hash

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
        config, site_cfg = _settings()
        meta = _collect(config, site_cfg)
        assert meta.identity.id == "fangorn-gnss"
        assert meta.identity.description == testing.SITE_DESCRIPTION
        assert meta.creator.name == testing.PERSON_NAME
        assert meta.publisher.name == testing.PUBLISHER
        assert meta.publisher.license == "CC-BY-4.0"
        assert meta.processing.python is not None

    @pytest.mark.parametrize(
        ("missing", "named"),
        [
            ("store_description", r"sites\.fangorn\.store_description"),
            ("publisher", r"processing\.metadata\.publisher"),
            ("license", r"processing\.metadata\.license"),
        ],
    )
    def test_collect_metadata_refuses_a_missing_required_field(self, missing, named):
        """A store is not created without description, publisher or license."""
        config, site_cfg = _settings()
        owner = (
            site_cfg if missing == "store_description" else config.processing.metadata
        )
        setattr(owner, missing, None)
        with pytest.raises(ValueError, match=named):
            _collect(config, site_cfg)

    def test_collect_metadata_names_every_missing_field(self):
        config, site_cfg = _settings()
        site_cfg.store_description = None
        config.processing.metadata.publisher = " "
        config.processing.metadata.license = None
        with pytest.raises(ValueError) as err:
            _collect(config, site_cfg)
        for name in ("store_description", "publisher", "license"):
            assert name in str(err.value)

    def test_collect_metadata_takes_the_deprecated_shared_description(self):
        """Settings from before the per-site description still create stores."""
        config, site_cfg = _settings()
        site_cfg.store_description = None
        config.processing.metadata.store_description = testing.SITE_DESCRIPTION
        meta = _collect(config, site_cfg)
        assert meta.identity.description == testing.SITE_DESCRIPTION


def _settings() -> tuple[MagicMock, MagicMock]:
    """Settings for a new store at the made-up site, every required field set."""
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
    meta_cfg.author = testing.PERSON_NAME
    meta_cfg.email = testing.PERSON_EMAIL
    meta_cfg.institution = testing.INSTITUTION
    for name in (
        "orcid",
        "institution_ror",
        "department",
        "research_group",
        "website",
        "publisher_url",
        "store_description",
    ):
        setattr(meta_cfg, name, None)
    meta_cfg.publisher = testing.PUBLISHER
    meta_cfg.license = "CC-BY-4.0"
    meta_cfg.naming_authority = testing.NAMING_AUTHORITY

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
            "store_description",
            "country",
            "receivers",
        ]
    )
    site_cfg.latitude = testing.LATITUDE
    site_cfg.longitude = testing.LONGITUDE
    site_cfg.altitude_m = testing.ALTITUDE_M
    site_cfg.description = None
    site_cfg.store_description = testing.SITE_DESCRIPTION
    site_cfg.country = None
    site_cfg.receivers = {}
    return config, site_cfg


def _collect(config: MagicMock, site_cfg: MagicMock):
    from canvod.store_metadata.schema import ConfigSnapshot

    with patch("canvod.store_metadata.collectors.collect_config_snapshot") as snap:
        snap.return_value = ConfigSnapshot(config_hash="abc123")
        return collect_metadata(
            config=config,
            site_name="fangorn",
            site_config=site_cfg,
            store_type="gnss_store",
            source_format="rinex3",
            store_path=Path("/tmp/test"),
        )
