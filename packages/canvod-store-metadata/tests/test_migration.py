"""Moving a store written before ADR 0014 to repository metadata (#206)."""

from pathlib import Path
from typing import Any

import icechunk
import numpy as np
import pytest
import xarray as xr
import zarr
from canvod.utils import testing

from canvod.store_metadata import (
    ensure_metadata,
    migrate_metadata,
    read_metadata,
    validate_all,
)
from canvod.store_metadata.io import _set_field
from canvod.store_metadata.schema import (
    ConfigSnapshot,
    Creator,
    Instruments,
    MetadataRuleWarning,
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
    naming_authority: str | None = testing.NAMING_AUTHORITY, *, complete: bool = True
) -> StoreMetadata:
    """``complete=False``: without the description and publisher older stores lack."""
    return StoreMetadata(
        identity=StoreIdentity(
            id="Fangorn/gnss_store",
            title="Fangorn Gnss Store",
            description=testing.SITE_DESCRIPTION if complete else None,
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
            site=SiteInfo(name=testing.CANOPY_SITE),
            geospatial_lat=testing.LATITUDE,
            geospatial_lon=testing.LONGITUDE,
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
    naming_authority: str | None = testing.NAMING_AUTHORITY,
    *,
    complete: bool = True,
    changes: dict[str, Any] | None = None,
) -> Path:
    """``changes``: dotted fields as written, rules unchecked."""
    path = tmp_path / "store"
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    attrs = _old_metadata(naming_authority, complete=complete).to_root_attrs()
    for field, value in (changes or {}).items():
        _set_field(attrs["canvod_metadata"], field, value)
    root.attrs.update(attrs)
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

        migrate_metadata(path, who=testing.PERSON_INITIALS)

        repository = _repo(path).get_metadata()
        identity = repository["identity"]
        assert identity["id"] == "fangorn-gnss"
        assert identity["naming_authority"] == "org.middle-earth"
        assert identity["uuid"]
        assert identity["stac_link"] == (
            "../../gnss-observations/org.middle-earth.fangorn-gnss/"
            "org.middle-earth.fangorn-gnss.json"
        )
        assert repository["temporal"]["created"] == "2025-01-01T00:00:00+00:00"
        assert set(repository["instruments"]["receivers"]) == {"canopy_01"}
        assert "epochs" not in repository["instruments"]["receivers"]["canopy_01"]

    def test_migration_keeps_the_old_id_in_its_record(self, tmp_path):
        path = _old_store(tmp_path)

        migrate_metadata(path, who=testing.PERSON_INITIALS)

        record = _repo(path).get_metadata()["migration"]
        assert record["old_id"] == "Fangorn/gnss_store"
        assert record["old_metadata_version"] == "1.0.0"
        assert record["who"] == testing.PERSON_INITIALS
        assert record["when"]

    def test_the_migrated_store_reads_in_the_current_form(self, tmp_path):
        path = _old_store(tmp_path)
        before = _repo(path).lookup_branch("main")

        migrate_metadata(path, who=testing.PERSON_INITIALS)

        meta = read_metadata(path)
        assert not meta.written_before_migration
        assert meta.identity.id == "fangorn-gnss"
        assert read_metadata(path, snapshot_id=before).written_before_migration

    def test_writers_accept_the_migrated_store(self, tmp_path):
        path = _old_store(tmp_path)
        migrate_metadata(path, who=testing.PERSON_INITIALS)

        def fail():
            msg = "a migrated store needs no new metadata"
            raise AssertionError(msg)

        ensure_metadata(path, fail, site_name="Fangorn", store_type="gnss_store")

    def test_a_store_without_naming_authority_is_refused(self, tmp_path):
        path = _old_store(tmp_path, naming_authority=None)

        with pytest.raises(ValueError, match="--naming-authority"):
            migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert not _repo(path).get_metadata()

    def test_the_naming_authority_can_be_given(self, tmp_path):
        path = _old_store(tmp_path, naming_authority=None)

        migrate_metadata(
            path, who=testing.PERSON_INITIALS, naming_authority="eu.canvodpy"
        )

        assert _repo(path).get_metadata()["identity"]["id"] == "fangorn-gnss"
        assert (
            _repo(path).get_metadata()["identity"]["naming_authority"] == "eu.canvodpy"
        )

    def test_a_migration_needs_who_makes_it(self, tmp_path):
        path = _old_store(tmp_path)

        with pytest.raises(ValueError, match=r"processing\.metadata\.initials"):
            migrate_metadata(path, who="")
        assert not _repo(path).get_metadata()

    def test_migrating_twice_is_refused(self, tmp_path):
        path = _old_store(tmp_path)
        migrate_metadata(path, who=testing.PERSON_INITIALS)

        with pytest.raises(ValueError, match="already"):
            migrate_metadata(path, who=testing.PERSON_INITIALS)

    def test_a_store_without_any_metadata_is_refused(self, tmp_path):
        path = tmp_path / "plain"
        icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))

        with pytest.raises(ValueError, match="no store metadata to migrate"):
            migrate_metadata(path, who=testing.PERSON_INITIALS)


class TestMigrationChecks:
    def test_a_store_that_would_fail_the_checks_is_refused(self, tmp_path):
        path = _old_store(tmp_path, complete=False)

        with pytest.raises(ValueError, match="would fail the standards checks") as e:
            migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert "summary" in str(e.value)
        assert "publisher.name" in str(e.value)
        assert "publisher.license" in str(e.value)
        assert not _repo(path).get_metadata()

    def test_missing_fields_are_given_at_migration_time(self, tmp_path):
        path = _old_store(tmp_path, complete=False)

        migrate_metadata(
            path,
            who=testing.PERSON_INITIALS,
            values={
                "identity.description": testing.SITE_DESCRIPTION,
                "publisher.name": "U",
                "publisher.license": "CC-BY-4.0",
            },
        )

        meta = read_metadata(path)
        assert meta.identity.description == testing.SITE_DESCRIPTION
        assert not any(validate_all(meta, recommended=False).values())
        assert meta.migration.fields_given == [
            "identity.description",
            "publisher.license",
            "publisher.name",
        ]

    def test_a_field_under_an_unset_block_can_be_given(self, tmp_path):
        path = _old_store(tmp_path)

        migrate_metadata(
            path,
            who=testing.PERSON_INITIALS,
            values={"instruments.receivers.canopy_01.antenna.height_m": 1.5},
        )

        antenna = read_metadata(path).instruments.receivers["canopy_01"].antenna
        assert antenna is not None
        assert antenna.height_m == 1.5

    def test_a_migration_whose_commit_fails_can_be_retried(self, tmp_path, monkeypatch):
        path = _old_store(tmp_path)

        def fail(*args, **kwargs):
            raise icechunk.StorageError("disk full")

        with monkeypatch.context() as patch:
            patch.setattr(icechunk.Session, "commit", fail)
            with pytest.raises(icechunk.StorageError):
                migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert not _repo(path).get_metadata()

        migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert not read_metadata(path).written_before_migration

    def test_a_fixed_field_cannot_be_given(self, tmp_path):
        path = _old_store(tmp_path)

        with pytest.raises(ValueError, match="fixed field"):
            migrate_metadata(
                path, who=testing.PERSON_INITIALS, values={"identity.id": "other"}
            )
        assert not _repo(path).get_metadata()


class TestMigrationLicenseRule:
    def test_a_license_outside_spdx_is_refused_naming_the_field(self, tmp_path):
        path = _old_store(tmp_path, changes={"publisher.license": "Apache 2"})

        with pytest.raises(ValueError, match="publisher.license") as e:
            migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert "--set publisher.license=" in str(e.value)
        assert not _repo(path).get_metadata()

    def test_the_license_can_be_given_at_migration_time(self, tmp_path):
        path = _old_store(tmp_path, changes={"publisher.license": "Apache 2"})

        migrate_metadata(
            path,
            who=testing.PERSON_INITIALS,
            values={"publisher.license": "Apache-2.0"},
        )

        assert read_metadata(path).publisher.license == "Apache-2.0"


class TestMigrationFieldRules:
    def test_a_bad_orcid_is_refused_naming_the_field(self, tmp_path):
        path = _old_store(tmp_path, changes={"creator.orcid": "Treebeard"})

        with pytest.raises(ValueError, match=r"creator\.orcid.*ORCID") as e:
            migrate_metadata(path, who=testing.PERSON_INITIALS)
        assert "--set creator.orcid=" in str(e.value)

    def test_a_bad_computed_value_does_not_stop_the_migration(self, tmp_path):
        path = _old_store(
            tmp_path, changes={"temporal.time_coverage_duration": "PT2.592e+06S"}
        )

        with pytest.warns(MetadataRuleWarning, match="computes it again"):
            migrate_metadata(path, who=testing.PERSON_INITIALS)

        duration = read_metadata(path).temporal.time_coverage_duration
        assert duration is not None
        assert "e" not in duration


class TestVariableAttributes:
    def test_named_variables_get_the_new_attributes(self, tmp_path):
        path = _old_store(tmp_path)
        new = {"long_name": "Signal-to-noise ratio", "units": "dB"}

        migrate_metadata(path, who=testing.PERSON_INITIALS, variable_attrs={"SNR": new})

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

        migrate_metadata(path, who=testing.PERSON_INITIALS)

        root = zarr.open_group(
            _repo(path).readonly_session(branch="main").store, mode="r"
        )
        assert root["canopy_01/SNR"].attrs["valid_min"] == 0
        assert _repo(path).get_metadata()["migration"]["variables_replaced"] == []
