"""Build a ``canvod-settings.yaml`` mapping from a store's repository metadata.

``canvodpy config init --from-store <store>`` writes a settings file that
reproduces a store's processing. This module builds the mapping: the store's
content settings stay as they are, the site and receivers come from the
repository metadata, and the machine values a run owner fills in are
``TODO``. No printing, no prompts here; the CLI asks and fills them in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from canvod.config.models.aux_data import PRECISE_ONLY_SETTINGS

from .content import MissingContentSettingsError, with_current_names
from .io import read_repository_metadata
from .machine import set_machine_settings

#: Placeholder for a value the run owner fills in: data roots, cache and log
#: folders and the metadata author/email/institution. ``config init
#: --from-store --no-interactive`` keeps it; interactive asks.
PLACEHOLDER = "TODO"


def _content_settings(repository: dict[str, Any], store: Any) -> dict[str, Any]:
    """The nested content-settings dict of ``repository``.

    A store before ADR 0019 has none: the run owner must give them once,
    from the settings recorded in the store's first commit.
    """
    content = repository.get("content_settings")
    if not content:
        site = repository.get("spatial", {}).get("site", {}).get("name", "SITE")
        store_type = repository.get("identity", {}).get("store_type", "gnss_store")
        kind = "gnss" if store_type == "gnss_store" else store_type
        raise MissingContentSettingsError(
            f"The store at {store} has no content settings: it was created "
            "before stores kept them, so its settings cannot be reproduced "
            "from it. Write them once, from the settings recorded in the "
            "store's first commit:\n"
            f"  canvodpy store migrate-metadata {site} --store {kind}"
        )
    return content["settings"]


def _store_root_and_name(store: Any, site_name: str) -> tuple[str, str]:
    """``(stores_root_dir, gnss_store_name)`` of the store argument.

    A store lives at ``<stores_root_dir>/<site>/<store_name>``: ``<site>`` is
    the parent folder for a local store, or the S3 prefix part before the
    name for an ``s3://`` URL. The root of an ``s3://`` store must be
    ``s3://<bucket>`` or ``s3://<bucket>/<prefix>``. If the site is not the
    site the store records, nothing is written and the error names the
    expected layout.

    Raises
    ------
    ValueError
        If the parent folder (or S3 prefix part before the name) is not the
        site the store records, or if an ``s3://`` store has no bucket
        before it.
    """
    text = str(store).rstrip("/")
    if text.startswith("s3://"):
        parts = text.split("/")
        name = parts[-1]
        root = "/".join(parts[:-2])
        if len(parts) < 5:
            raise _layout_error(store, site_name)
        site_part = parts[-2]
    else:
        p = Path(text)
        name = p.name
        site_part = p.parent.name
        root = str(p.parent.parent)
    if site_part != site_name or not name:
        raise _layout_error(store, site_name)
    return root or "/", name


def _layout_error(store: Any, site_name: str) -> ValueError:
    """The error for a store not at ``<root>/<site>/<name>``."""
    return ValueError(
        f"The store at {store} is not at the layout "
        "<stores_root_dir>/<site>/<store_name>: the site the store records "
        f"is {site_name!r}, but the folder (or S3 prefix part) right "
        "before the store's name is not it. "
        "A store lives at <stores_root_dir>/<site>/<store_name>; use its "
        "<root>/<site>/<name> path, or write to a new store."
    )


def settings_from_store(store: Any) -> dict[str, Any]:
    """A ``canvod-settings.yaml`` mapping that reproduces ``store``.

    Parameters
    ----------
    store
        The store, as a local directory or ``s3://bucket/prefix``.

    Returns
    -------
    dict
        The settings mapping: the store's content settings (renamed values
        under their current names), the
        site and receivers from its repository metadata, ``stores_root_dir``
        and ``gnss_store_name`` from ``store``, and ``TODO`` for the machine
        values (``gnss_site_data_root``, each receiver ``directory``,
        ``aux_data_dir``, ``shared_aux_cache_dir``, ``log_dir``,
        ``metadata.author``, ``metadata.email``, ``metadata.institution``,
        and the ``recipe`` of a receiver whose recipe was a URL: the store
        keeps only its file name).

    Raises
    ------
    MissingContentSettingsError
        If the store has no content settings (created before ADR 0019):
        names the ``canvodpy store migrate-metadata`` command that gives it
        them.
    """
    repository = read_repository_metadata(store)
    content = with_current_names(_content_settings(repository, store))
    # A broadcast store records the settings of the precise ephemeris as
    # empty; the settings file leaves them out, so the defaults load.
    aux_data = content.get("processing", {}).get("aux_data", {})
    for name in PRECISE_ONLY_SETTINGS:
        if name in aux_data and aux_data[name] is None:
            del aux_data[name]
    settings = dict(content)
    site_name = next(iter(content["sites"]))
    site = content["sites"][site_name]

    # The site and the store from the repository metadata: site description
    # and location, the store's description, each receiver's description and
    # recipe. The receivers of a store's content settings are the ones its
    # creating run wrote; the repository metadata adds the free fields.
    spatial = repository.get("spatial", {})
    site_info = spatial.get("site", {})
    site["description"] = site_info.get("description")
    site["country"] = site_info.get("country")
    site["latitude"] = spatial.get("geospatial_lat")
    site["longitude"] = spatial.get("geospatial_lon")
    site["altitude_m"] = spatial.get("geospatial_alt_m")
    site["store_description"] = repository.get("identity", {}).get("description")

    receivers = repository.get("instruments", {}).get("receivers", {})
    for name, receiver in site["receivers"].items():
        meta = receivers.get(name, {})
        # The directory is the run owner's to give; interactive offers the
        # store's recorded one as the default answer.
        receiver["directory"] = PLACEHOLDER
        if meta.get("description") is not None:
            receiver["description"] = meta["description"]
        recipe = meta.get("recipe")
        if recipe is not None:
            # A store keeps only the file name of a recipe URL; the run
            # owner gives the URL again.
            receiver["recipe"] = (
                PLACEHOLDER if recipe.endswith((".yaml", ".yml")) else recipe
            )

    # Processing: the content keys the store kept, plus the free fields.
    processing = settings.setdefault("processing", {})
    storage = processing.setdefault("storage", {})
    root, name = _store_root_and_name(store, site_name)
    storage["stores_root_dir"] = root
    storage["gnss_store_name"] = name
    # The settings of the run owner's computer (data root, cache and log
    # folders), the same list the stores leave out.
    set_machine_settings(settings, PLACEHOLDER)
    metadata = processing.setdefault("metadata", {})
    metadata["author"] = PLACEHOLDER
    metadata["email"] = PLACEHOLDER
    metadata["institution"] = PLACEHOLDER

    return settings
