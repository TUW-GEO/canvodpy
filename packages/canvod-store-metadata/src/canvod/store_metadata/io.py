"""Read/write metadata to/from Icechunk store root attrs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import icechunk
import zarr
from zarr import errors as zarr_errors

from .schema import _METADATA_KEY, StoreMetadata


def commit_with_rebase(
    session: icechunk.Session,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Commit a session, rebasing it if the branch moved since it was opened.

    Several writers may commit to one store at the same time (e.g. two
    receivers of a site). Without a rebase, the later commit fails with
    ``icechunk.ConflictError``. With ``icechunk.ConflictDetector``, changes
    that do not overlap (e.g. different groups) are rebased onto the new tip;
    overlapping changes still fail with ``icechunk.RebaseFailedError``.

    Every commit in canVODpy goes through this function.

    Returns
    -------
    str
        Snapshot ID from the commit.
    """
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
    """Write metadata to Icechunk store root attrs.

    Returns
    -------
    str
        Snapshot ID from the commit.
    """
    repo = _open_repo(store_path)
    session = repo.writable_session(branch)
    store = session.store
    try:
        root = zarr.open_group(store, mode="r+")
    except zarr_errors.GroupNotFoundError:
        root = zarr.open_group(store, mode="w")

    root.attrs.update(metadata.to_root_attrs())
    return commit_with_rebase(session, "Write store metadata")


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
    return commit_with_rebase(session, "Update store metadata")


def metadata_exists(store_path: Path, branch: str = "main") -> bool:
    """Check if metadata exists in the store."""
    try:
        repo = _open_repo(store_path)
        session = repo.readonly_session(branch=branch)
        store = session.store
        root = zarr.open_group(store, mode="r")
        return _METADATA_KEY in root.attrs
    except Exception:
        return False
