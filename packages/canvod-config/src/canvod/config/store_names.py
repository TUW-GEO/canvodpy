"""Store types and the rule for a store's folder name (#456).

A site's stores are folders below ``stores_root_dir/{site}``. A store's
folder is named by its kind (``gnss``, ``vod`` or ``geodesy``), optionally
followed by ``-`` and a suffix for a second store of the same kind, for
example ``vod-recompute``. The store id is ``{site slug}-{folder}``, so the
folder says what a store is and which store it is.

This is the one list of store kinds: the settings, the store metadata, the
command line and extensions take it from here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Final

#: The kinds of store, which are also the default folder names.
STORE_KINDS: Final = ("gnss", "vod", "geodesy")

#: Store type as the store metadata records it -> store kind.
STORE_TYPE_KINDS: Final[Mapping[str, str]] = {
    "gnss_store": "gnss",
    "vod_store": "vod",
    "geodesy_store": "geodesy",
}

#: The GNSS store's folder name before v1.0.0.
OLD_GNSS_STORE_NAME: Final = "rinex"

#: Letters and digits, with single ``_`` or ``-`` between them (the store id
#: rule, so every valid folder gives a valid id).
_SUFFIX = r"[a-z0-9]+(?:[_-][a-z0-9]+)*"
_STORE_NAMES = {kind: re.compile(rf"{kind}(?:-{_SUFFIX})?") for kind in STORE_KINDS}
_OLD_GNSS = re.compile(rf"{OLD_GNSS_STORE_NAME}(?:[_-].*)?", re.IGNORECASE)

_LABELS = {"gnss": "GNSS", "vod": "VOD", "geodesy": "geodesy"}


class StoreNameError(ValueError):
    """A store folder name that breaks the naming rule."""


def store_kind(store_type: str) -> str:
    """The kind of a store type (``"vod_store"`` -> ``"vod"``).

    Raises
    ------
    ValueError
        If the store type is not one of :data:`STORE_TYPE_KINDS`.
    """
    try:
        return STORE_TYPE_KINDS[store_type]
    except KeyError:
        msg = (
            f"Unknown store type {store_type!r}; the store types are "
            f"{', '.join(STORE_TYPE_KINDS)}."
        )
        raise ValueError(msg) from None


def check_store_name(name: str, kind: str) -> str:
    """Return ``name`` if it is a valid folder name for a store of ``kind``.

    Valid: the kind itself, or the kind, ``-`` and a suffix of lowercase
    letters and digits with single ``_`` or ``-`` between them
    (``vod``, ``vod-recompute``). Lowercase only, so that two stores can't
    differ only in case on a case-insensitive file system.

    Raises
    ------
    ValueError
        If ``kind`` is not one of :data:`STORE_KINDS`.
    StoreNameError
        If ``name`` breaks the rule. The GNSS store's old name ``rinex``
        gets a message that names the migration command.
    """
    if kind not in _STORE_NAMES:
        msg = f"Unknown store kind {kind!r}; the kinds are {', '.join(STORE_KINDS)}."
        raise ValueError(msg)
    if _STORE_NAMES[kind].fullmatch(name):
        return name
    if kind == "gnss" and _OLD_GNSS.fullmatch(name):
        msg = (
            f"The GNSS store name {name!r} is no longer used: since v1.0.0 a "
            "store's folder is named by its kind, and the GNSS store's folder "
            "is 'gnss'. Remove processing.storage.gnss_store_name from your "
            "settings, then move each site's store with "
            "'canvodpy store migrate SITE'."
        )
        raise StoreNameError(msg)
    msg = (
        f"The {_LABELS[kind]} store name {name!r} is not allowed. A store's "
        f"folder is named by its kind, '{kind}', optionally followed by '-' "
        "and a suffix of lowercase letters and digits, with single '_' or '-' "
        f"between them, for a second store of that kind (e.g. "
        f"'{kind}-recompute')."
    )
    raise StoreNameError(msg)


def check_settings_store_name(name: str, kind: str) -> str:
    """:func:`check_store_name` for ``processing.storage.{kind}_store_name``.

    A refused name may be the folder of a store written before v1.0.0,
    which had no naming rule (``FAIR_Rinex_store``), so the message also
    says how to move such a store. It does not look for one.
    """
    try:
        return check_store_name(name, kind)
    except StoreNameError as error:
        if kind == "gnss" and _OLD_GNSS.fullmatch(name):
            raise
        msg = (
            f"{error} If {name!r} is the folder of a store from before v1.0.0, "
            f"remove processing.storage.{kind}_store_name from your settings "
            "(or set a name that follows the rule), then move each site's "
            f"store with 'canvodpy store migrate SITE --rename {name}={kind}' "
            "(or the name you set)."
        )
        raise StoreNameError(msg) from None


def kind_of_store_name(name: str) -> str | None:
    """The kind of a valid store folder name, or ``None`` if it has none."""
    for kind, pattern in _STORE_NAMES.items():
        if pattern.fullmatch(name):
            return kind
    return None


def store_folder_name(store_path: object) -> str:
    """The folder name of a store from its path or ``s3://`` URL.

    Accepts a :class:`~pathlib.Path`, a string, or any object whose ``str``
    is the path or URL (a store location).
    """
    if isinstance(store_path, PurePath):
        return store_path.name
    text = str(store_path).rstrip("/")
    if "://" in text:
        return text.rsplit("/", 1)[-1]
    return Path(text).name
