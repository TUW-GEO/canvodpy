"""Test runtime collectors."""

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from canvod.utils import testing

from canvod.store_metadata import collectors
from canvod.store_metadata.collectors import (
    collect_config_snapshot,
    collect_creator,
    collect_environment,
    collect_metadata,
    collect_processing_provenance,
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
        site_cfg.latitude = testing.LATITUDE
        site_cfg.longitude = testing.LONGITUDE
        site_cfg.altitude_m = testing.ALTITUDE_M
        site_cfg.description = "Test site"
        site_cfg.country = "AT"

        spatial = collect_spatial(site_cfg, "Fangorn")
        assert spatial.site.name == "Fangorn"
        assert spatial.geospatial_lat == testing.LATITUDE
        assert spatial.bbox == [
            testing.LONGITUDE,
            testing.LATITUDE,
            testing.LONGITUDE,
            testing.LATITUDE,
        ]

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
        refs_cfg.software_repository = testing.REPOSITORY
        refs_cfg.documentation = testing.DOCUMENTATION
        refs_cfg.access_url = "https://example.org/store"
        refs_cfg.related_stores = ["fangorn/vod_store"]
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
        assert refs.software_repository == testing.REPOSITORY
        assert refs.documentation == testing.DOCUMENTATION
        assert refs.access_url == "https://example.org/store"
        assert refs.related_stores == ["fangorn/vod_store"]
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

    def test_a_license_outside_spdx_comes_with_the_uri_of_its_text(self):
        config, site_cfg = _settings()
        config.processing.metadata.license = "other"
        config.processing.metadata.license_uri = "https://the.inklings.org/licence"

        meta = _collect(config, site_cfg)

        assert meta.publisher.license == "other"
        assert meta.publisher.license_uri == "https://the.inklings.org/licence"

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
            "license_uri",
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
        "license_uri",
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


def _project(path: Path, lock: str = "version = 1\n") -> Path:
    """A uv project: pyproject.toml and uv.lock."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text('[project]\nname = "fangorn"\n')
    (path / "uv.lock").write_bytes(lock.encode())
    return path


class TestLockfile:
    def test_the_lockfile_of_the_project_run_from_is_recorded(
        self, tmp_path, monkeypatch
    ):
        project = _project(tmp_path / "fangorn")
        (project / "notebooks").mkdir()
        monkeypatch.chdir(project / "notebooks")

        env = collect_environment()

        assert env.uv_lock_text == "version = 1\n"
        assert env.uv_lock_hash == hashlib.sha256(b"version = 1\n").hexdigest()
        assert env.pyproject_toml_text == '[project]\nname = "fangorn"\n'

    def test_outside_a_project_no_lockfile_is_recorded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        env = collect_environment()

        assert env.uv_lock_text is None
        assert env.uv_lock_hash is None
        assert env.pyproject_toml_text is None

    def test_an_unreadable_lockfile_is_an_error(self, tmp_path, monkeypatch):
        project = _project(tmp_path / "fangorn")
        monkeypatch.chdir(project)
        monkeypatch.setattr(
            Path,
            "read_bytes",
            lambda self: (_ for _ in ()).throw(PermissionError(str(self))),
        )

        with pytest.raises(PermissionError, match="uv.lock"):
            collect_environment()


class TestOncePerProcess:
    def test_uv_runs_once_for_many_commits(self, monkeypatch):
        calls = []

        def run(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="uv 0.9.0\n")

        monkeypatch.setattr(subprocess, "run", run)
        collectors.collect_uv_version.cache_clear()
        try:
            first = collect_processing_provenance("gnss_store", "rinex3")
            second = collect_processing_provenance("gnss_store", "rinex3")
        finally:
            collectors.collect_uv_version.cache_clear()

        assert len(calls) == 1
        assert first.uv_version == second.uv_version == "uv 0.9.0"

    def test_the_lockfile_is_read_once_until_it_changes(self, tmp_path, monkeypatch):
        project = _project(tmp_path / "fangorn")
        monkeypatch.chdir(project)
        reads = []
        read_bytes = Path.read_bytes

        def counted(self):
            reads.append(self.name)
            return read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", counted)

        first = collect_environment()
        second = collect_environment()
        assert reads.count("uv.lock") == 1
        assert first.uv_lock_hash == second.uv_lock_hash

        (project / "uv.lock").write_bytes(b"version = 1\nrevision = 3\n")
        third = collect_environment()
        assert reads.count("uv.lock") == 2
        assert third.uv_lock_text == "version = 1\nrevision = 3\n"
        assert third.uv_lock_hash != first.uv_lock_hash

    def test_software_versions_cannot_be_changed_by_a_caller(self):
        collect_software_versions()["pydantic"] = "0"

        assert collect_software_versions()["pydantic"] != "0"
