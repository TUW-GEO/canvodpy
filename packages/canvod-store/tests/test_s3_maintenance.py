"""Maintenance on a store on S3 is a dry run only (#357).

Against a real S3 service, like ``canvodpy/tests/test_s3_run.py`` and the
store tests of canvod-store-metadata (``test_s3_store.py``): CI runs them
against an S3 emulator (RustFS, ``.github/workflows/test_s3.yml``). They
need ``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket that exists)
and the ``AWS_*`` variables the service needs; without the URL they are
skipped.

On S3 a store may have writers on several machines, and maintenance only
knows the runs of its own machine (``is_pipeline_running``), so every
maintenance action that changes the store is refused by
:class:`~canvod.store.MaintenanceOnS3Error`; the garbage-collection dry
run and ``maintenance_due`` keep working because they change nothing.
"""

from __future__ import annotations

import os
import uuid

import pytest
import zarr
from canvod.store_metadata import open_repository, store_location
from canvod.store_metadata.location import S3StoreLocation

from canvod.store import (
    MaintenanceOnS3Error,
    MyIcechunkStore,
)

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

pytestmark = pytest.mark.integration
needs_s3 = pytest.mark.skipif(
    not S3_URL,
    reason=(
        "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
        "AWS_* variables to run the S3 tests (see the module docstring)."
    ),
)


@pytest.fixture
def s3_location() -> S3StoreLocation:
    """A new, empty store location under ``CANVOD_TEST_S3_URL``."""
    root = store_location(S3_URL)
    assert isinstance(root, S3StoreLocation)
    return root / f"maint-{uuid.uuid4().hex}"


@pytest.fixture
def s3_store(s3_location: S3StoreLocation) -> MyIcechunkStore:
    """An opened store on S3 with one commit, so it has a history."""
    repo = open_repository(s3_location, create=True)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="a").attrs["writer"] = "seed"
    session.commit("seed")
    return MyIcechunkStore(s3_location, store_type="gnss_store")


@needs_s3
def test_every_mutating_maintenance_action_is_refused(s3_store) -> None:
    """Each action that would change the store raises and changes nothing."""
    before_ops = [str(update.kind) for update in s3_store.repo.ops_log()]
    before_snaps = [snap.id for snap in s3_store.repo.ancestry(branch="main")]

    for action in (
        lambda: s3_store.expire_old_snapshots(days=30),
        lambda: s3_store.garbage_collect(days=30, dry_run=False),
        lambda: s3_store.compact_manifests(),
        lambda: s3_store.maintenance(expire_days=30),
        lambda: s3_store.cleanup_stale_branches(),
    ):
        with pytest.raises(MaintenanceOnS3Error):
            action()

    after_ops = [str(update.kind) for update in s3_store.repo.ops_log()]
    after_snaps = [snap.id for snap in s3_store.repo.ancestry(branch="main")]
    assert after_ops == before_ops
    assert after_snaps == before_snaps


@needs_s3
def test_gc_dry_run_still_works_on_s3(s3_store) -> None:
    """``garbage_collect(dry_run=True)`` changes nothing and reports."""
    before_ops = [str(update.kind) for update in s3_store.repo.ops_log()]

    summary = s3_store.garbage_collect(days=30, dry_run=True)

    assert summary["dry_run"] is True
    assert "bytes_deleted" in summary
    after_ops = [str(update.kind) for update in s3_store.repo.ops_log()]
    assert after_ops == before_ops


@needs_s3
def test_maintenance_due_still_works_on_s3(s3_store) -> None:
    """``maintenance_due`` reads the ops log and changes nothing."""
    before_ops = [str(update.kind) for update in s3_store.repo.ops_log()]

    due = s3_store.maintenance_due(expire_interval_days=45, gc_delay_days=20)

    assert set(due) == {
        "expire_due",
        "gc_due",
        "manifests_due",
        "last_expire",
        "last_gc",
        "manifest_count",
    }
    assert due["expire_due"] is True  # never maintained
    assert due["gc_due"] is False  # GC is never due before an expiry
    assert due["manifests_due"] is False  # dir_entry_counts is {} on S3
    assert due["manifest_count"] is None
    after_ops = [str(update.kind) for update in s3_store.repo.ops_log()]
    assert after_ops == before_ops
