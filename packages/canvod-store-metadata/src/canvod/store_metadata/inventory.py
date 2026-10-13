"""Store catalog builder: scan directories for Icechunk stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
from canvod.utils.tools import deprecated

from .io import (
    MIGRATE_COMMAND,
    _written_before_metadata,
    read_metadata,
    store_command,
)
from .location import StoreLocation, open_repository, store_exists
from .schema import StoreMetadata


def _store_candidates(root_dir: Path, recursive: bool = True) -> list[Path]:
    """The folders under root_dir that may hold an Icechunk store.

    A folder with a ``snapshots`` folder is a candidate; Icechunk decides
    whether it holds a repository (:func:`store_exists`).
    """
    if not root_dir.is_dir():
        return []
    # snapshots/ is always non-empty and reliably findable; refs/ may be empty
    # in v2 so we glob on snapshots/ only.
    pattern = "**/snapshots" if recursive else "*/snapshots"
    return sorted({marker.parent for marker in root_dir.glob(pattern)})


def _find_icechunk_stores(root_dir: Path, recursive: bool = True) -> list[Path]:
    """Find the Icechunk stores under root_dir."""
    return [
        candidate
        for candidate in _store_candidates(root_dir, recursive)
        if store_exists(candidate)
    ]


def _metadata_to_row(
    store_path: StoreLocation | Path | str, meta: StoreMetadata
) -> dict[str, Any]:
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
        "needs_migration": False,
        "migrate_command": None,
    }


def _empty_row(store_path: StoreLocation | Path | str) -> dict[str, Any]:
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
        "needs_migration": False,
        "migrate_command": None,
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
    "needs_migration": pl.Boolean,
    "migrate_command": pl.Utf8,
}


def _store_state(store_path: StoreLocation | Path | str) -> str:
    """``"current"``, ``"needs_migration"`` or ``"empty"`` (no metadata, no data)."""
    repo = open_repository(store_path)
    if repo.get_metadata():
        return "current"
    return "needs_migration" if _written_before_metadata(repo) else "empty"


def _row(store_path: StoreLocation | Path | str) -> dict[str, Any]:
    """A store's catalog row; one needing migration says so, with the command."""
    state = _store_state(store_path)
    if state == "empty":
        return _empty_row(store_path)
    if state == "current":
        return _metadata_to_row(store_path, read_metadata(store_path))
    try:
        meta = read_metadata(store_path)
    except KeyError:  # data, but not even old-form metadata
        row, command = _empty_row(store_path), MIGRATE_COMMAND
    else:
        row = _metadata_to_row(store_path, meta)
        command = store_command(
            "migrate-metadata", meta.spatial.site.name, meta.identity.store_type
        )
    return {**row, "needs_migration": True, "migrate_command": command}


def _check_catalog_stores(store_paths: list[Path]) -> None:
    """Refuse a catalog that would leave out a store.

    Raises
    ------
    ValueError
        If a store needs migration or has no metadata.
    """
    problems = []
    for sp in store_paths:
        state = _store_state(sp)
        if state == "needs_migration":
            problems.append(
                f"  {sp}: written before stores kept repository metadata; "
                f"migrate it with {MIGRATE_COMMAND}"
            )
        elif state == "empty":
            problems.append(f"  {sp}: has no metadata and no data")
    if problems:
        msg = (
            "A catalog lists every store under its data root; these stores "
            "cannot be listed:\n" + "\n".join(problems)
        )
        raise ValueError(msg)


def scan_stores(root_dir: Path, recursive: bool = True) -> pl.DataFrame:
    """List the Icechunk stores under a directory, one row per store.

    A store written before stores kept repository metadata is listed with
    ``needs_migration`` and the command that migrates it.

    Returns
    -------
    pl.DataFrame
        One row per store with metadata columns.
    """
    store_paths = _find_icechunk_stores(root_dir, recursive)
    rows = [_row(sp) for sp in store_paths]

    if not rows:
        return pl.DataFrame(schema=_SCHEMA)

    return pl.DataFrame(rows)


def _scan_stores_as_stac(root_dir: Path) -> dict[str, Any]:
    """Build a STAC Catalog JSON dict from stores.

    Raises
    ------
    ValueError
        If a store needs migration or has no metadata: the catalog would
        leave it out.
    """
    store_paths = _find_icechunk_stores(root_dir)
    _check_catalog_stores(store_paths)
    collections: list[dict[str, Any]] = []

    for sp in store_paths:
        meta = read_metadata(sp)

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


def _to_stac_collection(meta: StoreMetadata) -> dict[str, Any]:
    """Convert a single StoreMetadata to a STAC 1.1 Collection dict, in-memory.

    Parameters
    ----------
    meta : StoreMetadata
        Metadata to convert (e.g. from ``read_metadata(store_path)``).

    Returns
    -------
    dict[str, Any]
        A STAC Collection object, ready to ``json.dumps()`` or inspect
        directly -- no file I/O. See ``_write_stac_collection()`` to also
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


def _to_stac_collection_json(meta: StoreMetadata, indent: int = 2) -> str:
    """Convert a single StoreMetadata to a STAC 1.1 Collection JSON string.

    Convenience wrapper around ``_to_stac_collection()`` for callers who want
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
    return json.dumps(_to_stac_collection(meta), indent=indent, default=str)


def _write_stac_collection(
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
    collection = _to_stac_collection(meta)

    if output_path is None:
        output_path = store_path / "collection.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(collection, indent=2, default=str))
    return output_path


def _write_stac_catalog(
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

    Raises
    ------
    ValueError
        If a store needs migration or has no metadata.
    """
    catalog = _scan_stores_as_stac(root_dir)

    if output_path is None:
        output_path = root_dir / "catalog.json"

    # Rewrite links to point to actual collection.json files
    if write_collections:
        for sp in _find_icechunk_stores(root_dir):
            coll_path = _write_stac_collection(sp)
            # Update catalog link to relative path
            rel = coll_path.relative_to(output_path.parent)
            store_id = read_metadata(sp).identity.id
            for link in catalog["links"]:
                if link.get("href") == f"#{store_id}":
                    link["href"] = rel.as_posix()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, default=str))
    return output_path


@deprecated(
    "`scan_stores_as_stac` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.store_metadata.build_catalog` instead: it builds the STAC "
    "catalog of every store under the data root."
)
def scan_stores_as_stac(root_dir: Path) -> dict[str, Any]:
    """Build a STAC Catalog JSON dict from stores (deprecated)."""
    return _scan_stores_as_stac(root_dir)


@deprecated(
    "`to_stac_collection` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.store_metadata.store_item(store_path)` instead: it gives "
    "the STAC item of one store."
)
def to_stac_collection(meta: StoreMetadata) -> dict[str, Any]:
    """Convert a StoreMetadata to a STAC 1.1 Collection dict (deprecated)."""
    return _to_stac_collection(meta)


@deprecated(
    "`to_stac_collection_json` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.store_metadata.store_item(store_path)` instead: it gives "
    "the STAC item of one store; `json.dumps(item.to_dict())` is its JSON."
)
def to_stac_collection_json(meta: StoreMetadata, indent: int = 2) -> str:
    """Convert a StoreMetadata to STAC 1.1 Collection JSON (deprecated)."""
    return _to_stac_collection_json(meta, indent)


@deprecated(
    "`write_stac_collection` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.store_metadata.write_catalog` (or `canvodpy stac write`) "
    "instead: it writes each store's item into the catalog at the data root."
)
def write_stac_collection(
    store_path: Path,
    output_path: Path | None = None,
    branch: str = "main",
) -> Path:
    """Write a STAC Collection JSON file for one store (deprecated)."""
    return _write_stac_collection(store_path, output_path, branch)


@deprecated(
    "`write_stac_catalog` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.store_metadata.write_catalog` (or `canvodpy stac write`) "
    "instead: it writes the catalog at the data root."
)
def write_stac_catalog(
    root_dir: Path,
    output_path: Path | None = None,
    write_collections: bool = True,
) -> Path:
    """Write a STAC Catalog JSON and per-store Collections (deprecated)."""
    return _write_stac_catalog(root_dir, output_path, write_collections)
