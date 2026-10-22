"""Runtime collectors: pure functions that gather metadata."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from canvod.config.store_names import store_folder_name

from .content import CONTENT_STORE_TYPES, new_content_settings
from .identity import (
    NAMING_AUTHORITY_SETTING,
    check_naming_authority,
    new_uuid,
    stac_link,
    store_id,
)
from .location import StoreLocation, store_location
from .machine import without_machine_settings
from .schema import (
    ConfigSnapshot,
    Creator,
    Environment,
    Instruments,
    ProcessingProvenance,
    Publisher,
    ReceiverInfo,
    References,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
    VodAnalysisInfo,
)

if TYPE_CHECKING:
    pass


def collect_software_versions() -> dict[str, str]:
    """Collect versions of key packages via importlib.metadata."""
    return dict(_software_versions())


@functools.cache
def _software_versions() -> dict[str, str]:
    """The installed versions, looked up once per process."""
    import importlib.metadata

    packages = [
        "canvodpy",
        "canvod-utils",
        "canvod-config",
        "canvod-readers",
        "canvod-auxiliary",
        "canvod-preflight",
        "canvod-vod",
        "canvod-grids",
        "canvod-ops",
        "canvod-store-metadata",
        "canvod-store",
        "canvod-viz",
        "icechunk",
        "zarr",
        "xarray",
        "dask",
        "numpy",
        "polars",
        "pydantic",
    ]
    versions: dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


@functools.cache
def collect_python_info() -> str:
    """Return Python version + implementation."""
    return f"{sys.version} ({platform.python_implementation()})"


@functools.cache
def collect_uv_version() -> str | None:
    """Return the uv version number, or None if uv is not installed.

    Only the number is kept (``"0.13.1"``): ``uv --version`` may add how
    uv was built and the platform, for example
    ``"uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)"``, and the
    store records no machine information. Asked once per process.
    """
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            match = re.match(r"uv\s+(\S+)", result.stdout.strip())
            return match.group(1) if match else None
    except FileNotFoundError, subprocess.TimeoutExpired:
        pass
    return None


def _find_project_root() -> Path | None:
    """The uv project the process runs from: the nearest directory, from
    the working directory up, that holds ``pyproject.toml`` and ``uv.lock``.

    ``None`` outside such a project; no lockfile is recorded then.
    """
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / "pyproject.toml").is_file() and (path / "uv.lock").is_file():
            return path
    return None


def _project_files(root: Path) -> tuple[str, str, str]:
    """``pyproject.toml`` text, ``uv.lock`` text and its SHA256.

    Read again only when either file changed (modification time or size).
    """
    pyproject, lock = (root / "pyproject.toml").stat(), (root / "uv.lock").stat()
    return _read_project_files(
        root,
        (pyproject.st_mtime_ns, pyproject.st_size),
        (lock.st_mtime_ns, lock.st_size),
    )


@functools.lru_cache(maxsize=8)
def _read_project_files(
    root: Path, pyproject_key: tuple[int, int], lock_key: tuple[int, int]
) -> tuple[str, str, str]:
    """Read the project files; the keys only identify their versions."""
    lock = (root / "uv.lock").read_bytes()
    return (
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        lock.decode("utf-8"),
        hashlib.sha256(lock).hexdigest(),
    )


def collect_environment(
    store_path: Path | None = None,
    dask_workers: int | None = None,
    dask_threads_per_worker: int | None = None,
    record_machine: bool = True,
) -> Environment:
    """Collect runtime environment information.

    With ``record_machine=False`` the computer (operating system, architecture,
    CPU count, memory, free disk) is not recorded: those fields are
    ``None`` (``processing.metadata.record_machine``).
    """
    # Raw pyproject.toml + uv.lock of the project the process runs from
    pyproject_text = uv_lock_text = uv_lock_hash = None
    root = _find_project_root()
    if root is not None:
        pyproject_text, uv_lock_text, uv_lock_hash = _project_files(root)
    if not record_machine:
        return Environment(
            dask_workers=dask_workers,
            dask_threads_per_worker=dask_threads_per_worker,
            uv_lock_hash=uv_lock_hash,
            pyproject_toml_text=pyproject_text,
            uv_lock_text=uv_lock_text,
        )

    memory_gb = None
    try:
        import psutil

        memory_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass

    disk_free_gb = None
    if store_path is not None:
        check_path = store_path if store_path.exists() else store_path.parent
        if check_path.exists():
            usage = shutil.disk_usage(check_path)
            disk_free_gb = round(usage.free / (1024**3), 1)

    return Environment(
        os=platform.platform(),
        arch=platform.machine(),
        cpu_count=os.cpu_count(),
        memory_gb=memory_gb,
        disk_free_gb=disk_free_gb,
        dask_workers=dask_workers,
        dask_threads_per_worker=dask_threads_per_worker,
        uv_lock_hash=uv_lock_hash,
        pyproject_toml_text=pyproject_text,
        uv_lock_text=uv_lock_text,
    )


def records_machine(config: Any) -> bool:
    """``processing.metadata.record_machine`` of ``config``: settings, a
    plain dict of them or a :class:`ConfigSnapshot`; true when not set."""
    processing = (
        config.get("processing")
        if isinstance(config, dict)
        else getattr(config, "processing", None)
    )
    metadata = (
        processing.get("metadata")
        if isinstance(processing, dict)
        else getattr(processing, "metadata", None)
    )
    value = (
        metadata.get("record_machine")
        if isinstance(metadata, dict)
        else getattr(metadata, "record_machine", None)
    )
    return value is not False


#: Settings never written into a store: account details for data servers.
_PRIVATE_PROCESSING_KEYS = ("credentials",)


def collect_config_snapshot(config: Any) -> ConfigSnapshot:
    """Serialize config sections + compute SHA256 hash.

    Left out (and out of the hash), because stores are shared:
    ``processing.credentials``, the account details for data servers, and
    the settings of one computer (:data:`~.machine.MACHINE_SETTINGS`, and
    the stores' root when it is a local folder). The same settings on two
    computers give the same hash.
    """
    sections: dict[str, Any] = {}
    keys = (
        "processing",
        "preprocessing",
        "aux_data",
        "netcdf_compression",
        "icechunk",
        "sids",
    )
    for key in keys:
        if isinstance(config, dict):
            obj = config.get(key)
        else:
            obj = getattr(config, key, None)
        if obj is None:
            proc = getattr(config, "processing", None)
            if proc is not None:
                obj = getattr(proc, key, None)
        if obj is not None:
            if hasattr(obj, "model_dump"):
                sections[key] = obj.model_dump(mode="json")
            elif isinstance(obj, dict):
                sections[key] = obj
            else:
                sections[key] = str(obj)

    if isinstance(sections.get("processing"), dict):
        sections["processing"] = without_machine_settings(
            {
                "processing": {
                    k: v
                    for k, v in sections["processing"].items()
                    if k not in _PRIVATE_PROCESSING_KEYS
                }
            }
        )["processing"]

    config_str = json.dumps(sections, sort_keys=True, default=str)
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()

    return ConfigSnapshot(
        processing=sections.get("processing"),
        preprocessing=sections.get("preprocessing"),
        aux_data=sections.get("aux_data"),
        compression=sections.get("netcdf_compression"),
        icechunk=sections.get("icechunk"),
        sids=sections.get("sids"),
        config_hash=config_hash,
    )


def collect_creator(metadata_config: Any) -> Creator:
    """Build Creator from MetadataConfig."""
    return Creator(
        name=metadata_config.author,
        email=str(metadata_config.email),
        orcid=getattr(metadata_config, "orcid", None),
        institution=metadata_config.institution,
        institution_ror=getattr(metadata_config, "institution_ror", None),
        department=getattr(metadata_config, "department", None),
        research_group=getattr(metadata_config, "research_group", None),
        website=getattr(metadata_config, "website", None),
    )


def collect_publisher(metadata_config: Any) -> Publisher:
    """Build Publisher from MetadataConfig."""
    return Publisher(
        name=getattr(metadata_config, "publisher", None),
        url=getattr(metadata_config, "publisher_url", None),
        license=getattr(metadata_config, "license", None),
        license_uri=getattr(metadata_config, "license_uri", None),
    )


def collect_spatial(site_config: Any, site_name: str) -> SpatialExtent:
    """Build SpatialExtent from SiteConfig."""
    lat = getattr(site_config, "latitude", None)
    lon = getattr(site_config, "longitude", None)
    alt = getattr(site_config, "altitude_m", None)

    bbox = None
    if lat is not None and lon is not None:
        bbox = [lon, lat, lon, lat]

    return SpatialExtent(
        site=SiteInfo(
            name=site_name,
            description=getattr(site_config, "description", None),
            country=getattr(site_config, "country", None),
        ),
        geospatial_lat=lat,
        geospatial_lon=lon,
        geospatial_alt_m=alt,
        geospatial_lat_min=lat,
        geospatial_lat_max=lat,
        geospatial_lon_min=lon,
        geospatial_lon_max=lon,
        bbox=bbox,
    )


def collect_receiver(
    receiver_config: Any, site_name: str | None = None
) -> ReceiverInfo:
    """A receiver's entry in the store metadata, from its settings.

    With ``site_name``, a receiver with a naming recipe also gets the
    sha256 of its recipe file (:func:`recipe_sha256_of`).
    """
    recipe = getattr(receiver_config, "recipe", None)
    return ReceiverInfo(
        type=receiver_config.type,
        directory=receiver_config.directory,
        reader_format=getattr(receiver_config, "reader_format", "auto"),
        description=getattr(receiver_config, "description", None),
        recipe=recipe,
        recipe_sha256=(
            recipe_sha256_of(site_name, recipe) if site_name and recipe else None
        ),
        metadata=getattr(receiver_config, "metadata", None),
        receiver_hardware=_dump(getattr(receiver_config, "receiver_hardware", None)),
        antenna=_dump(getattr(receiver_config, "antenna", None)),
    )


def recipe_sha256_of(site_name: str, recipe: str) -> str | None:
    """sha256 of the naming recipe file ``recipe`` of ``site_name``.

    The file is found the way a run finds it (canvod-filemap's
    ``find_recipe``: a local recipe in the configuration directory, or a
    URL recipe in the cache, fetched if it is not there).

    Returns
    -------
    str | None
        The hexadecimal sha256, ``None`` if canvod-filemap is not installed
        or the recipe cannot be found (a run stops there before any store
        is written).
    """
    try:
        from canvod.filemap import (
            RecipeNotFoundError,
            RemoteRecipeError,
            find_recipe,
            recipe_sha256,
        )
    except ImportError:
        return None
    from canvod.config.loader import get_default_config_dir

    try:
        return recipe_sha256(find_recipe(get_default_config_dir(), site_name, recipe))
    except RecipeNotFoundError, RemoteRecipeError:
        return None


def _dump(settings: Any) -> dict[str, Any] | None:
    """A settings block as a plain dict, ``None`` when not set."""
    return None if settings is None else settings.model_dump()


def collect_instruments(
    site_config: Any, *, hardware: bool = True, site_name: str | None = None
) -> Instruments:
    """Build Instruments from SiteConfig receivers.

    ``hardware=False`` leaves out the receiver and antenna details: a VOD
    store reads them from the GNSS store's entries instead of copying them.
    """
    receivers = {
        name: collect_receiver(rcv, site_name)
        for name, rcv in site_config.receivers.items()
    }
    if not hardware:
        receivers = {
            name: r.model_copy(update={"receiver_hardware": None, "antenna": None})
            for name, r in receivers.items()
        }
    return Instruments(receivers=receivers)


def collect_vod_analyses(site_config: Any) -> dict[str, VodAnalysisInfo]:
    """The VOD analyses of a site, for its VOD store."""
    return {
        name: VodAnalysisInfo(
            canopy_receiver=analysis.canopy_receiver,
            reference_receiver=analysis.reference_receiver,
        )
        for name, analysis in (getattr(site_config, "vod_analyses", None) or {}).items()
    }


def collect_processing_provenance(
    store_type: str,
    source_format: str,
    facility: str | None = None,
) -> ProcessingProvenance:
    """Build ProcessingProvenance.

    ``facility`` is the institution that processed the data
    (``processing.metadata.institution``), never the computer.
    """
    now = datetime.now(UTC).isoformat()
    return ProcessingProvenance(
        software=collect_software_versions(),
        python=collect_python_info(),
        uv_version=collect_uv_version(),
        level="L1" if store_type == "gnss_store" else "L2",
        lineage=f"Raw {source_format} data ingested into Icechunk store",
        facility=facility,
        datetime=now,
    )


def collect_references(config: Any) -> References:
    """Build References from config if available."""
    from .schema import FundingRef, PublicationRef

    refs_config = None
    proc = getattr(config, "processing", None)
    if proc is not None:
        refs_config = getattr(proc, "references", None)

    if refs_config is None:
        return References()

    pubs = [
        PublicationRef(doi=p.doi, citation=getattr(p, "citation", None))
        for p in getattr(refs_config, "publications", [])
    ]
    funding = [
        FundingRef(
            funder=f.funder,
            funder_ror=getattr(f, "funder_ror", None),
            grant_number=getattr(f, "grant_number", None),
            award_title=getattr(f, "award_title", None),
        )
        for f in getattr(refs_config, "funding", [])
    ]
    return References(
        software_repository=getattr(refs_config, "software_repository", None),
        documentation=getattr(refs_config, "documentation", None),
        access_url=getattr(refs_config, "access_url", None),
        related_stores=getattr(refs_config, "related_stores", None) or [],
        publications=pubs,
        funding=funding,
    )


def _site_store_description(site_config: Any, meta_cfg: Any) -> str:
    """The site's store description, the deprecated shared one still counts."""
    return (
        getattr(site_config, "store_description", None)
        or getattr(meta_cfg, "store_description", None)
        or ""
    ).strip()


def missing_store_settings(site_name: str, site_config: Any, config: Any) -> list[str]:
    """Return the settings a new store needs but does not have.

    A store records these when it is created (DataCite, STAC): the site's
    store description, the publisher, the license and the naming authority.
    Each returned name carries an example value, as the store-creation error
    lists them. The deprecated shared ``processing.metadata.store_description``
    still counts as the site's store description.

    The naming authority is checked with ``check_naming_authority``: it is
    listed as missing when it is absent or not a reverse DNS name.
    """
    meta_cfg = config.processing.metadata
    required = {
        f"sites.{site_name}.store_description (e.g. 'GNSS-T observations "
        "below a beech canopy')": _site_store_description(site_config, meta_cfg),
        "processing.metadata.publisher (e.g. your institution)": getattr(
            meta_cfg, "publisher", None
        ),
        "processing.metadata.license (an SPDX identifier, e.g. 'CC-BY-4.0')": (
            getattr(meta_cfg, "license", None)
        ),
    }
    missing = [name for name, value in required.items() if not (value or "").strip()]
    try:
        check_naming_authority(getattr(meta_cfg, "naming_authority", None))
    except ValueError:
        missing.append(
            f"{NAMING_AUTHORITY_SETTING} is missing or not a reverse DNS "
            "name (e.g. 'org.middle-earth')"
        )
    return missing


def missing_store_settings_message(
    missing: list[str],
    *,
    stores: list[tuple[str, Path | str]] | None = None,
    store_label: str | None = None,
    store_path: Path | str | None = None,
) -> str:
    """Return the store-creation error message for *missing* settings.

    *missing* is the list from :func:`missing_store_settings`. *stores*
    names each of the new stores as ``(label, path)`` pairs and reads "the
    new <label> at <path>", joined with " and ", with a plural verb: the
    form for the one error that names several new stores. A single store is
    described by *store_path* ("The new <store_label> at <path>") or
    *store_label* ("A new <store_label>"), and with none of them the
    message reads "A store", as ``collect_metadata`` prints it.
    """
    if stores:
        subject = " and ".join(f"the new {label} at {path}" for label, path in stores)
        subject = subject[0].upper() + subject[1:]
        verb = "need these settings when they are"
    elif store_path is not None:
        subject = f"The new {store_label} at {store_path}"
        verb = "needs these settings when it is"
    elif store_label is not None:
        subject = f"A new {store_label}"
        verb = "needs these settings when it is"
    else:
        subject = "A store"
        verb = "needs these settings when it is"
    return (
        f"{subject} {verb} created; the metadata "
        f"standards (DataCite, STAC) require them: " + "; ".join(missing) + "."
    )


_ACRONYMS = {"gnss": "GNSS", "vod": "VOD"}


def _store_title(store_type: str) -> str:
    """``gnss_store`` -> ``GNSS Store``; other words title-cased."""
    return " ".join(_ACRONYMS.get(word, word.title()) for word in store_type.split("_"))


def collect_metadata(
    *,
    config: Any,
    site_name: str,
    site_config: Any,
    store_type: str,
    source_format: str,
    store_path: StoreLocation | Path | str | None = None,
    dask_workers: int | None = None,
    dask_threads_per_worker: int | None = None,
    gnss_repository: Mapping[str, Any] | None = None,
) -> StoreMetadata:
    """Collect all metadata sections into a StoreMetadata object.

    This is the main entry point for metadata collection. It gives a new
    store its id, UUID and catalog link.

    Raises
    ------
    ValueError
        If the site name gives no valid store id, the naming authority
        is missing or not a reverse DNS name, or the site's store
        description, the publisher or the license is missing.
    """
    meta_cfg = config.processing.metadata
    sid = store_id(
        site_name,
        store_type,
        None if store_path is None else store_folder_name(store_path),
    )
    missing = missing_store_settings(site_name, site_config, config)
    if missing:
        raise ValueError(missing_store_settings_message(missing))
    naming_authority = check_naming_authority(
        getattr(meta_cfg, "naming_authority", None)
    )
    description = _site_store_description(site_config, meta_cfg)
    now = datetime.now(UTC).isoformat()

    return StoreMetadata(
        identity=StoreIdentity(
            id=sid,
            uuid=new_uuid(),
            title=f"{site_name} {_store_title(store_type)}",
            description=description,
            store_type=store_type,
            source_format=source_format,
            keywords=["GNSS", "VOD", site_name, source_format],
            naming_authority=naming_authority,
            stac_link=stac_link(naming_authority, sid, store_type),
        ),
        creator=collect_creator(meta_cfg),
        publisher=collect_publisher(meta_cfg),
        temporal=TemporalExtent(created=now, updated=now),
        spatial=collect_spatial(site_config, site_name),
        instruments=collect_instruments(
            site_config, hardware=store_type != "vod_store", site_name=site_name
        ),
        processing=collect_processing_provenance(
            store_type, source_format, getattr(meta_cfg, "institution", None)
        ),
        environment=collect_environment(
            # The free disk of a local store's folder; S3 has none.
            None if store_path is None else store_location(store_path).local_path,
            dask_workers,
            dask_threads_per_worker,
            record_machine=records_machine(config),
        ),
        config=collect_config_snapshot(config),
        references=collect_references(config),
        vod_analyses=(
            collect_vod_analyses(site_config) if store_type == "vod_store" else {}
        ),
        content_settings=(
            new_content_settings(
                config,
                site_name,
                store_type=store_type,
                gnss_repository=gnss_repository,
            )
            if store_type in CONTENT_STORE_TYPES
            else None
        ),
    )
