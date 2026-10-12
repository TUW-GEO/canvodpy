"""Store catalog builder: scan directories for Icechunk stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from .io import metadata_exists, read_metadata
from .schema import StoreMetadata


def _is_icechunk_store(path: Path) -> bool:
    """Return True if path looks like an Icechunk ≥2.0 store.

    Icechunk 2.x layout: snapshots/ + transactions/ directories at the root.
    """
    return (path / "snapshots").is_dir() and (path / "transactions").is_dir()


def _find_icechunk_stores(root_dir: Path, recursive: bool = True) -> list[Path]:
    """Find Icechunk stores under root_dir by their layout markers."""
    stores: list[Path] = []
    if not root_dir.is_dir():
        return stores

    # snapshots/ is always non-empty and reliably findable; refs/ may be empty
    # in v2 so we glob on snapshots/ only.
    pattern = "**/snapshots" if recursive else "*/snapshots"
    for marker in root_dir.glob(pattern):
        candidate = marker.parent
        if _is_icechunk_store(candidate):
            stores.append(candidate)

    return sorted(set(stores))


def _metadata_to_row(store_path: Path, meta: StoreMetadata) -> dict[str, Any]:
    """Convert metadata to a flat dict for a DataFrame row."""
    return {
        "id": meta.identity.id,
        "title": meta.identity.title,
        "store_type": meta.identity.store_type,
        "source_format": meta.identity.source_format,
        "site": meta.spatial.site.name,
        "creator": meta.creator.name,
        "institution": meta.creator.institution,
        "license": meta.publisher.license,
        "created": meta.temporal.created,
        "updated": meta.temporal.updated,
        "time_start": meta.temporal.collected_start,
        "time_end": meta.temporal.collected_end,
        "lat": meta.spatial.geospatial_lat,
        "lon": meta.spatial.geospatial_lon,
        "total_epochs": meta.summaries.total_epochs,
        "total_sids": meta.summaries.total_sids,
        "file_count": meta.summaries.file_count,
        "store_size_mb": meta.summaries.store_size_mb,
        "path": str(store_path),
    }


def _empty_row(store_path: Path) -> dict[str, Any]:
    """Row for a store without metadata."""
    return {
        "id": None,
        "title": None,
        "store_type": None,
        "source_format": None,
        "site": None,
        "creator": None,
        "institution": None,
        "license": None,
        "created": None,
        "updated": None,
        "time_start": None,
        "time_end": None,
        "lat": None,
        "lon": None,
        "total_epochs": None,
        "total_sids": None,
        "file_count": None,
        "store_size_mb": None,
        "path": str(store_path),
    }


_SCHEMA = {
    "id": pl.Utf8,
    "title": pl.Utf8,
    "store_type": pl.Utf8,
    "source_format": pl.Utf8,
    "site": pl.Utf8,
    "creator": pl.Utf8,
    "institution": pl.Utf8,
    "license": pl.Utf8,
    "created": pl.Utf8,
    "updated": pl.Utf8,
    "time_start": pl.Utf8,
    "time_end": pl.Utf8,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "total_epochs": pl.Int64,
    "total_sids": pl.Int64,
    "file_count": pl.Int64,
    "store_size_mb": pl.Float64,
    "path": pl.Utf8,
}


def scan_stores(root_dir: Path, recursive: bool = True) -> pl.DataFrame:
    """Walk directories, find Icechunk stores, build a catalog.

    Returns
    -------
    pl.DataFrame
        One row per store with metadata columns.
    """
    store_paths = _find_icechunk_stores(root_dir, recursive)
    rows: list[dict[str, Any]] = []

    for sp in store_paths:
        if metadata_exists(sp):
            try:
                meta = read_metadata(sp)
                rows.append(_metadata_to_row(sp, meta))
            except Exception:
                rows.append(_empty_row(sp))
        else:
            rows.append(_empty_row(sp))

    if not rows:
        return pl.DataFrame(schema=_SCHEMA)

    return pl.DataFrame(rows)


def scan_stores_as_stac(root_dir: Path) -> dict[str, Any]:
    """Build a STAC Catalog JSON dict from stores."""
    store_paths = _find_icechunk_stores(root_dir)
    collections: list[dict[str, Any]] = []

    for sp in store_paths:
        if not metadata_exists(sp):
            continue
        try:
            meta = read_metadata(sp)
        except Exception:
            continue

        collection: dict[str, Any] = {
            "type": "Collection",
            "stac_version": "1.1.0",
            "id": meta.identity.id,
            "title": meta.identity.title,
            "description": meta.identity.description or "",
            "license": meta.publisher.license or "proprietary",
            "extent": {
                "spatial": {
                    "bbox": ([meta.spatial.bbox] if meta.spatial.bbox else [[]])
                },
                "temporal": {
                    "interval": (
                        meta.spatial.extent_temporal_interval
                        or [
                            [
                                meta.temporal.collected_start,
                                meta.temporal.collected_end,
                            ]
                        ]
                    )
                },
            },
            "links": [],
        }
        if meta.identity.keywords:
            collection["keywords"] = meta.identity.keywords
        collections.append(collection)

    return {
        "type": "Catalog",
        "stac_version": "1.1.0",
        "id": "canvod-catalog",
        "description": "canVOD Icechunk Store Catalog",
        "links": [{"rel": "child", "href": f"#{c['id']}"} for c in collections],
        "collections": collections,
    }


def to_stac_collection(meta: StoreMetadata) -> dict[str, Any]:
    """Convert a single StoreMetadata to a STAC 1.1 Collection dict, in-memory.

    Parameters
    ----------
    meta : StoreMetadata
        Metadata to convert (e.g. from ``read_metadata(store_path)``).

    Returns
    -------
    dict[str, Any]
        A STAC Collection object, ready to ``json.dumps()`` or inspect
        directly -- no file I/O. See ``write_stac_collection()`` to also
        persist it to disk.
    """
    collection: dict[str, Any] = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": meta.identity.id,
        "title": meta.identity.title,
        "description": meta.identity.description or "",
        "license": meta.publisher.license or "proprietary",
        "extent": {
            "spatial": {
                "bbox": [meta.spatial.bbox] if meta.spatial.bbox else [[]],
            },
            "temporal": {
                "interval": meta.spatial.extent_temporal_interval
                or [
                    [
                        meta.temporal.collected_start,
                        meta.temporal.collected_end,
                    ]
                ],
            },
        },
        "links": [],
        "providers": [
            {
                "name": meta.creator.institution,
                "roles": ["producer", "host"],
                "url": meta.creator.website or "",
            }
        ],
        "summaries": {},
    }
    if meta.identity.keywords:
        collection["keywords"] = meta.identity.keywords
    if meta.summaries.constellations:
        collection["summaries"]["constellations"] = meta.summaries.constellations
    if meta.summaries.variables:
        collection["summaries"]["variables"] = meta.summaries.variables
    return collection


def to_stac_collection_json(meta: StoreMetadata, indent: int = 2) -> str:
    """Convert a single StoreMetadata to a STAC 1.1 Collection JSON string.

    Convenience wrapper around ``to_stac_collection()`` for callers who want
    the serialized form directly (e.g. to display, hash, or send over the
    wire) without touching the filesystem.

    Parameters
    ----------
    meta : StoreMetadata
        Metadata to convert.
    indent : int
        JSON indentation width.

    Returns
    -------
    str
        The STAC Collection, serialized as JSON.
    """
    return json.dumps(to_stac_collection(meta), indent=indent, default=str)


def write_stac_collection(
    store_path: Path,
    output_path: Path | None = None,
    branch: str = "main",
) -> Path:
    """Write a STAC Collection JSON file for a single store.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store.
    output_path : Path | None
        Output JSON file path. Defaults to ``store_path / "collection.json"``.
    branch : str
        Store branch to read metadata from.

    Returns
    -------
    Path
        The written JSON file path.
    """
    meta = read_metadata(store_path, branch)
    collection = to_stac_collection(meta)

    if output_path is None:
        output_path = store_path / "collection.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(collection, indent=2, default=str))
    return output_path


def write_stac_catalog(
    root_dir: Path,
    output_path: Path | None = None,
    write_collections: bool = True,
) -> Path:
    """Write a STAC Catalog JSON and optional per-store Collection JSONs.

    Parameters
    ----------
    root_dir : Path
        Root directory to scan for Icechunk stores.
    output_path : Path | None
        Output catalog JSON path. Defaults to ``root_dir / "catalog.json"``.
    write_collections : bool
        If True, also write a ``collection.json`` next to each store.

    Returns
    -------
    Path
        The written catalog JSON file path.
    """
    catalog = scan_stores_as_stac(root_dir)

    if output_path is None:
        output_path = root_dir / "catalog.json"

    # Rewrite links to point to actual collection.json files
    if write_collections:
        store_paths = _find_icechunk_stores(root_dir)
        for sp in store_paths:
            if not metadata_exists(sp):
                continue
            try:
                coll_path = write_stac_collection(sp)
                # Update catalog link to relative path
                rel = coll_path.relative_to(output_path.parent)
                for link in catalog["links"]:
                    meta = read_metadata(sp)
                    if link.get("href") == f"#{meta.identity.id}":
                        link["href"] = str(rel)
            except Exception:
                continue

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, default=str))
    return output_path
