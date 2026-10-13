"""What every commit writes into a store that has repository metadata.

ADR 0014: each commit carries

- the **root copy**: the repository metadata in standard form, as flat CF
  and ACDD global attributes, the zarr conventions for ``proj``,
  ``license`` and ``stac``, and the lossless copy under
  ``canvod:repository_metadata``;
- the **snapshot summary**: what the committed data holds;
- the **commit metadata**: software, environment, settings;
- the ``uv.lock`` and ``pyproject.toml`` text, once per lockfile hash, as
  byte arrays in the reserved group ``canvod`` (as arrays, not attributes:
  Icechunk copies attributes into every later snapshot file).

:func:`canvod.store_metadata.io.commit_with_rebase` calls these.
"""

from __future__ import annotations

import copy as copy_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from pydantic import ValidationError
from zarr_cm import license as zarr_license
from zarr_cm import proj as zarr_proj
from zarr_cm import stac as zarr_stac

from .io import _set_field
from .location import StoreLocation, store_location
from .schema import (
    _METADATA_KEY,
    ACDD_TYPES,
    FORM_VERSION,
    READ_CONTEXT,
    ConfigSnapshot,
    RepositoryMetadata,
    StoreMetadata,
    validate_existing,
)
from .summary import _array, summarize_root

#: The conventions the root group follows. CF 1.11 is the newest version
#: IOOS compliance-checker 6.1.0 checks.
CONVENTIONS = "CF-1.11, ACDD-1.3"
FEATURE_TYPE = "timeSeries"

#: The reserved top-level group; never data, never a receiver.
RESERVED_GROUP = "canvod"
ENVIRONMENTS_GROUP = f"{RESERVED_GROUP}/environments"

REPOSITORY_METADATA_ATTR = "canvod:repository_metadata"
SNAPSHOT_SUMMARY_ATTR = "canvod:snapshot_summary"
UUID_ATTR = "canvod:uuid"

# Every root attribute the root copy may write; a commit replaces them all.
_ROOT_COPY_KEYS = (
    "Conventions",
    "featureType",
    "title",
    "summary",
    "keywords",
    "id",
    "naming_authority",
    "date_created",
    "date_modified",
    "creator_name",
    "creator_email",
    "creator_url",
    "creator_type",
    "creator_institution",
    "institution",
    "publisher_name",
    "publisher_url",
    "publisher_type",
    "geospatial_lat_min",
    "geospatial_lat_max",
    "geospatial_lon_min",
    "geospatial_lon_max",
    "geospatial_vertical_min",
    "geospatial_vertical_max",
    "geospatial_vertical_positive",
    "geospatial_vertical_units",
    "platform",
    "instrument",
    "time_coverage_start",
    "time_coverage_end",
    "time_coverage_duration",
    "time_coverage_resolution",
    "proj:code",
    "license",
    "stac:link",
    "zarr_conventions",
    UUID_ATTR,
    REPOSITORY_METADATA_ATTR,
    SNAPSHOT_SUMMARY_ATTR,
    _METADATA_KEY,
)


def _acdd_type(value: str | None) -> str | None:
    """The ACDD word for a creator or publisher type.

    A value outside ``ACDD_TYPES`` is kept: the model refuses it in new
    metadata, and a store already holding one warns when read.
    """
    if value is None:
        return None
    return ACDD_TYPES.get(value, value)


def _acdd_keywords(keywords: list[str]) -> str | None:
    """ACDD keywords: comma-separated, an entry with a comma in quotes."""
    if not keywords:
        return None
    return ", ".join(f'"{k}"' if "," in k else k for k in keywords)


def snapshot_summary(
    root: zarr.Group, repository: dict[str, Any], committed_at: str
) -> dict[str, Any]:
    """The snapshot summary of the data under ``root``."""
    receivers = {
        name: receiver["type"]
        for name, receiver in repository.get("instruments", {})
        .get("receivers", {})
        .items()
    }
    updates = summarize_root(root, receivers)
    summary: dict[str, Any] = {
        "metadata_version": FORM_VERSION,
        "temporal": {"updated": committed_at},
        "spatial": {},
        "receivers": {},
        "summaries": {},
    }
    for key, value in updates.items():
        section, _, rest = key.partition(".")
        if section == "instruments":
            # instruments.receivers.<name>.<field>
            _, name, field = rest.split(".", 2)
            summary["receivers"].setdefault(name, {})[field] = value
        else:
            summary[section][rest] = value

    spatial = repository["spatial"]
    lat, lon = spatial.get("geospatial_lat"), spatial.get("geospatial_lon")
    if lat is not None and lon is not None:
        summary["spatial"].update(
            geospatial_lat_min=lat,
            geospatial_lat_max=lat,
            geospatial_lon_min=lon,
            geospatial_lon_max=lon,
            bbox=[lon, lat, lon, lat],
        )
    return summary


def root_copy(repository: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """The root group attributes for ``repository`` and ``summary``."""
    identity = repository["identity"]
    creator = repository["creator"]
    publisher = repository.get("publisher", {})
    spatial = repository["spatial"]
    instruments = repository.get("instruments", {})
    temporal = summary["temporal"]
    lat, lon = spatial.get("geospatial_lat"), spatial.get("geospatial_lon")
    alt = spatial.get("geospatial_alt_m")

    flat: dict[str, Any] = {
        "Conventions": CONVENTIONS,
        "featureType": FEATURE_TYPE,
        "title": identity["title"],
        "summary": identity.get("description"),
        "keywords": _acdd_keywords(identity.get("keywords", [])),
        "id": identity["id"],
        "naming_authority": identity["naming_authority"],
        "date_created": repository["temporal"]["created"],
        "date_modified": temporal["updated"],
        "creator_name": creator["name"],
        "creator_email": creator["email"],
        "creator_url": creator.get("website"),
        "creator_type": _acdd_type(creator.get("type")),
        "creator_institution": creator.get("institution"),
        "institution": creator.get("institution"),
        "publisher_name": publisher.get("name"),
        "publisher_url": publisher.get("url"),
        "publisher_type": _acdd_type(publisher.get("type")),
        "geospatial_lat_min": lat,
        "geospatial_lat_max": lat,
        "geospatial_lon_min": lon,
        "geospatial_lon_max": lon,
        "geospatial_vertical_min": alt,
        "geospatial_vertical_max": alt,
        "geospatial_vertical_positive": "up" if alt is not None else None,
        "geospatial_vertical_units": "m" if alt is not None else None,
        "platform": instruments.get("platform"),
        "instrument": ", ".join(instruments.get("instruments", [])) or None,
        "time_coverage_start": temporal.get("time_coverage_start"),
        "time_coverage_end": temporal.get("time_coverage_end"),
        "time_coverage_duration": temporal.get("time_coverage_duration"),
        "time_coverage_resolution": temporal.get("time_coverage_resolution"),
        UUID_ATTR: identity["uuid"],
        REPOSITORY_METADATA_ATTR: repository,
        SNAPSHOT_SUMMARY_ATTR: summary,
    }
    attrs = {k: v for k, v in flat.items() if v is not None}

    attrs = zarr_proj.insert(
        attrs,
        zarr_proj.create(code=spatial.get("geospatial_vertical_crs", "EPSG:4979")),
    )
    if publisher.get("license") not in (None, "other"):
        attrs = zarr_license.insert(
            attrs, zarr_license.create(spdx=publisher["license"])
        )
    elif publisher.get("license_uri"):
        attrs = zarr_license.insert(
            attrs, zarr_license.create(url=publisher["license_uri"])
        )
    return zarr_stac.insert(
        attrs, zarr_stac.create(link={"href": identity["stac_link"], "rel": "item"})
    )


def _replay_amendments(copy: dict[str, Any], repository: dict[str, Any]) -> bool:
    """Whether ``copy`` becomes ``repository`` by the amendments made since."""
    done = copy.get("amendments", [])
    amendments = repository.get("amendments", [])
    if amendments[: len(done)] != done:
        return False
    replayed = copy_module.deepcopy({**copy, "amendments": amendments})
    for amendment in amendments[len(done) :]:
        _set_field(replayed, amendment["field"], amendment["new"])
    # An amendment under an unset section (e.g. a receiver's antenna) creates
    # the whole section, with defaults for the fields it does not name.
    try:
        replayed = RepositoryMetadata.model_validate(
            replayed, context=READ_CONTEXT
        ).model_dump(mode="json")
    except ValidationError:
        return False
    return replayed == repository


def check_root_copy(
    attrs: dict[str, Any],
    repository: dict[str, Any],
    store_path: StoreLocation | Path | str,
) -> None:
    """Refuse a root group that no longer matches the repository metadata.

    The root copy last committed must equal the repository metadata, up to
    the amendments made since (the commit of an amendment checks the copy
    from before it against the amended metadata). Its flat attributes must
    be the ones derived from it.

    Raises
    ------
    ValueError
        If the root group was written by an older canvodpy or edited by
        hand.
    """
    copy = attrs.get(REPOSITORY_METADATA_ATTR)
    if copy is None:
        return
    derived = root_copy(copy, attrs.get(SNAPSHOT_SUMMARY_ATTR, {}))
    differing = sorted(
        key
        for key in derived
        if key != REPOSITORY_METADATA_ATTR and attrs.get(key) != derived[key]
    )
    if not _replay_amendments(copy, repository):
        differing.insert(0, REPOSITORY_METADATA_ATTR)
    if differing:
        msg = (
            f"The root group of the store at {store_path} differs from its "
            f"repository metadata ({', '.join(differing)}): it was written by "
            "an older canvodpy or edited by hand. Upgrade canvodpy and run "
            "validate_all on the store; nothing was committed."
        )
        raise ValueError(msg)


def commit_metadata(
    repository: dict[str, Any],
    config: Any,
    store_path: StoreLocation | Path | str,
    committed_at: str,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The commit metadata, and the lockfile texts it refers to by hash.

    ``config`` is the settings object (or an already taken
    :class:`ConfigSnapshot`).
    """
    from .collectors import (
        collect_config_snapshot,
        collect_environment,
        collect_processing_provenance,
    )

    identity = repository["identity"]
    processing = collect_processing_provenance(
        identity["store_type"], identity["source_format"]
    )
    processing.datetime = committed_at
    environment = collect_environment(store_location(store_path).local_path)
    snapshot = (
        config
        if isinstance(config, ConfigSnapshot)
        else collect_config_snapshot(config)
    )
    texts = {
        "uv_lock_hash": environment.uv_lock_hash,
        "uv_lock": environment.uv_lock_text,
        "pyproject_toml": environment.pyproject_toml_text,
    }
    metadata = {
        "processing": processing.model_dump(mode="json"),
        "environment": environment.model_dump(
            mode="json", exclude={"uv_lock_text", "pyproject_toml_text"}
        ),
        "config": snapshot.model_dump(mode="json"),
    }
    return metadata, texts


def lockfile_stored(root: zarr.Group, lock_hash: str | None) -> bool:
    """Whether the lockfile texts for ``lock_hash`` are stored (or there are none)."""
    return lock_hash is None or f"{ENVIRONMENTS_GROUP}/{lock_hash}" in root


def _write_environment(root: zarr.Group, texts: dict[str, str | None]) -> None:
    """Store the lockfile texts once per hash."""
    lock_hash = texts["uv_lock_hash"]
    if lock_hash is None:
        return
    environments = root.require_group(ENVIRONMENTS_GROUP)
    if lock_hash in environments:
        return
    group = environments.require_group(lock_hash)
    for name in ("uv_lock", "pyproject_toml"):
        text = texts[name]
        if text is not None:
            group.create_array(name, data=np.frombuffer(text.encode(), dtype="u1"))


def prepare_commit(
    root: zarr.Group,
    repository: dict[str, Any],
    *,
    store_path: StoreLocation | Path | str,
    config: Any,
) -> dict[str, Any]:
    """Write the root copy, summary and lockfile text; return the commit metadata.

    Raises
    ------
    ValueError
        If the root group last committed differs from the repository
        metadata (see :func:`check_root_copy`).
    """
    check_root_copy(dict(root.attrs), repository, store_path)
    committed_at = datetime.now(UTC).isoformat()
    metadata, texts = commit_metadata(repository, config, store_path, committed_at)
    _write_environment(root, texts)

    summary = snapshot_summary(root, repository, committed_at)
    attrs = {k: v for k, v in root.attrs.items() if k not in _ROOT_COPY_KEYS}
    root.attrs.put({**attrs, **root_copy(repository, summary)})
    return metadata


def _environment_texts(root: zarr.Group, lock_hash: str | None) -> dict[str, str]:
    """The lockfile texts stored for ``lock_hash`` (see :func:`_write_environment`)."""
    path = f"{ENVIRONMENTS_GROUP}/{lock_hash}"
    if lock_hash is None or path not in root:
        return {}
    group = root[path]
    if not isinstance(group, zarr.Group):
        return {}
    return {
        f"{name}_text": bytes(np.asarray(_array(group, name)[...])).decode()
        for name in ("uv_lock", "pyproject_toml")
        if name in group
    }


def combined_metadata(
    root: zarr.Group, commit_metadata: dict[str, Any]
) -> StoreMetadata:
    """One :class:`StoreMetadata` for a snapshot.

    From its root copy and snapshot summary (the attributes of ``root``), its
    commit metadata, and the lockfile text stored for the commit's lockfile
    hash.
    """
    attrs: dict[str, Any] = dict(root.attrs)
    data = _combine(
        attrs[REPOSITORY_METADATA_ATTR], attrs[SNAPSHOT_SUMMARY_ATTR], commit_metadata
    )
    if "environment" in data:
        data["environment"] = {
            **data["environment"],
            **_environment_texts(root, data["environment"].get("uv_lock_hash")),
        }
    return validate_existing(StoreMetadata, data)


def preview_metadata(root: zarr.Group, repository: dict[str, Any]) -> StoreMetadata:
    """The metadata a commit of ``root`` would give, before it is written.

    Repository metadata plus the snapshot summary of the data under
    ``root``; without commit metadata (software, environment, settings).
    """
    summary = snapshot_summary(root, repository, datetime.now(UTC).isoformat())
    return StoreMetadata.model_validate(_combine(repository, summary, {}))


def _combine(
    repository: dict[str, Any],
    summary: dict[str, Any],
    commit_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Repository metadata, snapshot summary and commit metadata as one dict."""
    data: dict[str, Any] = {**repository}
    data["identity"] = {**data["identity"], "conventions": CONVENTIONS}
    data["temporal"] = {**data["temporal"], **summary["temporal"]}
    data["spatial"] = {**data["spatial"], **summary["spatial"]}
    receivers = data.get("instruments", {}).get("receivers", {})
    data["instruments"] = {
        **data.get("instruments", {}),
        "receivers": {
            name: {**receiver, **summary["receivers"].get(name, {})}
            for name, receiver in receivers.items()
        },
    }
    data["summaries"] = summary["summaries"]
    for section in ("processing", "environment", "config"):
        if section in commit_metadata:
            data[section] = commit_metadata[section]
    return data
