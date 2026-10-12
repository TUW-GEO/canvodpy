"""Amending a store's description (ADR 0014, #205)."""

from pathlib import Path

import icechunk
import pytest
import zarr
from canvod.utils import testing

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
            id=f"fangorn-{suffix}",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../x/x/x.json",
            title="Fangorn GNSS Store",
            store_type=store_type,
            source_format="rinex3",
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
        spatial=SpatialExtent(
            site=SiteInfo(name="Fangorn"), geospatial_lat=testing.LATITUDE
        ),
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


def _amend(
    path: Path,
    changes: dict,
    reason: str = "a better title",
    who: str = testing.PERSON_INITIALS,
) -> str:
    return amend_metadata(path, changes, reason=reason, who=who, config=_CONFIG)


class TestAmend:
    def test_an_amendment_changes_the_field_and_records_it(self, tmp_path):
        path = _store(tmp_path)

        _amend(path, {"identity.title": "Fangorn GNSS"})

        repository = _repository(path)
        assert repository["identity"]["title"] == "Fangorn GNSS"
        (record,) = repository["amendments"]
        assert record["field"] == "identity.title"
        assert record["old"] == "Fangorn GNSS Store"
        assert record["new"] == "Fangorn GNSS"
        assert record["reason"] == "a better title"
        assert record["who"] == testing.PERSON_INITIALS
        assert record["when"]

    def test_a_field_under_an_unset_block_creates_the_block(self, tmp_path):
        path = _store(tmp_path)
        assert (
            _repository(path)["instruments"]["receivers"]["canopy_01"]["antenna"]
            is None
        )

        _amend(
            path,
            {"instruments.receivers.canopy_01.antenna.height_m": 1.5},
            reason="antenna height measured",
        )

        repository = _repository(path)
        antenna = repository["instruments"]["receivers"]["canopy_01"]["antenna"]
        assert antenna["height_m"] == 1.5
        (record,) = repository["amendments"]
        assert record["old"] is None
        assert record["new"] == 1.5

    def test_an_amendment_commits_the_new_root_copy(self, tmp_path):
        path = _store(tmp_path)

        _amend(path, {"identity.title": "Fangorn GNSS"})

        session = icechunk.Repository.open(
            storage=icechunk.local_filesystem_storage(str(path))
        ).readonly_session(branch="main")
        assert zarr.open_group(session.store, mode="r").attrs["title"] == "Fangorn GNSS"
        assert read_metadata(path).identity.title == "Fangorn GNSS"

    def test_several_fields_in_one_amendment(self, tmp_path):
        path = _store(tmp_path)

        _amend(
            path,
            {
                "creator.email": "new@example.org",
                "spatial.geospatial_lat": testing.LATITUDE + 0.01,
            },
            reason="corrections",
        )

        repository = _repository(path)
        assert repository["creator"]["email"] == "new@example.org"
        assert repository["spatial"]["geospatial_lat"] == testing.LATITUDE + 0.01
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
        assert _repository(path)["identity"]["id"] == "fangorn-gnss"

    def test_an_amendment_needs_a_reason(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match="reason"):
            _amend(path, {"identity.title": "x"}, reason="  ")

    def test_an_amendment_needs_who_makes_it(self, tmp_path):
        path = _store(tmp_path)

        with pytest.raises(ValueError, match=r"processing\.metadata\.initials"):
            _amend(path, {"identity.title": "x"}, who=" ")
        assert not _repository(path)["amendments"]

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


def _fail_commits(monkeypatch) -> None:
    """Make every Icechunk commit fail, as a storage failure would."""

    def fail(*args, **kwargs):
        raise icechunk.StorageError("disk full")

    monkeypatch.setattr(icechunk.Session, "commit", fail)


class TestFailedCommit:
    def test_an_amendment_whose_commit_is_refused_changes_nothing(self, tmp_path):
        path = _store(tmp_path)
        session = icechunk.Repository.open(
            storage=icechunk.local_filesystem_storage(str(path))
        ).writable_session("main")
        root = zarr.open_group(session.store, mode="r+")
        copy = dict(root.attrs["canvod:repository_metadata"])
        copy["identity"] = {**copy["identity"], "title": "Edited"}
        root.attrs["canvod:repository_metadata"] = copy
        session.commit("hand edit")
        before = _repository(path)

        with pytest.raises(ValueError, match="edited by hand"):
            _amend(path, {"identity.title": "Fangorn GNSS"})

        assert _repository(path) == before

    def test_an_amendment_whose_commit_fails_can_be_retried(
        self, tmp_path, monkeypatch
    ):
        path = _store(tmp_path)
        before = _repository(path)

        with monkeypatch.context() as patch:
            _fail_commits(patch)
            with pytest.raises(icechunk.StorageError):
                _amend(path, {"identity.title": "Fangorn GNSS"})
        assert _repository(path) == before

        _amend(path, {"identity.title": "Fangorn GNSS"})
        assert len(_repository(path)["amendments"]) == 1


class TestDeprecations:
    def test_update_metadata_warns_and_names_amend_metadata(self, tmp_path):
        path = _store(tmp_path)
        with pytest.warns(FutureWarning, match="amend_metadata"):
            update_metadata(path, {})

    def test_apply_updates_warns_and_still_works(self):
        with pytest.warns(FutureWarning, match="amend_metadata"):
            updated = apply_updates(_metadata(), {"identity.title": "x"})
        assert updated.identity.title == "x"
