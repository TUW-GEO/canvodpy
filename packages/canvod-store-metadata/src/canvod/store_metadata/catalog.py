"""The STAC catalog of all stores under a data root (ADR 0015).

A static catalog beside the stores, never inside one: ``catalog.json``,
one collection per product (``gnss-observations``, ``vod``,
``gnss-geodesy``) and one item per store, all links relative, so the data
root can be copied or moved. The catalog is derived from the stores and is
written only on request.

Each asset names what opening its dataset needs: the store (href), the
group (``xarray:open_kwargs``) and the snapshot (``canvod:snapshot_id``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pystac
import zarr
from pystac.extensions.xarray_assets import XarrayAssetsExtension

from .identity import _PRODUCTS
from .inventory import _find_icechunk_stores
from .io import read_metadata
from .location import open_repository
from .schema import StoreMetadata
from .summary import _data_groups

#: STAC Zarr best practices; no media type is registered for Icechunk.
ZARR_MEDIA_TYPE = "application/vnd.zarr; version=3"

_CATALOG_ID = "canvod-catalog"
_COLLECTION_TITLES = {
    "gnss-observations": "GNSS observations",
    "vod": "Vegetation optical depth",
    "gnss-geodesy": "GNSS geodesy",
}


def _item_id(meta: StoreMetadata) -> str:
    return f"{meta.identity.naming_authority}.{meta.identity.id}"


def _collection_id(meta: StoreMetadata) -> str:
    return _PRODUCTS[meta.identity.store_type][1]


def _geometry(meta: StoreMetadata) -> tuple[dict[str, Any], list[float]]:
    """GeoJSON point at the site and its bbox (the point repeated)."""
    spatial = meta.spatial
    if spatial.geospatial_lon is None or spatial.geospatial_lat is None:
        msg = f"{meta.identity.id} has no site position (latitude, longitude)"
        raise ValueError(msg)
    point = [spatial.geospatial_lon, spatial.geospatial_lat]
    if spatial.geospatial_alt_m is not None:
        point.append(spatial.geospatial_alt_m)
    return {"type": "Point", "coordinates": point}, point + point


def _license(meta: StoreMetadata) -> str:
    """The store's SPDX identifier; ``other`` for a license given by its URI.

    STAC 1.1 has no ``proprietary`` or ``various``: a license outside SPDX
    is ``other`` plus a ``license`` link to its text.
    """
    return meta.publisher.license or "other"


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
    """
    return _store_item(Path(store_path))[1]


def _store_item(store_path: Path) -> tuple[str, pystac.Item]:
    """The collection a store belongs to, and its item (see :func:`store_item`)."""
    snapshot_id = open_repository(store_path).lookup_branch("main")
    meta = read_metadata(store_path, snapshot_id=snapshot_id)
    geometry, bbox = _geometry(meta)
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
            "license": _license(meta),
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


def build_catalog(root: Path | str) -> pystac.Catalog:
    """The catalog of every store under ``root``, in memory.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).
    """
    root = Path(root)
    by_collection: dict[str, list[pystac.Item]] = {}
    for store_path in _find_icechunk_stores(root):
        collection_id, item = _store_item(store_path)
        by_collection.setdefault(collection_id, []).append(item)

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
    """
    root = Path(root).resolve()
    catalog = build_catalog(root)
    catalog.normalize_hrefs(str(root))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    return root / "catalog.json"
