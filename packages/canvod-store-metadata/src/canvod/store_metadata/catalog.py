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

Each write replaces the latest catalog fully: the catalog, collection and
item files of the previous write that the new one has no use for are
removed, and only those. Any other file stays, and ``releases/`` is never
touched. Each file is replaced in one step, so a reader or a second
writer never sees half a file; of two writers at once, the last one wins.

A release (:func:`create_release`) tags ``main`` in every store with the
same Icechunk tag and writes the catalog of that tag under
``releases/<tag>/``: the same tree, each asset pinned to the tag and the
snapshot it points at. A release catalog is never changed afterwards.
"""

from __future__ import annotations

import json
import os
import uuid
import warnings
from dataclasses import dataclass
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
_RELEASES = "releases"
_COLLECTION_TITLES = {
    "gnss-observations": "GNSS observations",
    "vod": "Vegetation optical depth",
    "gnss-geodesy": "GNSS geodesy",
}


class _RefusedError(ValueError):
    """Why a store cannot be described in the catalog."""


@dataclass(frozen=True)
class _Described:
    """A store as the catalog describes it: at one snapshot, in one collection."""

    path: Path
    snapshot_id: str
    collection_id: str
    site: tuple[str | None, str]
    item: pystac.Item


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


def _period(meta: StoreMetadata) -> tuple[Any, Any]:
    """The start and end of the store's data, from its time coverage."""
    temporal = meta.temporal
    if not (temporal.time_coverage_start and temporal.time_coverage_end):
        msg = (
            "holds no data (no temporal.time_coverage_start, "
            "temporal.time_coverage_end); a store gets its time coverage from "
            "the run that writes its data"
        )
        raise _RefusedError(msg)
    return (
        pystac.utils.str_to_datetime(temporal.time_coverage_start),
        pystac.utils.str_to_datetime(temporal.time_coverage_end),
    )


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
    # By name: the store lists its arrays in no fixed order, and the same
    # store must give the same catalog file.
    for name, array in sorted(group.arrays(), key=lambda pair: pair[0]):
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
    release: str | None,
    extra: dict[str, Any] | None = None,
) -> pystac.Asset:
    """An asset of the dataset in ``group``: the store, snapshot and group.

    A release asset also names its tag; only a latest-catalog asset has the
    role ``latest-version``.
    """
    return pystac.Asset(
        href=str(store_path.resolve()),
        title=title,
        media_type=ZARR_MEDIA_TYPE,
        roles=[role] if release else [role, "latest-version"],
        extra_fields={
            "canvod:snapshot_id": snapshot_id,
            **({"canvod:tag": release} if release else {}),
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
    store_path: Path, snapshot_id: str, meta: StoreMetadata, release: str | None
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
            release=release,
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
                release=release,
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
                release=release,
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
        return _store_item(store_path).item
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


def _store_item(store_path: Path, release: str | None = None) -> _Described:
    """A store described at ``main``, or at the tag ``release``.

    The site is the naming authority and the site name: two networks may
    name a site alike. The item is described at :func:`store_item`.

    Raises
    ------
    _RefusedError
        If the store cannot be described: it cannot be opened, has no
        metadata or needs migration, has no site position, its license
        is missing or breaks the license rule, it holds no data (no time
        coverage), or it has no tag ``release``.
    """
    try:
        repo = open_repository(store_path)
    except (icechunk.IcechunkError, OSError) as error:
        raise _cannot_open(error) from error
    try:
        snapshot_id = (
            repo.lookup_tag(release) if release else repo.lookup_branch("main")
        )
    except icechunk.IcechunkError as error:
        if release:
            raise _RefusedError(f"has no tag {release!r}") from error
        raise _cannot_open(error) from error
    if not repo.get_metadata():
        raise _RefusedError(_without_metadata(store_path, repo))
    meta = _read_quietly(store_path, snapshot_id=snapshot_id)
    geometry, bbox = _geometry(meta)
    license_ = _license(meta)
    start, end = _period(meta)
    item = pystac.Item(
        id=_item_id(meta),
        geometry=geometry,
        bbox=bbox,
        datetime=None,
        start_datetime=start,
        end_datetime=end,
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
    for key, asset in _assets(store_path, snapshot_id, meta, release).items():
        item.add_asset(key, asset)
    site = (meta.identity.naming_authority, meta.spatial.site.name)
    return _Described(store_path, snapshot_id, _collection_id(meta), site, item)


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


def _refusal(root: Path, refused: dict[Path, str], what: str = "catalog") -> str:
    lines = [
        f"No {what} was written: {len(refused)} store(s) under {root} cannot "
        "be described.",
        *(
            f"  {path.relative_to(root).as_posix()}: {reason}"
            for path, reason in sorted(refused.items())
        ),
    ]
    return "\n".join(lines)


def _describe(root: Path, release: str | None = None) -> list[_Described]:
    """Every store under ``root``, described at ``main`` or at ``release``.

    Raises
    ------
    ValueError
        Listing every store that cannot be described, with its reason.
    """
    described: list[_Described] = []
    refused: dict[Path, str] = {}
    for candidate in _store_candidates(root):
        try:
            if _holds_store(candidate):
                described.append(_store_item(candidate, release))
        except _RefusedError as reason:
            refused[candidate] = str(reason)
    if refused:
        what = f"release {release!r}" if release else "catalog"
        raise ValueError(_refusal(root, refused, what))
    return described


def build_catalog(root: Path | str, *, release: str | None = None) -> pystac.Catalog:
    """The catalog of every store under ``root``, in memory.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).
    release
        A release tag: the catalog of every store at that tag, each asset
        naming the tag. ``None``: the latest catalog, of ``main``.

    Raises
    ------
    ValueError
        Listing every store that cannot be described, with its reason: it
        cannot be opened, has no metadata, needs migration (with the
        migrate command), has no site position, its license is missing
        or not usable (not SPDX, or ``other`` without ``license_uri``), or
        it has no tag ``release``.
    """
    return _catalog(_describe(Path(root), release), release)


def _catalog(described: list[_Described], release: str | None) -> pystac.Catalog:
    by_collection: dict[str, list[pystac.Item]] = {}
    by_site: dict[tuple[str | None, str], list[pystac.Item]] = {}
    for store in described:
        by_collection.setdefault(store.collection_id, []).append(store.item)
        by_site.setdefault(store.site, []).append(store.item)
    _relate_sites(by_site)

    catalog = pystac.Catalog(
        id=_CATALOG_ID,
        title=f"canVODpy stores, release {release}" if release else "canVODpy stores",
        description=(
            f"Every store under this data root at the release tag {release}, "
            "by product."
            if release
            else "Every store under this data root, by product."
        ),
    )
    for collection_id in sorted(by_collection):
        catalog.add_child(_collection(collection_id, by_collection[collection_id]))
    return catalog


def write_catalog(root: Path | str, *, release: str | None = None) -> Path:
    """Write the latest catalog of every store under ``root``, beside them.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).
    release
        A release tag the stores already have: write the catalog of that
        release under ``releases/<tag>/`` instead. :func:`create_release`
        tags the stores and calls this.

    Returns
    -------
    Path
        The written ``catalog.json``.

    Raises
    ------
    ValueError
        Listing every store that cannot be described (see
        :func:`build_catalog`); nothing is written. With ``release``, also
        if the tag is not a single folder name or its catalog exists
        already: a release catalog is never changed.
    """
    root = Path(root).resolve()
    if release is not None:
        _check_tag(release)
        _refuse_written_release(root, release)
        return _save_release(root, release, _describe(root, release))
    catalog = build_catalog(root)
    previous = _written_files(root)
    _save(catalog, root)
    current = {Path(obj.self_href).resolve() for obj in _catalog_objects(catalog)}
    for path in sorted(previous - current):
        path.unlink(missing_ok=True)
        _remove_empty_folders(path.parent, root)
    return root / "catalog.json"


def create_release(root: Path | str, tag: str) -> Path:
    """Tag ``main`` in every store under ``root`` and write the release catalog.

    Every store gets the Icechunk tag ``tag`` on the snapshot of ``main``
    the release describes, and ``releases/<tag>/`` gets the catalog of
    that tag: the latest catalog's tree, each asset naming the tag and its
    snapshot. If the stores have the tag already (a release whose catalog
    write failed), only the catalog is written.

    Parameters
    ----------
    root
        The data root (``storage.stores_root_dir``).
    tag
        The release tag, for example ``v2026.1``. It holds no ``/``: that
        keeps it apart from the keeper tags (``keep/<receiver>/<date>``),
        and ``releases/<tag>/`` one folder deep.

    Returns
    -------
    Path
        The release's ``catalog.json``.

    Raises
    ------
    ValueError
        Before anything is tagged or written: the tag holds a ``/``, the
        release catalog exists already, a store cannot be described (see
        :func:`build_catalog`, all of them listed), no store is under
        ``root``, or some stores have the tag and others don't (those that
        have it listed).
    """
    root = Path(root).resolve()
    _check_tag(tag)
    _refuse_written_release(root, tag)
    stores = _describe(root)
    if not stores:
        msg = f"No release was written: no store under {root}."
        raise ValueError(msg)
    tagged = [store.path for store in stores if tag in _tags(store.path)]
    if tagged and len(tagged) < len(stores):
        lines = [
            f"Release tag {tag!r} exists already in {len(tagged)} store(s) under "
            f"{root}; no store was tagged:",
            *(f"  {path.relative_to(root).as_posix()}" for path in sorted(tagged)),
        ]
        raise ValueError("\n".join(lines))
    if not tagged:
        for store in stores:
            open_repository(store.path).create_tag(tag, store.snapshot_id)
    return _save_release(root, tag, _describe(root, tag))


def _tags(store_path: Path) -> set[str]:
    return set(open_repository(store_path).list_tags())


def _check_tag(tag: str) -> None:
    if "/" in tag or "\\" in tag or tag in {"", ".", ".."}:
        msg = (
            f"Release tag {tag!r} is refused: a release tag holds no '/' "
            "(keeper tags are keep/<receiver>/<date>) and names one folder "
            f"under {_RELEASES}/."
        )
        raise ValueError(msg)


def _refuse_written_release(root: Path, tag: str) -> None:
    catalog_file = root / _RELEASES / tag / "catalog.json"
    if catalog_file.exists():
        msg = (
            f"Release {tag!r} exists: {catalog_file}. A release catalog is "
            "never changed; choose another tag."
        )
        raise ValueError(msg)


def _save_release(root: Path, tag: str, described: list[_Described]) -> Path:
    folder = root / _RELEASES / tag
    _save(_catalog(described, tag), folder)
    return folder / "catalog.json"


def _save(catalog: pystac.Catalog, folder: Path) -> None:
    """Save ``catalog`` under ``folder``, self-contained, all hrefs relative."""
    catalog.normalize_hrefs(str(folder))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(
        catalog_type=pystac.CatalogType.SELF_CONTAINED, stac_io=_ReplacingStacIO()
    )


class _ReplacingStacIO(pystac.stac_io.DefaultStacIO):
    """Writes each file beside its target first, then replaces it in one step."""

    def write_text_to_href(self, href: str, txt: str) -> None:
        target = Path(href)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Not tempfile.mkstemp: its files are readable by the owner only.
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(txt, encoding="utf-8")
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def _catalog_objects(catalog: pystac.Catalog) -> list[pystac.STACObject]:
    collections = list(catalog.get_children())
    items = [item for child in collections for item in child.get_items()]
    return [catalog, *collections, *items]


def _linked(path: Path, rel: str) -> list[Path]:
    """The files a catalog file links as ``rel``; none if it cannot be read."""
    try:
        links = json.loads(path.read_text(encoding="utf-8")).get("links", [])
    except OSError, ValueError, AttributeError:
        return []
    return [
        (path.parent / link["href"]).resolve()
        for link in links
        if isinstance(link, dict)
        and link.get("rel") == rel
        and isinstance(link.get("href"), str)
        and "://" not in link["href"]
    ]


def _written_files(root: Path) -> set[Path]:
    """The collection and item files the previous write left under ``root``.

    Found by following the links of the previous ``catalog.json``, so a file
    it did not write is never among them; nothing under ``releases/`` is.
    """
    catalog_file = root / "catalog.json"
    try:
        if (
            json.loads(catalog_file.read_text(encoding="utf-8")).get("id")
            != _CATALOG_ID
        ):
            return set()
    except OSError, ValueError, AttributeError:
        return set()
    collections = _linked(catalog_file, "child")
    items = [item for collection in collections for item in _linked(collection, "item")]
    releases = root / _RELEASES
    return {
        path
        for path in (*collections, *items)
        if root in path.parents and releases not in path.parents
    }


def _remove_empty_folders(folder: Path, root: Path) -> None:
    while folder != root and root in folder.parents and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
