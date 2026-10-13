"""One function opens a store's repository from its location (#235)."""

import os
from pathlib import Path

import icechunk
import pytest
from canvod.config.models.compression import IcechunkConfig

from canvod.store_metadata import (
    commit_lock,
    open_repository,
    read_store_uuid,
    repository_config,
    store_exists,
    store_location,
)
from canvod.store_metadata.io import (
    COMMIT_LOCK_NAME,
    metadata_exists,
    read_metadata,
    read_repository_metadata,
)
from canvod.store_metadata.location import (
    LocalStoreLocation,
    S3StoreLocation,
    StoreLocation,
)
from canvod.store_metadata.testing import give_test_metadata


class TestStoreLocation:
    def test_a_path_is_a_local_location(self, tmp_path: Path) -> None:
        location = store_location(tmp_path / "fangorn")

        assert isinstance(location, LocalStoreLocation)
        assert isinstance(location, StoreLocation)
        assert location.path == tmp_path / "fangorn"

    def test_a_string_path_is_a_local_location(self, tmp_path: Path) -> None:
        location = store_location(str(tmp_path / "fangorn"))

        assert location == LocalStoreLocation(tmp_path / "fangorn")

    def test_a_location_is_kept_as_it_is(self, tmp_path: Path) -> None:
        location = LocalStoreLocation(tmp_path)

        assert store_location(location) is location

    def test_a_home_directory_is_expanded(self) -> None:
        assert store_location("~/fangorn").path == Path.home() / "fangorn"

    def test_join_appends_a_relative_path(self, tmp_path: Path) -> None:
        location = store_location(tmp_path) / "fangorn" / "gnss"

        assert location == LocalStoreLocation(tmp_path / "fangorn" / "gnss")

    def test_a_local_location_shows_as_its_path(self, tmp_path: Path) -> None:
        assert str(store_location(tmp_path)) == str(tmp_path)

    def test_local_commits_need_the_commit_lock(self, tmp_path: Path) -> None:
        assert store_location(tmp_path).needs_commit_lock


class TestOpenRepository:
    def test_opens_an_existing_repository(self, tmp_path: Path) -> None:
        store = give_test_metadata(tmp_path / "store")

        repo = open_repository(store)

        assert repo.get_metadata() == read_repository_metadata(store)
        assert repo.get_metadata()["identity"]["id"]

    def test_refuses_a_location_without_a_repository(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-store"

        with pytest.raises(FileNotFoundError, match="no-store"):
            open_repository(missing)

        assert not missing.exists()

    def test_refuses_an_empty_directory(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(FileNotFoundError, match="empty"):
            open_repository(empty)

    def test_creates_a_repository_when_asked(self, tmp_path: Path) -> None:
        location = tmp_path / "new" / "store"

        repo = open_repository(location, create=True)

        assert repo.get_metadata() == {}
        assert icechunk.Repository.exists(
            icechunk.local_filesystem_storage(str(location))
        )

    def test_refuses_to_create_over_an_existing_repository(
        self, tmp_path: Path
    ) -> None:
        store = give_test_metadata(tmp_path / "store")

        with pytest.raises(FileExistsError, match="already"):
            open_repository(store, create=True)

        assert read_repository_metadata(store)["identity"]["id"]

    def test_uses_the_configuration_it_is_given(self, tmp_path: Path) -> None:
        config = icechunk.RepositoryConfig.default()
        config.inline_chunk_threshold_bytes = 17

        repo = open_repository(tmp_path / "store", create=True, config=config)

        assert repo.config.inline_chunk_threshold_bytes == 17

    def test_refuses_to_create_where_other_files_are(self, tmp_path: Path) -> None:
        store = tmp_path / "store"
        store.mkdir()
        (store / "notes.txt").write_text("Entmoot, day 3")

        with pytest.raises(ValueError, match="holds files but no store"):
            open_repository(store, create=True)

        assert sorted(p.name for p in store.iterdir()) == ["notes.txt"]


class TestStoreExists:
    def test_a_missing_location_holds_no_store(self, tmp_path: Path) -> None:
        assert not store_exists(tmp_path / "fangorn")
        assert not (tmp_path / "fangorn").exists()

    def test_an_empty_directory_holds_no_store(self, tmp_path: Path) -> None:
        assert not store_exists(tmp_path)

    def test_a_created_store_exists(self, tmp_path: Path) -> None:
        open_repository(tmp_path / "store", create=True)

        assert store_exists(tmp_path / "store")
        assert store_exists(str(tmp_path / "store"))


class TestRepositoryConfig:
    def test_a_new_store_keeps_the_settings_configuration(self, tmp_path: Path) -> None:
        settings = IcechunkConfig(inline_chunk_threshold_bytes=17)

        open_repository(
            tmp_path / "store", create=True, config=repository_config(settings)
        )

        reopened = open_repository(tmp_path / "store")
        assert reopened.config.inline_chunk_threshold_bytes == 17

    def test_an_unset_cache_size_keeps_the_icechunk_default(self) -> None:
        config = repository_config(IcechunkConfig(cache_num_bytes_chunks=1024))

        default = icechunk.CachingConfig.default()  # ty: ignore[unresolved-attribute]
        assert config.caching.num_bytes_chunks == 1024
        assert config.caching.num_chunk_refs == default.num_chunk_refs

    def test_a_store_created_without_a_configuration_gets_the_settings_defaults(
        self, tmp_path: Path
    ) -> None:
        """Not Icechunk's defaults, which split no manifests along "epoch"."""
        open_repository(tmp_path / "store", create=True)

        reopened = open_repository(tmp_path / "store")
        defaults = repository_config(IcechunkConfig())
        assert reopened.config.manifest == defaults.manifest
        assert (
            reopened.config.get_partial_values_concurrency
            == defaults.get_partial_values_concurrency
        )

    def test_a_compression_level_overrides_the_settings(self) -> None:
        config = repository_config(
            IcechunkConfig(compression_level=3), compression_level=9
        )

        assert config.compression.level == 9


class TestCommitLockTakesALocation:
    def test_a_location_takes_the_lock_in_its_directory(self, tmp_path: Path) -> None:
        with commit_lock(store_location(tmp_path)):
            assert (tmp_path / COMMIT_LOCK_NAME).exists()

    def test_a_location_and_its_path_share_one_lock(self, tmp_path: Path) -> None:
        # Re-entrant in one thread: the same lock, whichever form names it.
        with commit_lock(tmp_path), commit_lock(store_location(str(tmp_path))):
            pass


class TestExpectedStore:
    """A store replaced behind the same location is never taken for the old one."""

    def test_opens_the_expected_store(self, tmp_path: Path) -> None:
        store = give_test_metadata(tmp_path / "store")
        uuid = read_store_uuid(store)

        repo = open_repository(store, expected_uuid=uuid)

        assert repo.get_metadata()["identity"]["uuid"] == uuid

    def test_refuses_another_store_naming_both(self, tmp_path: Path) -> None:
        store = give_test_metadata(tmp_path / "store")
        found = read_store_uuid(store)
        expected = "00000000-0000-4000-8000-00000000beef"

        with pytest.raises(ValueError, match="not the store expected") as error:
            open_repository(store, expected_uuid=expected)

        assert expected in str(error.value)
        assert found in str(error.value)
        assert str(store) in str(error.value)

    def test_refuses_a_store_without_metadata(self, tmp_path: Path) -> None:
        store = tmp_path / "store"
        open_repository(store, create=True)

        with pytest.raises(ValueError, match="migrate-metadata"):
            open_repository(store, expected_uuid="00000000-0000-4000-8000-000000000001")

    def test_reads_the_uuid_from_the_repository_metadata(self, tmp_path: Path) -> None:
        store = give_test_metadata(tmp_path / "store")

        assert (
            read_store_uuid(store)
            == (read_repository_metadata(store)["identity"]["uuid"])
        )

    def test_reading_the_uuid_of_a_store_without_metadata_fails(
        self, tmp_path: Path
    ) -> None:
        store = tmp_path / "store"
        open_repository(store, create=True)

        with pytest.raises(ValueError, match="migrate-metadata"):
            read_store_uuid(store)


class TestS3Locations:
    """Metadata functions open stores on S3 (#237). No network: no MinIO."""

    def test_an_s3_url_names_bucket_and_prefix(self) -> None:
        location = store_location("s3://fangorn/stores/gnss/")

        assert location == S3StoreLocation(bucket="fangorn", prefix="stores/gnss")
        assert str(location) == "s3://fangorn/stores/gnss"

    @pytest.mark.parametrize("url", ["s3://fangorn", "s3://fangorn/", "s3:///gnss"])
    def test_an_s3_url_without_bucket_or_prefix_is_refused(self, url: str) -> None:
        with pytest.raises(ValueError, match="s3://bucket/prefix"):
            store_location(url)

    @pytest.mark.parametrize(
        "url", ["gs://fangorn/gnss", "az://fangorn/gnss", "http://fangorn/gnss"]
    )
    def test_other_schemes_are_refused_naming_the_supported_ones(
        self, url: str
    ) -> None:
        with pytest.raises(ValueError, match="s3://"):
            store_location(url)

    def test_join_keeps_s3(self) -> None:
        location = store_location("s3://fangorn/stores") / "fangorn" / "gnss"

        assert str(location) == "s3://fangorn/stores/fangorn/gnss"

    def test_join_resolves_a_relative_href(self) -> None:
        """S3 doesn't resolve ``..``, so the join does (a catalog item's href)."""
        catalog = store_location("s3://fangorn/catalog/gnss-observations/fangorn")

        location = catalog / "../../../stores/fangorn/gnss"

        assert location == S3StoreLocation("fangorn", "stores/fangorn/gnss")

    @pytest.mark.parametrize("relative", ["../..", "../../elsewhere", "gnss/../.."])
    def test_join_out_of_the_bucket_prefix_is_refused(self, relative: str) -> None:
        with pytest.raises(ValueError, match="s3://fangorn/stores"):
            _ = store_location("s3://fangorn/stores") / relative

    @pytest.mark.parametrize("location", ["s3://fangorn/stores", "/srv/stores"])
    def test_join_of_an_absolute_path_is_refused(self, location: str) -> None:
        with pytest.raises(ValueError, match="relative path"):
            _ = store_location(location) / "/fangorn/gnss"

    def test_s3_has_no_local_directory_and_no_commit_lock(self) -> None:
        location = store_location("s3://fangorn/stores/gnss")

        assert location.local_path is None
        assert not location.needs_commit_lock

    def test_the_commit_lock_does_nothing_on_s3(self, tmp_path: Path) -> None:
        with commit_lock("s3://fangorn/stores/gnss"):
            pass

        assert not any(tmp_path.iterdir())

    @pytest.fixture
    def no_aws_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No credentials anywhere: Icechunk fails before it contacts the
        endpoint. (An endpoint that can't be reached is retried for half a
        minute, so it is not tested here.)"""
        for name in [n for n in os.environ if n.startswith("AWS_")]:
            monkeypatch.delenv(name)
        monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent/config")
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent/credentials")
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
        monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("AWS_REGION", "eu-central-1")

    @pytest.mark.usefixtures("no_aws_credentials")
    def test_a_missing_credential_names_where_credentials_come_from(self) -> None:
        with pytest.raises(OSError, match="s3://fangorn/stores/gnss") as error:
            open_repository("s3://fangorn/stores/gnss")

        assert "~/.aws/credentials" in str(error.value)

    @pytest.mark.usefixtures("no_aws_credentials")
    @pytest.mark.parametrize(
        "read", [read_repository_metadata, read_metadata, metadata_exists]
    )
    def test_metadata_functions_open_s3_through_the_opener(self, read) -> None:
        with pytest.raises(OSError, match="s3://fangorn/stores/gnss"):
            read("s3://fangorn/stores/gnss")
