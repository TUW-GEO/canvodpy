"""Tests for MyIcechunkStore's retention/maintenance capability.

Two bugs fixed
before shipping (expire_old_snapshots overriding safe upstream defaults to
True/True; maintenance() running garbage_collect() twice per call), plus
a new tag-based keeper scheme (create_keeper_tag). These are regression
locks against exactly those bugs, plus basic coverage of the new methods.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import zarr
from canvod.store_metadata.testing import create_test_store

from canvod.store import open_vod_store


class TestExpireOldSnapshotsDefaults:
    def test_delete_flags_default_to_false(self):
        """Regression lock: must match Icechunk's own safe defaults, not
        override them to True (the original bug)."""
        sig = inspect.signature(
            __import__(
                "canvod.store.store", fromlist=["MyIcechunkStore"]
            ).MyIcechunkStore.expire_old_snapshots
        )
        assert sig.parameters["delete_expired_branches"].default is False
        assert sig.parameters["delete_expired_tags"].default is False

    def test_default_days_is_90(self, tmp_path: Path):
        """90 days (weeks-to-months cadence), not the aggressive old default."""
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store.repo = Mock()
        store.repo.expire_snapshots.return_value = set()
        store._logger = Mock()
        store.store_type = "gnss_store"

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.expire_old_snapshots(store, days=None)

        called_cutoff = store.repo.expire_snapshots.call_args.kwargs["older_than"]
        expected = datetime.now(called_cutoff.tzinfo) - timedelta(days=90)
        assert abs((called_cutoff - expected).total_seconds()) < 5

    def test_does_not_call_garbage_collect(self, tmp_path: Path):
        """expire_old_snapshots must be expire-only; GC ownership moved to
        garbage_collect()/maintenance() so it runs exactly once per
        maintenance() call, not twice (the second bug)."""
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store.repo = Mock()
        store.repo.expire_snapshots.return_value = set()
        store._logger = Mock()
        store.store_type = "gnss_store"

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.expire_old_snapshots(store, days=30)

        store.repo.garbage_collect.assert_not_called()


class TestMaintenanceRunsGcExactlyOnce:
    def test_maintenance_defaults(self):
        sig = inspect.signature(
            __import__(
                "canvod.store.store", fromlist=["MyIcechunkStore"]
            ).MyIcechunkStore.maintenance
        )
        assert sig.parameters["expire_days"].default == 90

    def test_gc_called_exactly_once(self, tmp_path: Path):
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(
            return_value={
                "dry_run": False,
                "bytes_deleted": 0,
                "chunks_deleted": 0,
                "manifests_deleted": 0,
                "snapshots_deleted": 0,
                "attributes_deleted": 0,
                "transaction_logs_deleted": 0,
            }
        )

        from canvod.store.store import MyIcechunkStore

        results = MyIcechunkStore.maintenance(
            store, expire_days=30, cleanup_branches=False, run_gc=True
        )

        store.garbage_collect.assert_called_once()
        assert store.garbage_collect.call_args.kwargs["days"] == 30
        assert results["gc_summary"] is not None

    def test_dry_run_gc_passed_through(self, tmp_path: Path):
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(return_value={"dry_run": True})

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.maintenance(store, dry_run_gc=True)

        assert store.garbage_collect.call_args.kwargs["dry_run"] is True

    def test_expire_delete_flags_passed_through(self, tmp_path: Path):
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(return_value={})

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.maintenance(
            store, delete_expired_branches=True, delete_expired_tags=False
        )

        kwargs = store.expire_old_snapshots.call_args.kwargs
        assert kwargs["delete_expired_branches"] is True
        assert kwargs["delete_expired_tags"] is False


class TestGarbageCollectWrapper:
    def test_dry_run_passed_to_repo(self, tmp_path: Path):
        store = Mock()
        store.store_path = tmp_path  # where commit_lock puts its file
        store._logger = Mock()
        store.repo = Mock()
        store.repo.garbage_collect.return_value = Mock(
            bytes_deleted=0,
            chunks_deleted=0,
            manifests_deleted=0,
            snapshots_deleted=0,
            attributes_deleted=0,
            transaction_logs_deleted=0,
        )

        from canvod.store.store import MyIcechunkStore

        result = MyIcechunkStore.garbage_collect(store, days=90, dry_run=True)

        assert store.repo.garbage_collect.call_args.kwargs["dry_run"] is True
        assert result["dry_run"] is True


class TestCreateKeeperTag:
    def test_creates_tag_on_real_store(self, tmp_path: Path) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("canopy")
            group.create_array("data", shape=(3,), dtype="i4")
            group["data"][:] = [1, 2, 3]
            snapshot_id = session.commit("test commit")

        created = store.create_keeper_tag("canopy", "2025001", snapshot_id)

        assert created is True
        assert "keep/canopy/2025001" in store.list_tags()

    def test_duplicate_tag_returns_false_without_raising(self, tmp_path: Path) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            snapshot_id = session.commit("test commit")

        first = store.create_keeper_tag("canopy", "2025001", snapshot_id)
        second = store.create_keeper_tag("canopy", "2025001", snapshot_id)

        assert first is True
        assert second is False


class TestKeeperTagsConfigDefault:
    def test_storage_config_keeper_tags_defaults_false(self):
        from canvod.config.models.storage import StorageConfig

        config = StorageConfig(stores_root_dir="/tmp/canvod-test-stores")
        assert config.keeper_tags is False


class TestMaintenanceConfigDefaults:
    def test_defaults_are_inert(self):
        """Off/dry-run by default, mirroring keeper_tags' shipping precedent."""
        from canvod.config.models.storage import MaintenanceConfig

        config = MaintenanceConfig()
        assert config.enabled is False
        assert config.dry_run_until_confirmed is True
        assert config.retention_days == 90
        assert config.expire_interval_days == 45
        assert config.gc_delay_days == 20
        assert config.manifests_enabled is False
        assert config.manifest_count_threshold == 3000

    def test_nested_under_storage_config(self):
        from canvod.config.models.storage import StorageConfig

        config = StorageConfig(stores_root_dir="/tmp/canvod-test-stores")
        assert config.maintenance.enabled is False


class TestMaintenanceDue:
    """Icechunk maintenance scheduling:
    nothing ever calls expire_old_snapshots()/garbage_collect() on its own.
    maintenance_due() uses the store's own ops log (Icechunk-written,
    can't drift like a separate marker file) as the source of truth for
    "when did maintenance last actually run"."""

    def test_never_maintained_expire_due_gc_not_due(self, tmp_path: Path) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            session.commit("test commit")

        due = store.maintenance_due(expire_interval_days=45, gc_delay_days=20)

        assert due["expire_due"] is True
        assert due["gc_due"] is False, "GC must never be due before any expire ran"
        assert due["last_expire"] is None
        assert due["last_gc"] is None

    def test_expire_writes_ops_log_entry_even_when_nothing_expired(
        self, tmp_path: Path
    ) -> None:
        """Empirically confirmed 2026-07-20: expire_old_snapshots() always
        writes ExpirationRan, even when the expired set is empty (root/tip
        snapshots are protected) -- so due-checking doesn't need to special
        -case "nothing was actually expired"."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            session.commit("test commit")

        expired = store.expire_old_snapshots(days=0)
        assert expired == set()  # nothing eligible (root/tip protected)

        due = store.maintenance_due(expire_interval_days=45, gc_delay_days=20)
        assert due["expire_due"] is False
        assert due["last_expire"] is not None

    def test_gc_due_only_after_delay_elapses_past_expiration(
        self, tmp_path: Path
    ) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            session.commit("test commit")

        store.expire_old_snapshots(days=0)

        not_yet = store.maintenance_due(expire_interval_days=45, gc_delay_days=20)
        assert not_yet["gc_due"] is False, "delay hasn't elapsed yet"

        now_due = store.maintenance_due(expire_interval_days=45, gc_delay_days=0)
        assert now_due["gc_due"] is True

    def test_gc_not_due_again_after_it_already_ran(self, tmp_path: Path) -> None:
        """dry_run=True GC must NOT count as having run (confirmed
        empirically: garbage_collect(dry_run=True) writes no GCRan entry) --
        only a real GC should clear gc_due."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            session.commit("test commit")

        store.expire_old_snapshots(days=0)

        store.garbage_collect(days=0, dry_run=True)
        still_due = store.maintenance_due(expire_interval_days=45, gc_delay_days=0)
        assert still_due["gc_due"] is True, "dry-run GC must not clear gc_due"

        store.garbage_collect(days=0, dry_run=False)
        no_longer_due = store.maintenance_due(expire_interval_days=45, gc_delay_days=0)
        assert no_longer_due["gc_due"] is False


class TestManifestCompaction:
    """Manifest fragmentation:
    canvodpy's one-to_icechunk()-call-per-file write pattern creates one
    new manifest per flush; rewrite_manifests() was documented but never
    invoked anywhere. Unlike expire/GC, due-ness here is measured
    directly from on-disk manifest count (no distinguishing ops-log
    entry exists for rewrite_manifests() -- it logs as an ordinary
    NewCommit)."""

    def _make_fragmented_store(self, tmp_path: Path, n_commits: int = 5):
        import numpy as np
        import xarray as xr
        from icechunk.xarray import to_icechunk

        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))
        with store.writable_session() as session:
            for i in range(n_commits):
                ds = xr.Dataset(
                    {"x": (("epoch",), np.arange(3.0) + i)},
                    coords={"epoch": np.arange(i * 3, i * 3 + 3)},
                )
                if i == 0:
                    to_icechunk(ds, session, group="canopy", mode="w")
                else:
                    to_icechunk(ds, session, group="canopy", append_dim="epoch")
            session.commit("fragmented write")
        return store

    def test_manifest_count_threshold_none_never_due(self, tmp_path: Path) -> None:
        """manifests_enabled=False -> caller passes threshold=None ->
        manifests_due always False, regardless of actual fragmentation."""
        store = self._make_fragmented_store(tmp_path)
        due = store.maintenance_due(
            expire_interval_days=45, gc_delay_days=20, manifest_count_threshold=None
        )
        assert due["manifests_due"] is False
        assert due["manifest_count"] is None

    def test_manifest_count_threshold_triggers_when_exceeded(
        self, tmp_path: Path
    ) -> None:
        store = self._make_fragmented_store(tmp_path, n_commits=5)
        counts = store.dir_entry_counts()
        assert counts.get("manifests", 0) >= 1, "sanity: fragmented store has manifests"

        due_low = store.maintenance_due(
            expire_interval_days=45, gc_delay_days=20, manifest_count_threshold=1
        )
        assert due_low["manifests_due"] is True
        assert due_low["manifest_count"] == counts["manifests"]

        due_high = store.maintenance_due(
            expire_interval_days=45,
            gc_delay_days=20,
            manifest_count_threshold=10_000_000,
        )
        assert due_high["manifests_due"] is False

    def test_compact_manifests_succeeds_without_error(self, tmp_path: Path) -> None:
        store = self._make_fragmented_store(tmp_path, n_commits=8)

        snapshot_id = store.compact_manifests(branch="main")

        assert isinstance(snapshot_id, str) and snapshot_id
        after = store.dir_entry_counts()["manifests"]
        # rewrite_manifests() adds one new manifest set and a new commit;
        # old per-flush manifests remain on disk until GC, but the *live*
        # branch tip reads from the consolidated set -- assert compaction
        # ran (new snapshot) and didn't error, not a specific count delta
        # (that depends on GC, out of scope here).
        assert after >= 1

    def test_compact_manifests_data_unchanged_after_compaction(
        self, tmp_path: Path
    ) -> None:
        """The whole point is compaction must be data-invisible -- a
        read after compact_manifests() must return identical data."""
        store = self._make_fragmented_store(tmp_path, n_commits=4)
        before = store.read_group("canopy")

        store.compact_manifests(branch="main")

        after = store.read_group("canopy")
        assert before["x"].values.tolist() == after["x"].values.tolist()
        assert before["epoch"].values.tolist() == after["epoch"].values.tolist()


class TestCompactionRecordsCommitMetadata:
    """A compaction commit carries commit metadata like every other commit."""

    def _store_with_metadata(self, path: Path):
        import icechunk
        import numpy as np
        import xarray as xr
        from canvod.config import load_config
        from canvod.store_metadata import (
            collect_config_snapshot,
            commit_with_rebase,
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
        from icechunk.xarray import to_icechunk

        from canvod.store import MyIcechunkStore

        settings = load_config()
        icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))
        write_metadata(
            path,
            StoreMetadata(
                identity=StoreIdentity(
                    id="fangorn-vod",
                    uuid="00000000-0000-4000-8000-000000000001",
                    naming_authority="org.middle-earth",
                    stac_link="../../vod/x/x.json",
                    title="Fangorn VOD Store",
                    store_type="vod_store",
                    source_format="rinex3",
                ),
                creator=Creator(name="T", email="t@example.org", institution="U"),
                temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
                spatial=SpatialExtent(site=SiteInfo(name="Fangorn")),
                config=collect_config_snapshot(settings),
            ),
        )
        store = MyIcechunkStore(path, store_type="vod_store", config=settings)
        for i in range(3):
            with store.writable_session() as session:
                ds = xr.Dataset(
                    {"x": (("epoch",), np.arange(3.0) + i)},
                    coords={
                        "epoch": np.datetime64("2025-01-01T00:00:00", "s")
                        + np.arange(i * 3, i * 3 + 3) * np.timedelta64(5, "s")
                    },
                )
                kwargs = {"mode": "w"} if i == 0 else {"append_dim": "epoch"}
                to_icechunk(ds, session, group="canopy", **kwargs)
                commit_with_rebase(
                    session, f"write {i}", store_path=path, config=settings
                )
        return store

    def _tip_metadata(self, store) -> dict:
        tip = store.repo.lookup_branch("main")
        return next(iter(store.repo.ancestry(snapshot_id=tip))).metadata

    def test_the_compaction_commit_has_commit_metadata(self, tmp_path: Path):
        from canvod.store_metadata import read_metadata, validate_all

        store = self._store_with_metadata(tmp_path / "store")
        before = validate_all(read_metadata(store.store_path), recommended=False)

        store.compact_manifests(branch="main")

        metadata = self._tip_metadata(store)
        assert {"processing", "environment", "config"} <= metadata.keys()
        assert "__icechunk" in metadata  # Icechunk's own splitting_config
        meta = read_metadata(store.store_path)
        assert meta.processing.software
        assert meta.config.config_hash
        assert validate_all(meta, recommended=False) == before

    def test_every_commit_carries_commit_metadata(self, tmp_path: Path):
        store = self._store_with_metadata(tmp_path / "store")
        store.compact_manifests(branch="main")

        commits = list(store.repo.ancestry(branch="main"))[:-1]  # not the first

        assert len(commits) == 5  # metadata, 3 writes, compaction
        for commit in commits:
            assert "environment" in commit.metadata, commit.message

    def test_a_new_lockfile_is_stored_before_compaction(
        self, tmp_path: Path, monkeypatch
    ):
        from canvod.store_metadata import read_metadata

        store = self._store_with_metadata(tmp_path / "store")
        project = tmp_path / "fangorn"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "fangorn"\n')
        (project / "uv.lock").write_bytes(b"version = 1\nrevision = 3\n")
        monkeypatch.chdir(project)

        store.compact_manifests(branch="main")

        meta = read_metadata(store.store_path)
        assert meta.environment.uv_lock_text == "version = 1\nrevision = 3\n"
