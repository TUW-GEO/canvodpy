"""Move a store written before ADR 0014 to repository metadata.

Such a store keeps all its metadata in one root attribute,
``canvod_metadata``. :func:`migrate_metadata` writes its fixed and
amendable fields into the repository metadata, with the store id, UUID and
catalog link of ADR 0015, and commits the root copy in the current form.
The old id is kept in the migration record; snapshots from before the
migration keep their old attribute and stay readable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import zarr
from zarr import errors as zarr_errors

from .identity import check_naming_authority, new_uuid, stac_link, store_id
from .io import _open_repo, commit_lock, commit_with_rebase, current_user
from .schema import _METADATA_KEY, MigrationRecord, RepositoryMetadata, StoreMetadata


def migrate_metadata(
    store_path: Path,
    *,
    naming_authority: str | None = None,
    branch: str = "main",
) -> str:
    """Move a store's metadata to repository metadata (ADR 0014).

    Parameters
    ----------
    naming_authority
        The naming authority (reverse DNS) for a store whose metadata has
        none; otherwise the store's own is kept.
    branch
        The branch whose metadata is migrated.

    Returns
    -------
    str
        Snapshot ID of the migration commit.

    Raises
    ------
    ValueError
        If the store is already migrated, holds no store metadata, or has
        no valid naming authority and none is given.
    """
    store_path = Path(store_path)
    with commit_lock(store_path):
        repo = _open_repo(store_path)
        existing = repo.get_metadata()
        if existing:
            msg = (
                f"The store at {store_path} is already migrated "
                f"(store {existing.get('identity', {}).get('id', 'unknown id')})."
            )
            raise ValueError(msg)

        session = repo.readonly_session(branch=branch)
        try:
            attrs = dict(zarr.open_group(session.store, mode="r").attrs)
        except zarr_errors.GroupNotFoundError:
            attrs = {}
        if _METADATA_KEY not in attrs:
            msg = (
                f"The store at {store_path} has no store metadata to migrate "
                f"(no {_METADATA_KEY} attribute on branch {branch!r})."
            )
            raise ValueError(msg)
        old = StoreMetadata._from_old_root_attrs(attrs)

        authority = naming_authority or old.identity.naming_authority
        try:
            authority = check_naming_authority(authority)
        except ValueError:
            msg = (
                f"The store at {store_path} has no valid naming authority "
                f"({authority!r}). Give one with --naming-authority (in Python: "
                "naming_authority=), your institution's domain in reverse order, "
                "e.g. 'at.ac.tuwien'."
            )
            raise ValueError(msg) from None

        store_type = old.identity.store_type
        new_id = store_id(old.spatial.site.name, store_type)
        migrated = old.model_copy(
            update={
                "identity": old.identity.model_copy(
                    update={
                        "id": new_id,
                        "uuid": new_uuid(),
                        "naming_authority": authority,
                        "stac_link": stac_link(authority, new_id, store_type),
                    }
                ),
                "migration": MigrationRecord(
                    old_id=old.identity.id,
                    old_metadata_version=old.metadata_version,
                    who=current_user(),
                    when=datetime.now(UTC).isoformat(),
                ),
            }
        )
        repo.set_metadata(
            RepositoryMetadata.from_store_metadata(migrated).model_dump(mode="json")
        )
        return commit_with_rebase(
            repo.writable_session(branch),
            "Migrate store metadata to repository metadata (ADR 0014)",
            store_path=store_path,
            config=old.config,
        )
