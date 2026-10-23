"""Amending a store's description (ADR 0014).

Amendable fields of the repository metadata change only by amendment:
:func:`amend_metadata` (``canvodpy store amend`` on the command line)
needs a reason and records, per field, the old and new value, the reason,
who and when. Fixed fields never change. One amendment is one change of
the repository metadata plus one commit of the root copy to ``main``.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .io import (
    _field_exists,
    _set_field,
    check_who,
    commit_lock,
    commit_with_rebase,
)
from .location import StoreLocation, open_repository, store_location
from .schema import RepositoryMetadata, StoreMetadata, validate_existing

#: Fields that define which store this is; a different value is a
#: different store.
FIXED_FIELDS = (
    "identity.id",
    "identity.uuid",
    "identity.store_type",
    "identity.source_format",
    "identity.naming_authority",
    "identity.stac_link",
    "temporal.created",
    "content_settings",
)

#: Fields canVODpy keeps itself.
_RECORDS = ("metadata_version", "amendments", "migration")


def _get(data: dict[str, Any], field: str) -> Any:
    for part in field.split("."):
        data = data[part]
    return data


def check_amendable(field: str) -> None:
    """Refuse a field that cannot be amended: fixed, computed or unknown.

    Raises
    ------
    ValueError
        Saying why, e.g. that a fixed field means a different store.
    """
    fixed = next(
        (f for f in FIXED_FIELDS if field == f or field.startswith(f"{f}.")), None
    )
    if fixed is not None:
        name = fixed.rsplit(".", 1)[-1].replace("_", " ")
        msg = (
            f"`{fixed}` is a fixed field; a store with a different {name} is a "
            "different store: create a new one."
        )
        raise ValueError(msg)
    if field.split(".", 1)[0] in _RECORDS:
        msg = f"`{field}` is kept by canVODpy and cannot be amended."
        raise ValueError(msg)
    if _field_exists(RepositoryMetadata, field):
        return
    if _field_exists(StoreMetadata, field):
        msg = (
            f"`{field}` is computed by every commit (snapshot summary or commit "
            "metadata); it is not part of the repository metadata."
        )
    else:
        msg = f"`{field}` is not a field of the store metadata."
    raise ValueError(msg)


def amend_metadata(
    store_path: StoreLocation | Path | str,
    changes: dict[str, Any],
    *,
    reason: str,
    who: str,
    config: Any = None,
    receiver_content: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Change amendable fields of a store's repository metadata.

    Parameters
    ----------
    changes
        New values by dotted field path, e.g. ``{"identity.title": "..."}``.
        A new receiver or VOD analysis is added by its whole entry, e.g.
        ``{"instruments.receivers.canopy_02": {"type": "canopy",
        "directory": "..."}}``.
    reason
        Why; recorded with each changed field.
    who
        Who changes the fields, e.g. ``"NFB"``; recorded with each changed
        field.
    config
        The settings recorded in the commit metadata (see
        :func:`~canvod.store_metadata.io.commit_with_rebase`).
    receiver_content
        The content settings of each receiver added (``type``,
        ``reader_format``, ``paired_canopies``, ADR 0019), by name. Needed
        to add a receiver to a store that has content settings: they are
        added with it, and never changed later.

    Returns
    -------
    str
        Snapshot ID of the commit that carries the new root copy.

    Raises
    ------
    ValueError
        If there is no reason, no ``who`` or no change, a field is fixed, computed or
        unknown, a value is invalid, the store has no repository metadata,
        or a receiver is added to a store with content settings without its
        ``receiver_content``.
    """
    if not reason or not reason.strip():
        msg = "An amendment needs a reason: say why the fields change."
        raise ValueError(msg)
    who = check_who(who)
    if not changes:
        msg = "An amendment needs at least one change."
        raise ValueError(msg)
    for field in changes:
        check_amendable(field)

    store_path = store_location(store_path)
    with commit_lock(store_path):
        repo = open_repository(store_path)
        current = repo.get_metadata()
        if not current:
            msg = (
                f"The store at {store_path} has no repository metadata to amend; "
                "migrate it first (canvodpy store migrate-metadata)."
            )
            raise ValueError(msg)

        data = copy.deepcopy(current)
        old: dict[str, Any] = {}
        for field, value in changes.items():
            old[field] = _set_field(data, field, value)
        try:
            amended = validate_existing(
                RepositoryMetadata, data, changed=changes
            ).model_dump(mode="json")
        except ValidationError as exc:
            fields = sorted(
                ".".join(str(p) for p in error["loc"]) for error in exc.errors()
            )
            msg = f"Invalid value for {', '.join(fields)}; nothing was changed."
            raise ValueError(msg) from exc
        except ValueError as exc:  # a changed field breaks a rule
            msg = f"{exc} Nothing was changed."
            raise ValueError(msg) from exc
        for field, value in changes.items():
            if isinstance(value, dict):
                unknown = sorted(set(value) - set(_get(amended, field)))
                if unknown:
                    msg = f"`{field}` has no field(s) {', '.join(unknown)}."
                    raise ValueError(msg)

        added = _add_receiver_content(current, amended, receiver_content or {})
        when = datetime.now(UTC).isoformat()
        amended["amendments"] = [
            *current.get("amendments", []),
            *(
                {
                    "field": field,
                    "old": old[field],
                    "new": _get(amended, field),
                    "reason": reason.strip(),
                    "who": who,
                    "when": when,
                }
                for field in changes
            ),
            *(
                {
                    "field": field,
                    "old": previous,
                    "new": _get(amended, field),
                    "reason": reason.strip(),
                    "who": who,
                    "when": when,
                }
                for field, previous in added
            ),
        ]
        snapshot_id = commit_with_rebase(
            repo.writable_session("main"),
            f"Amend store metadata: {', '.join(changes)} ({reason.strip()})",
            store_path=store_path,
            config=config,
            repository=amended,
        )
        repo.set_metadata(amended)
        return snapshot_id


def _add_receiver_content(
    current: dict[str, Any],
    amended: dict[str, Any],
    receiver_content: dict[str, dict[str, Any]],
) -> list[tuple[str, Any]]:
    """Add the content settings of the receivers an amendment adds.

    A store's content settings list every receiver's type, reader format
    and paired canopies (ADR 0019); a receiver added by amendment brings
    its own. The hash is computed again. Returns each changed field with
    its old value, to record as amendments.

    Raises
    ------
    ValueError
        If a receiver is added without its content settings, or they don't
        match its entry.
    """
    from .content import (
        CONTENT_SETTINGS_FIELD,
        GNSS_CONTENT_HASH,
        RECEIVER_KEYS,
        settings_hash,
    )

    content = amended.get(CONTENT_SETTINGS_FIELD)
    new = sorted(
        set(amended.get("instruments", {}).get("receivers", {}))
        - set(current.get("instruments", {}).get("receivers", {}))
    )
    if not content or not new:
        return []
    (site,) = content["settings"]["sites"]
    receivers = content["settings"]["sites"][site]["receivers"]
    fields: list[tuple[str, Any]] = []
    for name in new:
        entry = receiver_content.get(name)
        if entry is None or set(entry) != set(RECEIVER_KEYS):
            msg = (
                f"The store has content settings (ADR 0019): adding receiver "
                f"{name!r} needs its {', '.join(RECEIVER_KEYS)} "
                "(canvodpy store amend --add-receiver takes them from the "
                "settings). Nothing was changed."
            )
            raise ValueError(msg)
        listed = amended["instruments"]["receivers"][name]
        for key in ("type", "reader_format"):
            if listed.get(key) != entry[key]:
                msg = (
                    f"Receiver {name!r}: {key} {entry[key]!r} in its content "
                    f"settings differs from {listed.get(key)!r} in its entry. "
                    "Nothing was changed."
                )
                raise ValueError(msg)
        receivers[name] = dict(entry)
        field = f"{CONTENT_SETTINGS_FIELD}.settings.sites.{site}.receivers.{name}"
        fields.append((field, None))
    fields.append((f"{CONTENT_SETTINGS_FIELD}.hash", content["hash"]))
    content["hash"] = settings_hash(
        content["settings"],
        content.get("resolved_sids"),
        content.get(GNSS_CONTENT_HASH),
    )
    return fields
