"""Build a ``canvod-settings.yaml`` mapping from a store's repository metadata.

``canvodpy config init --from-store <store>`` writes a settings file that
reproduces a store's processing. This module builds the mapping: the store's
content settings stay as they are, the site and receivers come from the
repository metadata, and the machine values a run owner fills in are
``TODO``. No printing, no prompts here; the CLI asks and fills them in.
"""

from __future__ import annotations

from typing import Any

from .content import MissingContentSettingsError
from .io import read_repository_metadata

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

    A store lives at ``<root>/<site>/<name>``: ``<root>`` is the
    ``stores_root_dir`` (a folder or the ``s3://`` root), ``<name>`` the
    store's own directory (a request for the S3 path counts the last part
    only). The site component must match the store's recorded site.
    """
    text = str(store).rstrip("/")
    name = text.rsplit("/", 1)[-1]
    tail = f"/{site_name}/{name}"
    if text.endswith(tail):
        root = text[: -len(tail)]
    else:
        root = text.rsplit("/", 2)[0]
    return (root or "/"), (name or PLACEHOLDER)


def settings_from_store(store: Any) -> dict[str, Any]:
    """A ``canvod-settings.yaml`` mapping that reproduces ``store``.

    Parameters
    ----------
    store
        The store, as a local directory or ``s3://bucket/prefix``.

    Returns
    -------
    dict
        The settings mapping: the store's content settings (unchanged), the
        site and receivers from its repository metadata, ``stores_root_dir``
        and ``gnss_store_name`` from ``store``, and ``TODO`` for the machine
        values (``gnss_site_data_root``, each receiver ``directory``,
        ``aux_data_dir``, ``shared_aux_cache_dir``, ``log_dir``, and
        ``metadata.author``, ``metadata.email``, ``metadata.institution``).

    Raises
    ------
    MissingContentSettingsError
        If the store has no content settings (created before ADR 0019):
        names the ``canvodpy store migrate-metadata`` command that gives it
        them.
    """
    repository = read_repository_metadata(store)
    content = _content_settings(repository, store)
    settings = dict(content)
    site_name = next(iter(content["sites"]))
    site = content["sites"][site_name]

    # The site's machine value: the run owner's data root.
    site["gnss_site_data_root"] = PLACEHOLDER

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
        # The directory is a machine value; interactive offers the store's
        # recorded one as the default answer.
        receiver["directory"] = PLACEHOLDER
        if meta.get("description") is not None:
            receiver["description"] = meta["description"]
        if meta.get("recipe") is not None:
            receiver["recipe"] = meta["recipe"]

    # Processing: the content keys the store kept, plus the free fields.
    processing = settings.setdefault("processing", {})
    storage = processing.setdefault("storage", {})
    root, name = _store_root_and_name(store, site_name)
    storage["stores_root_dir"] = root
    storage["gnss_store_name"] = name
    storage["aux_data_dir"] = PLACEHOLDER
    storage["shared_aux_cache_dir"] = PLACEHOLDER
    metadata = processing.setdefault("metadata", {})
    metadata["author"] = PLACEHOLDER
    metadata["email"] = PLACEHOLDER
    metadata["institution"] = PLACEHOLDER
    logging = processing.setdefault("logging", {})
    logging["log_dir"] = PLACEHOLDER

    return settings
