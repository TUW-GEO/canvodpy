"""Move a store written before ADR 0014 to repository metadata.

Such a store keeps all its metadata in one root attribute,
``canvod_metadata``. :func:`migrate_metadata` writes its fixed and
amendable fields into the repository metadata, with the store id, UUID and
catalog link of ADR 0015, and commits the root copy in the current form.
The old id is kept in the migration record; snapshots from before the
migration keep their old attribute and stay readable.

A migrated store must pass the standards checks like a new one
(``validate_all(meta, recommended=False)`` is empty): fields an old store
lacks, such as its description, are given at migration time. The caller
can also replace the attributes of variables older versions wrote wrong
(e.g. ``VOD``, which inherited SNR's and theta's attributes).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import zarr
from zarr import errors as zarr_errors

from .amend import check_amendable
from .identity import check_naming_authority, new_uuid, stac_link, store_id
from .io import (
    _apply_updates,
    _open_repo,
    check_who,
    commit_lock,
    commit_with_rebase,
)
from .schema import _METADATA_KEY, MigrationRecord, RepositoryMetadata, StoreMetadata
from .snapshot import preview_metadata
from .validate import validate_all

#: Attributes xarray writes to encode a variable; kept when a variable's
#: attributes are replaced.
_ENCODING_ATTRS = frozenset({"_FillValue", "coordinates"})


def migrate_metadata(
    store_path: Path,
    *,
    who: str,
    naming_authority: str | None = None,
    values: Mapping[str, Any] | None = None,
    variable_attrs: Mapping[str, Mapping[str, Any]] | None = None,
    branch: str = "main",
) -> str:
    """Move a store's metadata to repository metadata (ADR 0014).

    Parameters
    ----------
    who
        Who migrates the store, e.g. ``"NFB"``; recorded in the migration
        record.
    naming_authority
        The naming authority (reverse DNS) for a store whose metadata has
        none; otherwise the store's own is kept.
    values
        Amendable fields to set while migrating, by dotted path, e.g.
        ``{"identity.description": "..."}``: the fields an old store lacks
        to pass the standards checks.
    variable_attrs
        New attributes by variable name, e.g. ``{"VOD": VOD_ATTRS}``. Every
        array of that name gets them in place of its own; xarray's encoding
        attributes (``_FillValue``, ``coordinates``) are kept. The changed
        arrays are listed in the migration record.
    branch
        The branch whose metadata is migrated.

    Returns
    -------
    str
        Snapshot ID of the migration commit.

    Raises
    ------
    ValueError
        If ``who`` is blank, the store is already migrated, holds no store
        metadata, has no
        valid naming authority and none is given, a value names a field
        that cannot be amended, or the migrated store would fail the
        standards checks (the message lists the failures). Nothing is
        written then.
    """
    who = check_who(who)
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
        for field in values or {}:
            check_amendable(field)
        given = _apply_updates(old, dict(values or {}))
        identity = given.identity.model_copy(
            update={
                "id": new_id,
                "uuid": new_uuid(),
                "naming_authority": authority,
                "stac_link": stac_link(authority, new_id, store_type),
            }
        )
        candidate = given.model_copy(update={"identity": identity})
        _refuse_failures(
            preview_metadata(
                zarr.open_group(repo.readonly_session(branch=branch).store, mode="r"),
                RepositoryMetadata.from_store_metadata(candidate).model_dump(
                    mode="json"
                ),
            ),
            store_path,
        )

        session = repo.writable_session(branch)
        replaced = _replace_variable_attrs(
            zarr.open_group(session.store, mode="a"), variable_attrs or {}
        )
        migrated = given.model_copy(
            update={
                "identity": identity,
                "migration": MigrationRecord(
                    old_id=old.identity.id,
                    old_metadata_version=old.metadata_version,
                    who=who,
                    when=datetime.now(UTC).isoformat(),
                    fields_given=sorted(values or {}),
                    variables_replaced=replaced,
                ),
            }
        )
        repo.set_metadata(
            RepositoryMetadata.from_store_metadata(migrated).model_dump(mode="json")
        )
        return commit_with_rebase(
            session,
            "Migrate store metadata to repository metadata (ADR 0014)",
            store_path=store_path,
            config=old.config,
        )


def _refuse_failures(preview: StoreMetadata, store_path: Path) -> None:
    """Refuse a migration whose result would fail the standards checks."""
    failures = [
        issue
        for issues in validate_all(preview, recommended=False).values()
        for issue in issues
    ]
    if failures:
        listed = "\n".join(f"  - {issue}" for issue in failures)
        msg = (
            f"The store at {store_path} would fail the standards checks after "
            f"migration:\n{listed}\n"
            "Give the missing fields with --set FIELD=VALUE (in Python: "
            "values=). ACDD `summary` comes from identity.description, "
            "spatial.bbox from spatial.geospatial_lat and spatial.geospatial_lon."
        )
        raise ValueError(msg)


def _replace_variable_attrs(
    root: zarr.Group, variable_attrs: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Give every array named in ``variable_attrs`` its new attributes.

    Returns the paths of the changed arrays.
    """
    if not variable_attrs:
        return []
    changed = []
    for path, node in root.members(max_depth=None):
        name = path.rsplit("/", 1)[-1]
        if isinstance(node, zarr.Array) and name in variable_attrs:
            kept = {k: v for k, v in node.attrs.items() if k in _ENCODING_ATTRS}
            node.attrs.put({**kept, **variable_attrs[name]})
            changed.append(path)
    return sorted(changed)
