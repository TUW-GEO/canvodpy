"""A store's identifiers: id, UUID, naming authority and catalog link.

The id is ``{site slug}-{store folder}``, the slug being the configured site
name made lowercase and the folder the store's name (``gnss``, ``vod``,
``geodesy``, or one of these with a suffix such as ``vod-recompute``,
:mod:`canvod.config.store_names`); a site name that gives no valid slug is
refused, never changed into one. With the naming authority (reverse DNS, required when a
store is created) the id gives the store's network-unique item id in the
STAC catalog, ``{naming_authority}.{id}`` (ADR 0015).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from canvod.config.store_names import (
    OLD_GNSS_STORE_NAME,
    STORE_TYPE_KINDS,
    check_store_name,
    kind_of_store_name,
    store_folder_name,
    store_kind,
)

#: The settings field that gives the naming authority.
NAMING_AUTHORITY_SETTING = "processing.metadata.naming_authority"

_SLUG = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
_LABEL = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_REVERSE_DNS = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")

#: Store kind -> catalog collection.
_COLLECTIONS = {
    "gnss": "gnss-observations",
    "vod": "vod",
    "geodesy": "gnss-geodesy",
}
#: The known store types.
STORE_TYPES = tuple(STORE_TYPE_KINDS)


def _product(store_type: str) -> tuple[str, str]:
    """``(kind, catalog collection)`` of a store type."""
    try:
        kind = store_kind(store_type)
    except ValueError:
        msg = (
            f"A {store_type!r} has no place in the catalog; "
            f"store metadata is written for {sorted(STORE_TYPES)} only."
        )
        raise ValueError(msg) from None
    return kind, _COLLECTIONS[kind]


def store_id(site_name: str, store_type: str, store_name: str | None = None) -> str:
    """Return the store id ``{site slug}-{store folder}``.

    Parameters
    ----------
    store_name
        The store's folder name, checked against its type
        (:func:`canvod.config.store_names.check_store_name`). ``None``: the
        type's default folder (``gnss``, ``vod``, ``geodesy``).

    Raises
    ------
    ValueError
        If the lowercase site name is not made of letters, digits and
        single ``_`` or ``-`` between them, the store type has no
        catalog collection, or the folder name breaks the naming rule.
    """
    kind, _ = _product(store_type)
    name = kind if store_name is None else check_store_name(store_name, kind)
    slug = site_name.lower()
    if not _SLUG.fullmatch(slug):
        msg = (
            f"The site name {site_name!r} gives no valid store id: use letters, "
            "digits, and '_' or '-' between them (e.g. 'rosalia' or "
            "'rosalia_v3_04'). Rename the site in the settings."
        )
        raise ValueError(msg)
    return f"{slug}-{name}"


def check_naming_authority(naming_authority: str | None) -> str:
    """Return the naming authority, refusing a missing or malformed one.

    Raises
    ------
    ValueError
        If it is missing or not a lowercase reverse DNS name such as
        ``org.middle-earth``.
    """
    if not naming_authority:
        msg = (
            "A store needs a naming authority when it is created: set "
            f"{NAMING_AUTHORITY_SETTING} in the settings to your institution's "
            "domain in reverse order (e.g. 'org.middle-earth')."
        )
        raise ValueError(msg)
    if not _REVERSE_DNS.fullmatch(naming_authority):
        msg = (
            f"The naming authority {naming_authority!r} is not a reverse DNS "
            "name: write your institution's domain in reverse order, lowercase "
            f"(e.g. 'org.middle-earth'), in {NAMING_AUTHORITY_SETTING}."
        )
        raise ValueError(msg)
    return naming_authority


def new_uuid() -> str:
    """Return a new random UUID for a store being created."""
    return str(uuid.uuid4())


def stac_link(naming_authority: str, store_id: str, store_type: str) -> str:
    """Return the link from a store to its item in the catalog.

    Relative to the store, so it holds wherever the data root is copied:
    ``../../<collection>/<item id>/<item id>.json``.
    """
    _, collection = _product(store_type)
    item_id = f"{naming_authority}.{store_id}"
    return f"../../{collection}/{item_id}/{item_id}.json"


def check_store_folder(repository: dict[str, Any], store_path: object) -> str | None:
    """Why a store's recorded id doesn't fit its folder, or ``None`` if it does.

    The id ends in the folder name it was created in. Another folder name
    means the folder was renamed by hand (or the store predates ids taken
    from the folder name): runs and migration refuse to write to it.
    """
    recorded = repository.get("identity", {}).get("id")
    if not recorded:
        return None
    folder = store_folder_name(store_path)
    if kind_of_store_name(folder) is not None and recorded.endswith(f"-{folder}"):
        return None
    if folder.lower().startswith(OLD_GNSS_STORE_NAME):
        return (
            f"The store at {store_path} is in a folder named {folder!r}, the "
            "GNSS store's name before v1.0.0. Move it with "
            "'canvodpy store migrate SITE'."
        )
    return (
        f"The store at {store_path} records the id {recorded!r}, which doesn't "
        f"end in its folder name {folder!r}: the folder was renamed after the "
        "store was created. A store's id is fixed, so give the folder back the "
        f"name its id ends in, or rebuild the store in {folder!r}."
    )
