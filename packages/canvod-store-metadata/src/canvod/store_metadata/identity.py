"""A store's identifiers: id, UUID, naming authority and catalog link.

The id is ``{site slug}-{gnss|vod|geodesy}``, the slug being the configured site
name made lowercase; a site name that gives no valid slug is refused, never
changed into one. With the naming authority (reverse DNS, required when a
store is created) the id gives the store's network-unique item id in the
STAC catalog, ``{naming_authority}.{id}`` (ADR 0015).
"""

from __future__ import annotations

import re
import uuid

#: The settings field that gives the naming authority.
NAMING_AUTHORITY_SETTING = "processing.metadata.naming_authority"

_SLUG = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
_LABEL = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_REVERSE_DNS = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")

#: Store type -> (id suffix, catalog collection).
_PRODUCTS = {
    "gnss_store": ("gnss", "gnss-observations"),
    "vod_store": ("vod", "vod"),
    "geodesy_store": ("geodesy", "gnss-geodesy"),
}
#: The known store types.
STORE_TYPES = tuple(_PRODUCTS)


def _product(store_type: str) -> tuple[str, str]:
    try:
        return _PRODUCTS[store_type]
    except KeyError:
        msg = (
            f"A {store_type!r} has no place in the catalog; "
            f"store metadata is written for {sorted(_PRODUCTS)} only."
        )
        raise ValueError(msg) from None


def store_id(site_name: str, store_type: str) -> str:
    """Return the store id ``{site slug}-{gnss|vod|geodesy}``.

    Raises
    ------
    ValueError
        If the lowercase site name is not made of letters, digits and
        single ``_`` or ``-`` between them, or the store type has no
        catalog collection.
    """
    suffix, _ = _product(store_type)
    slug = site_name.lower()
    if not _SLUG.fullmatch(slug):
        msg = (
            f"The site name {site_name!r} gives no valid store id: use letters, "
            "digits, and '_' or '-' between them (e.g. 'rosalia' or "
            "'rosalia_v3_04'). Rename the site in the settings."
        )
        raise ValueError(msg)
    return f"{slug}-{suffix}"


def check_naming_authority(naming_authority: str | None) -> str:
    """Return the naming authority, refusing a missing or malformed one.

    Raises
    ------
    ValueError
        If it is missing or not a lowercase reverse DNS name such as
        ``at.ac.tuwien``.
    """
    if not naming_authority:
        msg = (
            "A store needs a naming authority when it is created: set "
            f"{NAMING_AUTHORITY_SETTING} in the settings to your institution's "
            "domain in reverse order (e.g. 'at.ac.tuwien')."
        )
        raise ValueError(msg)
    if not _REVERSE_DNS.fullmatch(naming_authority):
        msg = (
            f"The naming authority {naming_authority!r} is not a reverse DNS "
            "name: write your institution's domain in reverse order, lowercase "
            f"(e.g. 'at.ac.tuwien'), in {NAMING_AUTHORITY_SETTING}."
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
