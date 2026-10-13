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
import numpy as np
import pystac
import zarr
from pydantic import ValidationError
from pystac.extensions.datacube import DatacubeExtension
from pystac.extensions.xarray_assets import XarrayAssetsExtension

from .identity import _product
from .inventory import _store_candidates
from .io import _written_before_metadata, read_metadata, store_command
from .location import MIGRATE_COMMAND, open_repository, store_exists
from .schema import (
    SPDX_LIST_URL,
    MetadataRuleWarning,
    StoreMetadata,
    check_rules,
    describe_rule_breaks,
)
from .snapshot import RESERVED_GROUP
from .summary import _array, _data_groups, _decode_epochs, _iso, receiver_groups

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


def _dimension(group: zarr.Group, name: str, size: int) -> dict[str, Any]:
    """A datacube dimension object for the dimension ``name`` of ``group``."""
    if name == "epoch":
        epochs = _decode_epochs(_array(group, "epoch"))
        return {"type": "temporal", "extent": [_iso(epochs.min()), _iso(epochs.max())]}
    if name in group and isinstance(group[name], zarr.Array):
        values = np.asarray(_array(group, name)[...])
        return {"type": name, "values": [str(v) for v in values.tolist()]}
    return {"type": name, "extent": [0, size - 1]}


def _datacube(group: zarr.Group) -> dict[str, Any]:
    """The datacube fields of a dataset: its dimensions and variables.

    A coordinate that is no dimension (xarray lists those in each array's
    ``coordinates`` attribute) is an ``auxiliary`` variable.
    """
    sizes: dict[str, int] = {}
    variables: dict[str, Any] = {}
    coordinates: set[str] = set()
    for name, array in group.arrays():
        # Stores are Zarr 3, whose arrays name their dimensions.
        dims = [str(d) for d in getattr(array.metadata, "dimension_names", None) or ()]
        sizes.update(zip(dims, array.shape, strict=True))
        coordinates.update(str(array.attrs.get("coordinates", "")).split())
        if dims and name not in dims:
            variables[name] = {"dimensions": dims}
    for name, variable in variables.items():
        variable["type"] = "auxiliary" if name in coordinates else "data"
    return {
        "cube:dimensions": {
            name: _dimension(group, name, size) for name, size in sizes.items()
        },
        "cube:variables": variables,
    }


def _asset(
    store_path: Path,
    snapshot_id: str,
    group: str,
    *,
    title: str,
    role: str,
    extra: dict[str, Any] | None = None,
) -> pystac.Asset:
    """An asset of the dataset in ``group``: the store, snapshot and group."""
    return pystac.Asset(
        href=str(store_path.resolve()),
        title=title,
        media_type=ZARR_MEDIA_TYPE,
        roles=[role, "latest-version"],
        extra_fields={
            "canvod:snapshot_id": snapshot_id,
            # xarray-assets extension: what xarray needs on the snapshot's
            # store (an Icechunk session) to open the group.
            "xarray:open_kwargs": {
                "group": group,
                "engine": "zarr",
                "consolidated": False,
                "zarr_format": 3,
            },
            **(extra or {}),
        },
    )


def _receiver_positions(meta: StoreMetadata) -> dict[str, list[float]]:
    """Each receiver's position (ECEF, m), for the receivers that have one."""
    return {
        name: info.position_ecef_m
        for name, info in meta.instruments.receivers.items()
        if info.position_ecef_m is not None
    }


def _positions(meta: StoreMetadata) -> dict[str, list[float]]:
    """Each data group's receiver position (ECEF, m), by group."""
    receivers = meta.instruments.receivers
    groups = receiver_groups({name: info.type for name, info in receivers.items()})
    return {
        group: position
        for name, position in _receiver_positions(meta).items()
        for group in groups[name]
    }


def _assets(
    store_path: Path, snapshot_id: str, meta: StoreMetadata
) -> dict[str, pystac.Asset]:
    """One asset per stored dataset of a snapshot, by key.

    A data group (a receiver's observations, a VOD analysis) is an asset;
    its SBF metadata (``metadata/sbf_obs``) and its log book
    (``metadata/table``) are assets of their own. Keys join the parts of
    the group path with a dot: some tools read a ``/`` in a key as a path.
    The reserved group is no asset.
    """
    session = open_repository(store_path).readonly_session(snapshot_id=snapshot_id)
    root = zarr.open_group(session.store, mode="r")
    data_groups = _data_groups(root)
    positions = _positions(meta)
    assets: dict[str, pystac.Asset] = {}
    for path in sorted(data_groups):
        parts = path.split("/")
        if parts[0] == RESERVED_GROUP or "metadata" in parts:
            continue
        key = ".".join(parts)
        position = (
            {"canvod:position_ecef_m": positions[path]} if path in positions else {}
        )
        assets[key] = _asset(
            store_path,
            snapshot_id,
            path,
            title=f"{path}: data",
            role="data",
            extra=_datacube(data_groups[path]) | position,
        )
        sbf_obs = f"{path}/metadata/sbf_obs"
        if sbf_obs in data_groups:
            assets[f"{key}.sbf_obs"] = _asset(
                store_path,
                snapshot_id,
                sbf_obs,
                title=f"{path}: SBF metadata",
                role="metadata",
                extra=_datacube(data_groups[sbf_obs]),
            )
        log_book = f"{path}/metadata/table"
        if log_book in root and isinstance(root[log_book], zarr.Group):
            assets[f"{key}.log_book"] = _asset(
                store_path,
                snapshot_id,
                log_book,
                title=f"{path}: log book",
                role="metadata",
            )
    return assets


def _receivers(meta: StoreMetadata) -> dict[str, dict[str, Any]]:
    """``canvod:receivers``: each receiver's type and position, if known."""
    positions = _receiver_positions(meta)
    return {
        name: {"type": info.type}
        | ({"position_ecef_m": positions[name]} if name in positions else {})
        for name, info in sorted(meta.instruments.receivers.items())
    }


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
        time range of the data, the receivers with their positions, and one
        asset per stored dataset whose href is the store itself.

    Raises
    ------
    ValueError
        If the store cannot be described (see :func:`build_catalog`).
    """
    store_path = Path(store_path)
    try:
        return _store_item(store_path)[2]
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


def _license_link(href: str) -> pystac.Link:
    return pystac.Link(rel=pystac.RelType.LICENSE, target=href, title="License")


def _store_item(store_path: Path) -> tuple[str, tuple[str | None, str], pystac.Item]:
    """The collection a store belongs to, its site, and its item.

    The site is the naming authority and the site name: two networks may
    name a site alike. The item is described at :func:`store_item`.

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
            "canvod:site": meta.spatial.site.name,
            "canvod:receivers": _receivers(meta),
        },
    )
    if meta.publisher.license_uri:
        item.add_link(_license_link(meta.publisher.license_uri))
    XarrayAssetsExtension.add_to(item)
    DatacubeExtension.add_to(item)
    for key, asset in _assets(store_path, snapshot_id, meta).items():
        item.add_asset(key, asset)
    site = (meta.identity.naming_authority, meta.spatial.site.name)
    return _collection_id(meta), site, item


def _license_text(item: pystac.Item) -> str:
    """Where an item's license text is: its license link, else SPDX's page."""
    links = item.get_links(pystac.RelType.LICENSE)
    if links:
        return links[0].href
    return f"{SPDX_LIST_URL}{item.properties['license']}.html"


def _extent(items: list[pystac.Item]) -> pystac.Extent:
    """The union of the items' bboxes and time ranges.

    Not ``pystac.Extent.from_items``: it reads every bbox as 2D, and an
    item bbox here is 3D (with the site's altitude).
    """
    bboxes = [item.bbox for item in items if item.bbox]
    axes = min(len(bbox) for bbox in bboxes) // 2
    lows = [min(bbox[i] for bbox in bboxes) for i in range(axes)]
    highs = [max(bbox[len(bbox) // 2 + i] for bbox in bboxes) for i in range(axes)]
    temporal = pystac.Extent.from_items(items).temporal
    return pystac.Extent(pystac.SpatialExtent([lows + highs]), temporal)


def _collection(collection_id: str, items: list[pystac.Item]) -> pystac.Collection:
    """A product's collection; its extent covers every item.

    Items under several licenses make the collection's license ``other``,
    with a link to each license's text (STAC has no ``various``).
    """
    licenses = {item.properties["license"] for item in items}
    collection = pystac.Collection(
        id=collection_id,
        title=_COLLECTION_TITLES[collection_id],
        description=f"{_COLLECTION_TITLES[collection_id]}, one item per store.",
        extent=_extent(items),
        license=licenses.pop() if len(licenses) == 1 else "other",
    )
    if collection.license == "other":
        for text in sorted({_license_text(item) for item in items}):
            collection.add_link(_license_link(text))
    collection.add_items(items)
    return collection


def _relate_sites(by_site: dict[tuple[str | None, str], list[pystac.Item]]) -> None:
    """Link the items of one site (its GNSS, VOD, geodesy stores) to each other."""
    for site_items in by_site.values():
        for item in site_items:
            for other in site_items:
                if other is not item:
                    item.add_link(pystac.Link(rel="related", target=other))


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
    by_site: dict[tuple[str | None, str], list[pystac.Item]] = {}
    refused: dict[Path, str] = {}
    for candidate in _store_candidates(root):
        try:
            if not _holds_store(candidate):
                continue
            collection_id, site, item = _store_item(candidate)
        except _RefusedError as reason:
            refused[candidate] = str(reason)
            continue
        by_collection.setdefault(collection_id, []).append(item)
        by_site.setdefault(site, []).append(item)
    if refused:
        raise ValueError(_refusal(root, refused))
    _relate_sites(by_site)

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
