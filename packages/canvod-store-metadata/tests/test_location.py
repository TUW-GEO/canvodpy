"""One function opens a store's repository from its location (#235)."""

from pathlib import Path

import icechunk
import pytest

from canvod.store_metadata import commit_lock, open_repository, store_location
from canvod.store_metadata.io import COMMIT_LOCK_NAME, read_repository_metadata
from canvod.store_metadata.location import LocalStoreLocation, StoreLocation
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


class TestCommitLockTakesALocation:
    def test_a_location_takes_the_lock_in_its_directory(self, tmp_path: Path) -> None:
        with commit_lock(store_location(tmp_path)):
            assert (tmp_path / COMMIT_LOCK_NAME).exists()

    def test_a_location_and_its_path_share_one_lock(self, tmp_path: Path) -> None:
        # Re-entrant in one thread: the same lock, whichever form names it.
        with commit_lock(tmp_path), commit_lock(store_location(str(tmp_path))):
            pass
