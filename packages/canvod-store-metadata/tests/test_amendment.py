"""Amending a store's description (ADR 0014, #205)."""

from pathlib import Path

import icechunk
import pytest
import zarr

from canvod.store_metadata import (
    amend_metadata,
    apply_updates,
    check_receivers,
    check_vod_analyses,
    read_metadata,
    update_metadata,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    Instruments,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
    VodAnalysisInfo,
)

_CONFIG = {"processing": {"batch_hours": 24}}


def _metadata(store_type: str = "gnss_store") -> StoreMetadata:
    suffix = "gnss" if store_type == "gnss_store" else "vod"
    return StoreMetadata(
        identity=StoreIdentity(
            id=f"rosalia-{suffix}",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="at.ac.tuwien",
            stac_link="../../x/x/x.json",
            title="Rosalia GNSS Store",
            store_type=store_type,
            source_format="rinex3",
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
        spatial=SpatialExtent(site=SiteInfo(name="Rosalia"), geospatial_lat=47.7),
        instruments=Instruments(
            receivers={"canopy_01": ReceiverInfo(type="canopy", directory="c")}
        ),
        vod_analyses={
            "a": VodAnalysisInfo(canopy_receiver="canopy_01", reference_receiver="r")
        }
        if store_type == "vod_store"
        else {},
    )


def _store(tmp_path: Path, store_type: str = "gnss_store") -> Path:
    path = tmp_path / "store"
    icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))
    write_metadata(path, _metadata(store_type))
    return path


def _repository(path: Path) -> dict:
    return icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(path))
    ).get_metadata()


def _amend(path: Path, changes: dict, reason: str = "a better title") -> str:
    return amend_metadata(path, changes, reason=reason, config=_CONFIG)


class TestAmend:
    def test_an_amendment_changes_the_field_and_records_it(self, tmp_path):
        path = _store(tmp_path)

        _amend(path, {"identity.title": "Rosalia GNSS"})

        repository = _repository(path)
        assert repository["identity"]["title"] == "Rosalia GNSS"
        (record,) = repository["amendments"]
        assert record["field"] == "identity.title"
        assert record["old"] == "Rosalia GNSS Store"
        assert record["new"] == "Rosalia GNSS"
        assert record["reason"] == "a better title"
        assert "@" in record["who"]
        assert record["when"]

    def test_an_amendment_commits_the_new_root_copy(self, tmp_path):
        path = _store(tmp_path)

        _amend(path, {"identity.title": "Rosalia GNSS"})

        session = icechunk.Repository.open(
            storage=icechunk.local_filesystem_storage(str(path))
        ).readonly_session(branch="main")
        assert zarr.open_group(session.store, mode="r").attrs["title"] == "Rosalia GNSS"
        assert read_metadata(path).identity.title == "Rosalia GNSS"

    def test_several_fields_in_one_amendment(self, tmp_path):
        path = _store(tmp_path)

        _amend(
            path,
            {"creator.email": "new@example.org", "spatial.geospatial_lat": 47.71},
            reason="corrections",
        )

        repository = _repository(path)
        assert repository["creator"]["email"] == "new@example.org"
        assert repository["spatial"]["geospatial_lat"] == 47.71
        assert [a["field"] for a in repository["amendments"]] == [
            "creator.email",
            "spatial.geospatial_lat",
        ]

    def test_a_fixed_field_is_refused(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(
            ValueError,
            match="a store with a different id is a different store: create a new one",
        ):
            _amend(path, {"identity.id": "other-gnss"})
        assert _repository(path)["identity"]["id"] == "rosalia-gnss"

    def test_an_amendment_needs_a_reason(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match="reason"):
            _amend(path, {"identity.title": "x"}, reason="  ")

    def test_a_field_computed_by_every_commit_is_refused(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match="computed"):
            _amend(path, {"summaries.total_epochs": 3})

    def test_an_unknown_field_is_refused(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match="identity.titel"):
            _amend(path, {"identity.titel": "x"})

    def test_an_invalid_value_changes_nothing(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match="spatial.geospatial_lat"):
            _amend(path, {"spatial.geospatial_lat": "north"})
        assert _repository(path)["amendments"] == []


class TestProtectedLists:
    def test_an_added_receiver_may_be_written(self, tmp_path):
        path = _store(tmp_path)

        _amend(
            path,
            {"instruments.receivers.canopy_02": {"type": "canopy", "directory": "c2"}},
            reason="second canopy receiver installed",
        )

        check_receivers(_repository(path), ["canopy_02"], store_path=path)

    def test_an_added_vod_analysis_may_be_written(self, tmp_path):
        path = _store(tmp_path, "vod_store")

        _amend(
            path,
            {
                "vod_analyses.b": {
                    "canopy_receiver": "canopy_02",
                    "reference_receiver": "r",
                }
            },
            reason="second canopy receiver installed",
        )

        check_vod_analyses(_repository(path), ["a", "b"], store_path=path)


class TestDeprecations:
    def test_update_metadata_warns_and_names_amend_metadata(self, tmp_path):
        path = _store(tmp_path)
        with pytest.warns(FutureWarning, match="amend_metadata"):
            update_metadata(path, {"temporal.updated": "x"})

    def test_apply_updates_warns_and_still_works(self):
        with pytest.warns(FutureWarning, match="amend_metadata"):
            updated = apply_updates(_metadata(), {"identity.title": "x"})
        assert updated.identity.title == "x"
