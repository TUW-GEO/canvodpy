"""Read/write metadata to/from Icechunk store root attrs."""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import icechunk
import structlog
import zarr
from filelock import FileLock, Timeout
from pydantic import ValidationError
from zarr import errors as zarr_errors

from .schema import RepositoryMetadata, StoreMetadata

#: Name of the lock file in the store directory (see :func:`commit_lock`).
COMMIT_LOCK_NAME = ".canvodpy-commit.lock"

_logger = structlog.get_logger(__name__)
_locks: dict[Path, FileLock] = {}
_locks_guard = threading.Lock()


@contextmanager
def commit_lock(store_path: Path | str) -> Generator[None]:
    """Let only one commit at a time change the store at ``store_path``.

    Icechunk on a local file system is not safe for concurrent commits:
    when two commits run at the same time, both can return successfully
    while one of them is lost. This lock, a file in the store directory,
    makes every other commit wait, in this process (other threads) and in
    other processes on the same machine. A commit that waits then sees the
    commit before it, and :func:`commit_with_rebase` rebases onto it.

    The lock is re-entrant in one thread. The operating system releases it
    when the process that holds it ends.
    """
    path = Path(store_path).resolve()
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = _locks[path] = FileLock(path / COMMIT_LOCK_NAME)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        _logger.info("waiting_for_commit_lock", store=str(path))
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def commit_with_rebase(
    session: icechunk.Session,
    message: str,
    metadata: dict[str, Any] | None = None,
    *,
    store_path: Path | str,
) -> str:
    """Commit a session, rebasing it if the branch moved since it was opened.

    The commit holds :func:`commit_lock` for ``store_path``, the store the
    session belongs to, so commits to one store run one after the other.
    Several writers may still work on one store at the same time (e.g. two
    receivers of a site): when the branch moved since a session was opened,
    ``icechunk.ConflictDetector`` rebases changes that do not overlap (e.g.
    different groups) onto the new tip; overlapping changes fail with
    ``icechunk.RebaseFailedError``.

    Every commit in canVODpy goes through this function.

    Returns
    -------
    str
        Snapshot ID from the commit.
    """
    with commit_lock(store_path):
        return session.commit(
            message, metadata=metadata, rebase_with=icechunk.ConflictDetector()
        )


def _open_repo(store_path: Path) -> icechunk.Repository:
    """Open an existing Icechunk repository."""
    storage = icechunk.local_filesystem_storage(str(store_path))
    return icechunk.Repository.open(storage=storage)


def write_metadata(
    store_path: Path,
    metadata: StoreMetadata,
    branch: str = "main",
) -> str:
    """Write a new store's metadata.

    The repository metadata (fixed and amendable fields, ADR 0014) is
    written once; the root group gets the full metadata in the same call.

    Returns
    -------
    str
        Snapshot ID from the commit.

    Raises
    ------
    ValueError
        If the store already has repository metadata, or ``metadata``
        lacks a fixed field (build it with ``collect_metadata``).
    """
    try:
        repository_metadata = RepositoryMetadata.from_store_metadata(metadata)
    except ValidationError as exc:
        missing = sorted(
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()
        )
        msg = (
            f"The store metadata lacks fields a store needs when it is created "
            f"({', '.join(missing)}); build it with collect_metadata."
        )
        raise ValueError(msg) from exc

    with commit_lock(store_path):
        repo = _open_repo(store_path)
        existing = repo.get_metadata()
        if existing:
            store = existing.get("identity", {}).get("id", "unknown id")
            msg = (
                f"The store at {store_path} already has repository metadata "
                f"(store {store}); open it instead of creating it again."
            )
            raise ValueError(msg)
        repo.set_metadata(repository_metadata.model_dump(mode="json"))

        session = repo.writable_session(branch)
        try:
            root = zarr.open_group(session.store, mode="r+")
        except zarr_errors.GroupNotFoundError:
            root = zarr.open_group(session.store, mode="w")
        root.attrs.update(metadata.to_root_attrs())
        return commit_with_rebase(
            session, "Write store metadata", store_path=store_path
        )


def read_metadata(
    store_path: Path,
    branch: str = "main",
) -> StoreMetadata:
    """Read metadata from Icechunk store root attrs.

    Raises
    ------
    KeyError
        If no metadata found in store.
    """
    repo = _open_repo(store_path)
    session = repo.readonly_session(branch=branch)
    store = session.store
    root = zarr.open_group(store, mode="r")
    attrs = dict(root.attrs)
    return StoreMetadata.from_root_attrs(attrs)


def apply_updates(metadata: StoreMetadata, updates: dict[str, Any]) -> StoreMetadata:
    """Return a copy of ``metadata`` with dotted-key ``updates`` applied.

    Keys such as ``"temporal.updated"`` address nested fields.
    """
    data = metadata.model_dump(mode="json")

    for key, value in updates.items():
        parts = key.split(".")
        target = data
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value

    return StoreMetadata.model_validate(data)


def update_metadata(
    store_path: Path,
    updates: dict[str, Any],
    branch: str = "main",
) -> str:
    """Merge updates into existing metadata.

    Supports dotted keys for nested updates (e.g. "temporal.updated").

    Returns
    -------
    str
        Snapshot ID from the commit.
    """
    updated = apply_updates(read_metadata(store_path, branch), updates)

    repo = _open_repo(store_path)
    session = repo.writable_session(branch)
    store = session.store
    try:
        root = zarr.open_group(store, mode="r+")
    except zarr_errors.GroupNotFoundError:
        root = zarr.open_group(store, mode="w")

    root.attrs.update(updated.to_root_attrs())
    return commit_with_rebase(session, "Update store metadata", store_path=store_path)


def metadata_exists(store_path: Path, branch: str = "main") -> bool:
    """Check if the store has repository metadata.

    ``branch`` is not used: repository metadata is on no branch. It stays
    for callers that pass it.
    """
    try:
        repo = _open_repo(store_path)
    except icechunk.IcechunkError:
        return False
    return bool(repo.get_metadata())
