"""What writers check before they write data (ADR 0014, #203)."""

import threading
from pathlib import Path

import icechunk
import pytest
import zarr
from canvod.utils import testing

from canvod.store_metadata import (
    check_receivers,
    check_vod_analyses,
    commit_with_rebase,
    ensure_metadata,
    ensure_store_metadata,
    metadata_exists,
    open_repository,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    Instruments,
    ReceiverInfo,
    RepositoryMetadata,
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


def _new_store(tmp_path: Path, name: str = "gnss") -> Path:
    path = tmp_path / name
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
    def test_a_missing_store_is_created_with_the_configuration(self, tmp_path):
        config = icechunk.RepositoryConfig.default()
        config.inline_chunk_threshold_bytes = 17
        meta = _metadata()

        repository = ensure_metadata(
            tmp_path / "gnss",
            lambda: meta,
            site_name="Fangorn",
            store_type=meta.identity.store_type,
            config=config,
        )

        assert repository["identity"]["id"] == "fangorn-gnss"
        reopened = open_repository(tmp_path / "gnss")
        assert reopened.config.inline_chunk_threshold_bytes == 17

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

    def test_a_store_another_run_created_meanwhile_is_used(self, tmp_path):
        """Two runs found the store without metadata; the other one wrote it
        first. This run goes on with the other run's store (#358).
        """
        path = _new_store(tmp_path)
        other = _metadata().model_copy(deep=True)
        other.identity.id = "fangorn-other-run"

        def collect_while_the_other_run_creates_it():
            write_metadata(path, other)
            return _metadata()

        repository = ensure_metadata(
            path,
            collect_while_the_other_run_creates_it,
            site_name="Fangorn",
            store_type="gnss_store",
        )

        assert repository["identity"]["id"] == "fangorn-other-run"
        assert open_repository(path).get_metadata()["identity"]["id"] == (
            "fangorn-other-run"
        )

    def test_a_creation_commit_of_another_run_is_not_replaced(self, tmp_path):
        """The other run committed the store's creation but has not written
        its repository metadata yet: this run waits for it and uses it, and
        does not create the store a second time (#358).
        """
        path = _new_store(tmp_path)
        other = RepositoryMetadata.from_store_metadata(_metadata()).model_dump(
            mode="json"
        )
        other["identity"]["id"] = "fangorn-other-run"

        def collect_after_the_other_runs_creation_commit():
            repo = open_repository(path)
            session = repo.writable_session("main")
            zarr.open_group(session.store, mode="a")
            commit_with_rebase(
                session,
                "Write store metadata",
                store_path=path,
                config=_metadata().config,
                repository=other,
            )
            threading.Timer(0.5, repo.set_metadata, args=(other,)).start()
            return _metadata()

        repository = ensure_metadata(
            path,
            collect_after_the_other_runs_creation_commit,
            site_name="Fangorn",
            store_type="gnss_store",
        )

        assert repository["identity"]["id"] == "fangorn-other-run"
        repo = open_repository(path)
        assert repo.get_metadata()["identity"]["id"] == "fangorn-other-run"
        creations = [
            snapshot
            for snapshot in repo.ancestry(branch="main")
            if snapshot.message == "Write store metadata"
        ]
        assert len(creations) == 1

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

    @pytest.mark.parametrize(
        "name", ["canopy_01_b", "reference_01_b", "reference_01_canopy_02"]
    )
    def test_a_name_extending_a_listed_receiver_is_refused(self, tmp_path, name):
        path = _new_store(tmp_path)
        repository = _ensure(path)

        with pytest.raises(ValueError, match=f"--add-receiver {name}"):
            check_receivers(repository, [name], store_path=path)

    def test_an_unlisted_vod_analysis_is_refused(self, tmp_path):
        path = _new_store(tmp_path, "vod")
        repository = _ensure(path, _metadata("vod_store"))

        check_vod_analyses(repository, ["canopy_01_vs_reference_01"], store_path=path)
        with pytest.raises(ValueError, match="--add-vod-analysis canopy_02_vs_ref"):
            check_vod_analyses(repository, ["canopy_02_vs_ref"], store_path=path)


class TestStoreFolder:
    """A store's id ends in its folder name (#456)."""

    def test_a_store_whose_folder_was_renamed_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        _ensure(path)
        renamed = path.rename(tmp_path / "gnss-renamed")

        with pytest.raises(ValueError, match="renamed after the store was created"):
            _ensure(renamed)

    def test_a_store_in_the_old_gnss_folder_names_the_migrate_command(self, tmp_path):
        path = _new_store(tmp_path)
        _ensure(path)
        renamed = path.rename(tmp_path / "rinex")

        with pytest.raises(ValueError, match="canvodpy store migrate SITE"):
            _ensure(renamed)


class TestStoreRefusesDataWithoutMetadata:
    def test_a_commit_to_a_store_without_metadata_is_refused(self, tmp_path):
        path = _new_store(tmp_path)
        repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
        before = repo.lookup_branch("main")
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="w").require_group("canopy_01")

        with pytest.raises(ValueError, match="no repository metadata") as excinfo:
            commit_with_rebase(session, "data", store_path=path)

        assert "canvodpy store migrate-metadata" in str(excinfo.value)
        assert repo.lookup_branch("main") == before

    def test_a_commit_to_a_store_with_metadata_is_written(self, tmp_path):
        path = _new_store(tmp_path)
        _ensure(path)
        repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="a").require_group("canopy_01")

        commit_with_rebase(session, "data", store_path=path, config={"processing": {}})

        assert "canopy_01" in dict(
            zarr.open_group(
                repo.readonly_session(branch="main").store, mode="r"
            ).groups()
        )


def _settings(tmp_path: Path):
    """The made-up settings, with what a new store needs from its site."""
    from canvod.config import load_config
    from canvod.config.models import ReceiverConfig, VodAnalysisConfig

    folder = tmp_path / "settings"
    testing.write_settings(folder)
    config = load_config(config_dir=folder).model_copy(deep=True)
    site = config.sites.sites[testing.SITE_KEY]
    site.store_description = "GNSS-T observations below an Ent canopy"
    site.receivers["reference_01"] = ReceiverConfig(
        type="reference", directory="01_reference", paired_canopies=["canopy_01"]
    )
    site.vod_analyses = {
        "canopy_01_vs_reference_01": VodAnalysisConfig(
            canopy_receiver="canopy_01", reference_receiver="reference_01"
        )
    }
    return config


def _gnss_repository(tmp_path: Path):
    """The repository metadata of a made-up GNSS store with content settings."""
    return ensure_store_metadata(
        _new_store(tmp_path / "gnss"),
        config=_settings(tmp_path),
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=["canopy_01", "reference_01_canopy_01"],
    )


def _ensure_store(tmp_path: Path, store_type: str, names: list[str]) -> dict:
    return ensure_store_metadata(
        _new_store(tmp_path, store_type.removesuffix("_store")),
        config=_settings(tmp_path),
        site_name=testing.SITE_KEY,
        store_type=store_type,
        source_format="rinex3",
        names=names,
        gnss_repository=(
            _gnss_repository(tmp_path) if store_type == "vod_store" else None
        ),
    )


class TestMetadataFirst:
    """The step every run takes before it writes data."""

    def test_a_new_gnss_store_gets_the_receivers_of_the_settings(self, tmp_path):
        repository = _ensure_store(
            tmp_path, "gnss_store", ["canopy_01", "reference_01_canopy_01"]
        )

        assert repository["identity"]["id"] == f"{testing.SITE_KEY}-gnss"
        assert set(repository["instruments"]["receivers"]) == {
            "canopy_01",
            "reference_01",
        }
        assert metadata_exists(tmp_path / "gnss")

    def test_an_unlisted_receiver_is_refused_with_the_amend_command(self, tmp_path):
        with pytest.raises(ValueError, match="--add-receiver canopy_02"):
            _ensure_store(tmp_path, "gnss_store", ["canopy_02"])

    def test_a_new_vod_store_gets_the_vod_analyses_of_the_settings(self, tmp_path):
        repository = _ensure_store(tmp_path, "vod_store", ["canopy_01_vs_reference_01"])

        assert set(repository["vod_analyses"]) == {"canopy_01_vs_reference_01"}

    def test_an_unlisted_vod_analysis_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="--add-vod-analysis vod_result"):
            _ensure_store(tmp_path, "vod_store", ["vod_result"])

    def test_a_site_not_in_the_settings_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match=r"sites\.isengard"):
            ensure_store_metadata(
                _new_store(tmp_path),
                config=_settings(tmp_path),
                site_name="isengard",
                store_type="gnss_store",
                source_format="rinex3",
                names=["canopy_01"],
            )
