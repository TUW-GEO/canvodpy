"""Moving a store written before ADR 0014 to repository metadata (#206)."""

from pathlib import Path

import icechunk
import pytest
import zarr

from canvod.store_metadata import (
    ensure_metadata,
    migrate_metadata,
    read_metadata,
)
from canvod.store_metadata.schema import (
    ConfigSnapshot,
    Creator,
    Instruments,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)


def _old_metadata(naming_authority: str | None = "at.ac.tuwien") -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="Rosalia/gnss_store",
            title="Rosalia Gnss Store",
            store_type="gnss_store",
            source_format="rinex3",
            naming_authority=naming_authority,
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        temporal=TemporalExtent(
            created="2025-01-01T00:00:00+00:00", updated="2025-06-01T00:00:00+00:00"
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="Rosalia"), geospatial_lat=47.7, geospatial_lon=16.3
        ),
        instruments=Instruments(
            receivers={
                "canopy_01": ReceiverInfo(type="canopy", directory="c", epochs=17280)
            }
        ),
        config=ConfigSnapshot(config_hash="a" * 64),
    )


def _old_store(tmp_path: Path, naming_authority: str | None = "at.ac.tuwien") -> Path:
    path = tmp_path / "store"
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    root.attrs.update(_old_metadata(naming_authority).to_root_attrs())
    root.require_group("canopy_01")
    session.commit("data and metadata, old form")
    return path


def _repo(path: Path) -> icechunk.Repository:
    return icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(path))
    )


class TestMigration:
    def test_migration_writes_the_repository_metadata_in_the_current_form(
        self, tmp_path
    ):
        path = _old_store(tmp_path)

        migrate_metadata(path)

        repository = _repo(path).get_metadata()
        identity = repository["identity"]
        assert identity["id"] == "rosalia-gnss"
        assert identity["naming_authority"] == "at.ac.tuwien"
        assert identity["uuid"]
        assert identity["stac_link"] == (
            "../../gnss-observations/at.ac.tuwien.rosalia-gnss/"
            "at.ac.tuwien.rosalia-gnss.json"
        )
        assert repository["temporal"]["created"] == "2025-01-01T00:00:00+00:00"
        assert set(repository["instruments"]["receivers"]) == {"canopy_01"}
        assert "epochs" not in repository["instruments"]["receivers"]["canopy_01"]

    def test_migration_keeps_the_old_id_in_its_record(self, tmp_path):
        path = _old_store(tmp_path)

        migrate_metadata(path)

        record = _repo(path).get_metadata()["migration"]
        assert record["old_id"] == "Rosalia/gnss_store"
        assert record["old_metadata_version"] == "1.0.0"
        assert record["who"]
        assert record["when"]

    def test_the_migrated_store_reads_in_the_current_form(self, tmp_path):
        path = _old_store(tmp_path)
        before = _repo(path).lookup_branch("main")

        migrate_metadata(path)

        meta = read_metadata(path)
        assert not meta.written_before_migration
        assert meta.identity.id == "rosalia-gnss"
        assert read_metadata(path, snapshot_id=before).written_before_migration

    def test_writers_accept_the_migrated_store(self, tmp_path):
        path = _old_store(tmp_path)
        migrate_metadata(path)

        def fail():
            msg = "a migrated store needs no new metadata"
            raise AssertionError(msg)

        ensure_metadata(path, fail, site_name="Rosalia", store_type="gnss_store")

    def test_a_store_without_naming_authority_is_refused(self, tmp_path):
        path = _old_store(tmp_path, naming_authority=None)

        with pytest.raises(ValueError, match="--naming-authority"):
            migrate_metadata(path)
        assert not _repo(path).get_metadata()

    def test_the_naming_authority_can_be_given(self, tmp_path):
        path = _old_store(tmp_path, naming_authority=None)

        migrate_metadata(path, naming_authority="eu.canvodpy")

        assert _repo(path).get_metadata()["identity"]["id"] == "rosalia-gnss"
        assert (
            _repo(path).get_metadata()["identity"]["naming_authority"] == "eu.canvodpy"
        )

    def test_migrating_twice_is_refused(self, tmp_path):
        path = _old_store(tmp_path)
        migrate_metadata(path)

        with pytest.raises(ValueError, match="already"):
            migrate_metadata(path)

    def test_a_store_without_any_metadata_is_refused(self, tmp_path):
        path = tmp_path / "plain"
        icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))

        with pytest.raises(ValueError, match="no store metadata to migrate"):
            migrate_metadata(path)
