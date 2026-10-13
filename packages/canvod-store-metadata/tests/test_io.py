"""Test metadata I/O with temp Icechunk stores."""

import subprocess
import sys
import textwrap
import time

import icechunk
import pytest
import zarr
from structlog.testing import capture_logs

from canvod.store_metadata.io import (
    COMMIT_LOCK_NAME,
    commit_lock,
    commit_with_rebase,
    metadata_exists,
    read_metadata,
    update_metadata,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)
from canvod.store_metadata.snapshot import RESERVED_GROUP
from canvod.store_metadata.testing import give_test_metadata


def _make_metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="test-gnss",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../gnss-observations/org.middle-earth.test-gnss/org.middle-earth.test-gnss.json",
            title="Test Store",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(
            name="Test",
            email="test@example.com",
            institution="TestU",
        ),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="TestSite"),
        ),
    )


def _create_store(path):
    """Create a minimal Icechunk store."""
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")
    return path


def _store_with_metadata(path):
    """A store data may be committed to: one with repository metadata."""
    return give_test_metadata(path)


class TestIO:
    def test_write_and_read_roundtrip(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        meta = _make_metadata()

        write_metadata(store_path, meta)
        restored = read_metadata(store_path)

        for section in ("identity", "creator", "publisher", "references"):
            written = getattr(meta, section).model_dump()
            read = getattr(restored, section).model_dump()
            assert {k: read[k] for k in written if k != "conventions"} == {
                k: v for k, v in written.items() if k != "conventions"
            }
        assert restored.temporal.created == meta.temporal.created

    def test_metadata_exists_false(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        assert not metadata_exists(store_path)

    def test_metadata_exists_true(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        write_metadata(store_path, _make_metadata())
        assert metadata_exists(store_path)

    def test_a_new_store_whose_first_commit_fails_has_no_metadata(
        self, tmp_path, monkeypatch
    ):
        store_path = _create_store(tmp_path / "store")

        def fail(*args, **kwargs):
            raise icechunk.StorageError("disk full")

        with monkeypatch.context() as patch:
            patch.setattr(icechunk.Session, "commit", fail)
            with pytest.raises(icechunk.StorageError):
                write_metadata(store_path, _make_metadata())

        assert not metadata_exists(store_path)
        write_metadata(store_path, _make_metadata())
        assert metadata_exists(store_path)

    def test_metadata_exists_no_store(self, tmp_path):
        assert not metadata_exists(tmp_path / "nonexistent")

    def test_update_metadata_refuses_repository_fields(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        write_metadata(store_path, _make_metadata())

        with pytest.raises(ValueError, match="only by amendment"):
            update_metadata(store_path, {"identity.title": "Another title"})
        assert read_metadata(store_path).identity.title == "Test Store"

    @pytest.mark.parametrize(
        "key", ["temporal.updated", "summaries.file_count", "processing.software"]
    )
    def test_update_metadata_refuses_computed_fields(self, tmp_path, key):
        store_path = _create_store(tmp_path / "store")
        write_metadata(store_path, _make_metadata())
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(store_path))
        )
        tip = repo.lookup_branch("main")

        with pytest.raises(ValueError, match=f"{key}.*computed by every commit"):
            update_metadata(store_path, {key: 5})
        assert repo.lookup_branch("main") == tip

    def test_update_metadata_without_keys_commits(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        write_metadata(store_path, _make_metadata())
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(store_path))
        )
        tip = repo.lookup_branch("main")

        update_metadata(store_path, {})

        assert repo.lookup_branch("main") != tip

    def test_read_missing_raises(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        with pytest.raises(KeyError):
            read_metadata(store_path)


class TestCommitWithRebase:
    """Concurrent sessions on one branch (A25.1)."""

    @staticmethod
    def _write_group(session: icechunk.Session, name: str, value: int) -> None:
        root = zarr.open_group(session.store, mode="a")
        arr = root.require_group(name).create_array("x", shape=(2,), dtype="i4")
        arr[:] = value

    def test_disjoint_groups_both_commit(self, tmp_path):
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(
                str(_store_with_metadata(tmp_path / "store"))
            )
        )
        first = repo.writable_session("main")
        second = repo.writable_session("main")
        self._write_group(first, "reference_01", 1)
        self._write_group(second, "canopy_01", 2)

        commit_with_rebase(first, "first", store_path=tmp_path / "store")
        commit_with_rebase(second, "second", store_path=tmp_path / "store")

        root = zarr.open_group(repo.readonly_session("main").store, mode="r")
        assert root["reference_01/x"][:].tolist() == [1, 1]
        assert root["canopy_01/x"][:].tolist() == [2, 2]

    def test_overlapping_writes_fail_loudly(self, tmp_path):
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(
                str(_store_with_metadata(tmp_path / "store"))
            )
        )
        first = repo.writable_session("main")
        second = repo.writable_session("main")
        self._write_group(first, "reference_01", 1)
        self._write_group(second, "reference_01", 2)

        commit_with_rebase(first, "first", store_path=tmp_path / "store")
        with pytest.raises(icechunk.RebaseFailedError):
            commit_with_rebase(second, "second", store_path=tmp_path / "store")


def _commit_script(store_path, body: str) -> str:
    """Return a Python script that opens the store and runs ``body``."""
    return textwrap.dedent(f"""
        import sys, time
        import icechunk, zarr
        from filelock import FileLock
        from canvod.store_metadata.io import commit_with_rebase
        store_path = {str(store_path)!r}
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(store_path)
        )
    """) + textwrap.dedent(body)


class TestCommitLock:
    """Commits to one store run one after the other, also across processes."""

    def test_commit_waits_for_another_process(self, tmp_path):
        store_path = _store_with_metadata(tmp_path / "store")
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _commit_script(
                    store_path,
                    f"""
                    with FileLock(f"{{store_path}}/{COMMIT_LOCK_NAME}"):
                        print("locked", flush=True)
                        time.sleep(2)
                    """,
                ),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "locked"
            repo = icechunk.Repository.open(
                icechunk.local_filesystem_storage(str(store_path))
            )
            session = repo.writable_session("main")
            zarr.open_group(session.store, mode="a").attrs["x"] = 1
            start = time.monotonic()
            with capture_logs() as logs:
                commit_with_rebase(session, "waits", store_path=store_path)
            assert time.monotonic() - start > 1
            assert logs[0]["event"] == "waiting_for_commit_lock"
        finally:
            holder.wait(timeout=30)

    def test_concurrent_processes_lose_no_commit(self, tmp_path):
        store_path = _store_with_metadata(tmp_path / "store")
        n_processes, n_commits = 4, 5
        workers = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _commit_script(
                        store_path,
                        f"""
                        for i in range({n_commits}):
                            session = repo.writable_session("main")
                            root = zarr.open_group(session.store, mode="a")
                            root.require_group("p{p}_" + str(i))
                            commit_with_rebase(
                                session, "p{p} " + str(i), store_path=store_path
                            )
                        """,
                    ),
                ]
            )
            for p in range(n_processes)
        ]
        assert [w.wait(timeout=120) for w in workers] == [0] * n_processes

        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(store_path))
        )
        root = zarr.open_group(repo.readonly_session("main").store, mode="r")
        written = set(root.group_keys()) - {RESERVED_GROUP}
        assert len(written) == n_processes * n_commits
        # Every commit is on the branch: the n_processes * n_commits commits,
        # the metadata commit and the commit that created the repository.
        ancestry = list(repo.ancestry(branch="main"))
        assert len(ancestry) == n_processes * n_commits + 2

    def test_reentrant_in_one_thread(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        with commit_lock(store_path), commit_lock(store_path):
            # The lock file exists while the lock is held; on Windows,
            # filelock deletes it again on release.
            assert (store_path / COMMIT_LOCK_NAME).exists()
