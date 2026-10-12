"""What writers check before they write data (ADR 0014, #203)."""

from pathlib import Path

import icechunk
import pytest
import zarr

from canvod.store_metadata import (
    check_receivers,
    check_vod_analyses,
    ensure_metadata,
    metadata_exists,
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


def _metadata(store_type: str = "gnss_store") -> StoreMetadata:
    suffix = "gnss" if store_type == "gnss_store" else "vod"
    return StoreMetadata(
        identity=StoreIdentity(
            id=f"fangorn-{suffix}",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../x/x/x.json",
            title="Fangorn",
            store_type=store_type,
            source_format="rinex3",
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
        spatial=SpatialExtent(site=SiteInfo(name="Fangorn")),
        instruments=Instruments(
            receivers={
                "canopy_01": ReceiverInfo(type="canopy", directory="c"),
                "reference_01": ReceiverInfo(type="reference", directory="r"),
            }
        ),
        vod_analyses={
            "canopy_01_vs_reference_01": VodAnalysisInfo(
                canopy_receiver="canopy_01", reference_receiver="reference_01"
            )
        }
        if store_type == "vod_store"
        else {},
    )


def _new_store(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))
    return path


def _ensure(path: Path, metadata: StoreMetadata | None = None) -> dict:
    meta = metadata or _metadata()
    return ensure_metadata(
        path,
        lambda: meta,
        site_name="Fangorn",
        store_type=meta.identity.store_type,
    )


class TestEnsureMetadata:
    def test_a_new_store_gets_its_metadata(self, tmp_path):
        path = _new_store(tmp_path)

        repository = _ensure(path)

        assert repository["identity"]["id"] == "fangorn-gnss"
        assert metadata_exists(path)

    def test_a_store_with_metadata_is_not_collected_again(self, tmp_path):
        path = _new_store(tmp_path)
        _ensure(path)

        def fail():
            msg = "collected again"
            raise AssertionError(msg)

        repository = ensure_metadata(
            path, fail, site_name="Fangorn", store_type="gnss_store"
        )
        assert repository["identity"]["id"] == "fangorn-gnss"

    def test_a_store_with_old_metadata_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="w").attrs["canvod_metadata"] = {"x": 1}
        session.commit("old form")

        with pytest.raises(
            ValueError, match="canvodpy store migrate-metadata Fangorn --store gnss"
        ):
            _ensure(path)
        assert not metadata_exists(path)

    def test_a_store_with_data_but_no_metadata_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="w").require_group("canopy_01")
        session.commit("data without metadata")

        with pytest.raises(ValueError, match="canvodpy store migrate-metadata"):
            _ensure(path)


class TestListedReceivers:
    def test_listed_receivers_and_their_pair_groups_pass(self, tmp_path):
        path = _new_store(tmp_path)
        repository = _ensure(path)

        check_receivers(
            repository, ["canopy_01", "reference_01_canopy_01"], store_path=path
        )

    def test_an_unlisted_receiver_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        repository = _ensure(path)

        with pytest.raises(ValueError, match="--add-receiver canopy_02") as excinfo:
            check_receivers(repository, ["canopy_02"], store_path=path)
        assert "canvodpy store amend Fangorn --store gnss" in str(excinfo.value)

    def test_an_unlisted_vod_analysis_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        repository = _ensure(path, _metadata("vod_store"))

        check_vod_analyses(repository, ["canopy_01_vs_reference_01"], store_path=path)
        with pytest.raises(ValueError, match="--add-vod-analysis canopy_02_vs_ref"):
            check_vod_analyses(repository, ["canopy_02_vs_ref"], store_path=path)
