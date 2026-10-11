"""Moving a store written before ADR 0014 to repository metadata (#206)."""

from pathlib import Path

import icechunk
import numpy as np
import pytest
import xarray as xr
import zarr

from canvod.store_metadata import (
    ensure_metadata,
    migrate_metadata,
    read_metadata,
    validate_all,
)
from canvod.store_metadata.schema import (
    ConfigSnapshot,
    Creator,
    Instruments,
    Publisher,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)

#: Two epochs of SNR, with attributes as older versions wrote them.
_SNR_DAY = xr.Dataset(
    {
        "SNR": (
            ("epoch", "sid"),
            np.array([[40.0, 41.0], [42.0, 43.0]]),
            {"units": "dB", "valid_min": 0},
        )
    },
    coords={
        "epoch": np.array(
            ["2025-01-01T00:00:00", "2025-01-01T00:00:30"], dtype="datetime64[ns]"
        ),
        "sid": ["G01|L1|C", "G02|L1|C"],
        "system": ("sid", ["G", "G"]),
    },
)


def _old_metadata(
    naming_authority: str | None = "at.ac.tuwien", *, complete: bool = True
) -> StoreMetadata:
    """``complete=False``: without the description and publisher older stores lack."""
    return StoreMetadata(
        identity=StoreIdentity(
            id="Rosalia/gnss_store",
            title="Rosalia Gnss Store",
            description="Beech forest site." if complete else None,
            keywords=["GNSS", "SNR"],
            store_type="gnss_store",
            source_format="rinex3",
            naming_authority=naming_authority,
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        publisher=Publisher(name="U", license="CC-BY-4.0") if complete else Publisher(),
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


def _old_store(
    tmp_path: Path,
    naming_authority: str | None = "at.ac.tuwien",
    *,
    complete: bool = True,
) -> Path:
    path = tmp_path / "store"
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    root.attrs.update(
        _old_metadata(naming_authority, complete=complete).to_root_attrs()
    )
    _SNR_DAY.to_zarr(session.store, group="canopy_01", consolidated=False)
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


class TestMigrationChecks:
    def test_a_store_that_would_fail_the_checks_is_refused(self, tmp_path):
        path = _old_store(tmp_path, complete=False)

        with pytest.raises(ValueError, match="would fail the standards checks") as e:
            migrate_metadata(path)
        assert "summary" in str(e.value)
        assert "publisher.name" in str(e.value)
        assert "publisher.license" in str(e.value)
        assert not _repo(path).get_metadata()

    def test_missing_fields_are_given_at_migration_time(self, tmp_path):
        path = _old_store(tmp_path, complete=False)

        migrate_metadata(
            path,
            values={
                "identity.description": "Beech forest site.",
                "publisher.name": "U",
                "publisher.license": "CC-BY-4.0",
            },
        )

        meta = read_metadata(path)
        assert meta.identity.description == "Beech forest site."
        assert not any(validate_all(meta, recommended=False).values())
        assert meta.migration.fields_given == [
            "identity.description",
            "publisher.license",
            "publisher.name",
        ]

    def test_a_fixed_field_cannot_be_given(self, tmp_path):
        path = _old_store(tmp_path)

        with pytest.raises(ValueError, match="fixed field"):
            migrate_metadata(path, values={"identity.id": "other"})
        assert not _repo(path).get_metadata()


class TestVariableAttributes:
    def test_named_variables_get_the_new_attributes(self, tmp_path):
        path = _old_store(tmp_path)
        new = {"long_name": "Signal-to-noise ratio", "units": "dB"}

        migrate_metadata(path, variable_attrs={"SNR": new})

        root = zarr.open_group(
            _repo(path).readonly_session(branch="main").store, mode="r"
        )
        attrs = dict(root["canopy_01/SNR"].attrs)
        assert {k: attrs[k] for k in new} == new
        assert set(attrs) - set(new) <= {"_FillValue", "coordinates"}
        assert _repo(path).get_metadata()["migration"]["variables_replaced"] == [
            "canopy_01/SNR"
        ]

    def test_without_variable_attrs_nothing_is_replaced(self, tmp_path):
        path = _old_store(tmp_path)

        migrate_metadata(path)

        root = zarr.open_group(
            _repo(path).readonly_session(branch="main").store, mode="r"
        )
        assert root["canopy_01/SNR"].attrs["valid_min"] == 0
        assert _repo(path).get_metadata()["migration"]["variables_replaced"] == []
