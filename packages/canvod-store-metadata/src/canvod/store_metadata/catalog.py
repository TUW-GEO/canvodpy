"""The STAC catalog of all stores under a data root (ADR 0015).

A static catalog beside the stores, never inside one: ``catalog.json``,
one collection per product (``gnss-observations``, ``vod``,
``gnss-geodesy``) and one item per store, all links relative, so the data
root can be copied or moved. The catalog is derived from the stores and is
written only on request.

Each asset names what opening its dataset needs: the store (href), the
group (``xarray:open_kwargs``) and the snapshot (``canvod:snapshot_id``).

The catalog never leaves a store out silently: every store under the root
is read first, and if any cannot be described, one error lists them all
and nothing is written.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import icechunk
import pystac
import zarr
from pydantic import ValidationError
from pystac.extensions.xarray_assets import XarrayAssetsExtension

from .identity import _product
from .inventory import _store_candidates
from .io import _written_before_metadata, read_metadata, store_command
from .location import MIGRATE_COMMAND, open_repository, store_exists
from .schema import (
    MetadataRuleWarning,
    StoreMetadata,
    check_rules,
    describe_rule_breaks,
)
from .summary import _data_groups

#: STAC Zarr best practices; no media type is registered for Icechunk.
ZARR_MEDIA_TYPE = "application/vnd.zarr; version=3"

_CATALOG_ID = "canvod-catalog"
_COLLECTION_TITLES = {
    "gnss-observations": "GNSS observations",
    "vod": "Vegetation optical depth",
    "gnss-geodesy": "GNSS geodesy",
}


class _RefusedError(ValueError):
    """Why a store cannot be described in the catalog."""


def _item_id(meta: StoreMetadata) -> str:
    return f"{meta.identity.naming_authority}.{meta.identity.id}"


def _collection_id(meta: StoreMetadata) -> str:
    return _product(meta.identity.store_type)[1]


def _geometry(meta: StoreMetadata) -> tuple[dict[str, Any], list[float]]:
    """GeoJSON point at the site and its bbox (the point repeated)."""
    spatial = meta.spatial
    if spatial.geospatial_lon is None or spatial.geospatial_lat is None:
        msg = (
            "has no site position (spatial.geospatial_lat, "
            "spatial.geospatial_lon); set it with "
            f"{_command('amend', meta)}"
        )
        raise _RefusedError(msg)
    point = [spatial.geospatial_lon, spatial.geospatial_lat]
    if spatial.geospatial_alt_m is not None:
        point.append(spatial.geospatial_alt_m)
    return {"type": "Point", "coordinates": point}, point + point


def _command(command: str, meta: StoreMetadata) -> str:
    return store_command(command, meta.spatial.site.name, meta.identity.store_type)


def _license(meta: StoreMetadata) -> str:
    """The store's license: an SPDX identifier, or ``other``.

    STAC 1.1 has no ``proprietary`` or ``various``: a license outside SPDX
    is ``other`` plus a ``license`` link to its text. The publisher model
    holds that rule; a store written before it may break it.
    """
    license_ = meta.publisher.license
    if license_ is None:
        msg = (
            f"has no license (publisher.license); set it with {_command('amend', meta)}"
        )
        raise _RefusedError(msg)
    broken = [b for b in check_rules(meta) if b.field.startswith("publisher.license")]
    if broken:
        msg = f"{describe_rule_breaks(broken)}; fix it with {_command('amend', meta)}"
        raise _RefusedError(msg)
    return license_


def _datetime(value: str | None) -> Any:
    return pystac.utils.str_to_datetime(value) if value else None


def _observation_groups(store_path: Path, snapshot_id: str) -> list[str]:
    """The receivers' observation groups of a snapshot (top-level data groups)."""
    session = open_repository(store_path).readonly_session(snapshot_id=snapshot_id)
    root = zarr.open_group(session.store, mode="r")
    return sorted(name for name in _data_groups(root) if "/" not in name)


def store_item(store_path: Path | str) -> pystac.Item:
    """The catalog item of one store, describing ``main`` now.

    Parameters
    ----------
    store_path
        The store's directory.

    Returns
    -------
    pystac.Item
        Item ``{naming_authority}.{store id}``: a point at the site, the
        time range of the data, and one asset per observation group whose
        href is the store itself.

    Raises
    ------
    ValueError
        If the store cannot be described (see :func:`build_catalog`).
    """
    store_path = Path(store_path)
    try:
        return _store_item(store_path)[1]
    except _RefusedError as refused:
        msg = f"The store at {store_path} {refused}"
        raise ValueError(msg) from refused


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0]


def _cannot_open(error: Exception) -> _RefusedError:
    return _RefusedError(f"cannot be opened: {_first_line(error)}")


def _read_quietly(store_path: Path, **kwargs: Any) -> StoreMetadata:
    """``read_metadata`` without rule warnings: the catalog reports the
    broken rules of the fields it needs (``_license``)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MetadataRuleWarning)
        return read_metadata(store_path, **kwargs)


def _without_metadata(store_path: Path, repo: icechunk.Repository) -> str:
    """Why a store without repository metadata is refused."""
    if not _written_before_metadata(repo):
        return "has no metadata; a store gets it from the run that creates it"
    try:
        command = _command("migrate-metadata", _read_quietly(store_path))
    except KeyError, ValidationError:  # data without old-form metadata
        command = f"{MIGRATE_COMMAND} SITE --store gnss|vod"
    return f"needs migration to the current metadata form (ADR 0014): {command}"


def _store_item(store_path: Path) -> tuple[str, pystac.Item]:
    """The collection a store belongs to, and its item (see :func:`store_item`).

    Raises
    ------
    _RefusedError
        If the store cannot be described: it cannot be opened, has no
        metadata or needs migration, has no site position, or its license
        is missing or breaks the license rule.
    """
    try:
        repo = open_repository(store_path)
        snapshot_id = repo.lookup_branch("main")
    except (icechunk.IcechunkError, OSError) as error:
        raise _cannot_open(error) from error
    if not repo.get_metadata():
        raise _RefusedError(_without_metadata(store_path, repo))
    meta = _read_quietly(store_path, snapshot_id=snapshot_id)
    geometry, bbox = _geometry(meta)
    license_ = _license(meta)
    temporal = meta.temporal
    item = pystac.Item(
        id=_item_id(meta),
        geometry=geometry,
        bbox=bbox,
        datetime=None,
        start_datetime=_datetime(temporal.time_coverage_start),
        end_datetime=_datetime(temporal.time_coverage_end),
        properties={
            "title": meta.identity.title,
            "license": license_,
            "canvod:uuid": meta.identity.uuid,
        },
    )
    if meta.publisher.license_uri:
        item.add_link(
            pystac.Link(
                rel=pystac.RelType.LICENSE,
                target=meta.publisher.license_uri,
                title="License",
            )
        )
    XarrayAssetsExtension.add_to(item)
    for group in _observation_groups(store_path, snapshot_id):
        asset = pystac.Asset(
            href=str(store_path.resolve()),
            title=f"{group} observations",
            media_type=ZARR_MEDIA_TYPE,
            roles=["data", "latest-version"],
            extra_fields={
                "canvod:snapshot_id": snapshot_id,
                # xarray-assets extension: what xarray needs on the
                # snapshot's store (an Icechunk session) to open the group.
                "xarray:open_kwargs": {
                    "group": group,
                    "engine": "zarr",
                    "consolidated": False,
                    "zarr_format": 3,
                },
            },
        )
        item.add_asset(group, asset)
    return _collection_id(meta), item


def _collection(collection_id: str, items: list[pystac.Item]) -> pystac.Collection:
    licenses = {item.properties["license"] for item in items}
    collection = pystac.Collection(
        id=collection_id,
        title=_COLLECTION_TITLES[collection_id],
        description=f"{_COLLECTION_TITLES[collection_id]}, one item per store.",
        extent=pystac.Extent.from_items(items),
        license=licenses.pop() if len(licenses) == 1 else "other",
    )
    collection.add_items(items)
    return collection


def _holds_store(candidate: Path) -> bool:
    try:
        return store_exists(candidate)
    except (icechunk.IcechunkError, OSError) as error:
        raise _cannot_open(error) from error


def _refusal(root: Path, refused: dict[Path, str]) -> str:
    lines = [
        f"No catalog was written: {len(refused)} store(s) under {root} cannot "
        "be described.",
        *(
            f"  {path.relative_to(root).as_posix()}: {reason}"
            for path, reason in sorted(refused.items())
        ),
    ]
    return "\n".join(lines)


def build_catalog(root: Path | str) -> pystac.Catalog:
    """The catalog of every store under ``root``, in memory.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).

    Raises
    ------
    ValueError
        Listing every store that cannot be described, with its reason: it
        cannot be opened, has no metadata, needs migration (with the
        migrate command), has no site position, or its license is missing
        or not usable (not SPDX, or ``other`` without ``license_uri``).
    """
    root = Path(root)
    by_collection: dict[str, list[pystac.Item]] = {}
    refused: dict[Path, str] = {}
    for candidate in _store_candidates(root):
        try:
            if not _holds_store(candidate):
                continue
            collection_id, item = _store_item(candidate)
        except _RefusedError as reason:
            refused[candidate] = str(reason)
            continue
        by_collection.setdefault(collection_id, []).append(item)
    if refused:
        raise ValueError(_refusal(root, refused))

    catalog = pystac.Catalog(
        id=_CATALOG_ID,
        title="canVODpy stores",
        description="Every store under this data root, by product.",
    )
    for collection_id in sorted(by_collection):
        catalog.add_child(_collection(collection_id, by_collection[collection_id]))
    return catalog


def write_catalog(root: Path | str) -> Path:
    """Write the latest catalog of every store under ``root``, beside them.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).

    Returns
    -------
    Path
        The written ``catalog.json``.

    Raises
    ------
    ValueError
        Listing every store that cannot be described (see
        :func:`build_catalog`); nothing is written.
    """
    root = Path(root).resolve()
    catalog = build_catalog(root)
    catalog.normalize_hrefs(str(root))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    return root / "catalog.json"
