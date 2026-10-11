"""Pydantic models for store metadata (11 sections, ~90 fields).

Field names follow DataCite 4.5, ACDD 1.3, and STAC 1.1; ``validate.py``
checks the fields against them and the FAIR principles.
"""

from __future__ import annotations

import warnings
from typing import Any

from canvod.utils.tools import deprecated
from pydantic import BaseModel, Field


# §1 — Identity & Discovery
class StoreIdentity(BaseModel):
    id: str = Field(..., description="Store id: {site slug}-{gnss|vod}")
    uuid: str | None = Field(
        None, description="Random UUID generated when the store is created"
    )
    title: str = Field(..., description="Human-readable store title")
    description: str | None = Field(None, description="Store description")
    store_type: str = Field(..., description="Store type: gnss_store, vod_store")
    source_format: str = Field(
        ..., description="Data source format: rinex3, rinex2, sbf"
    )
    keywords: list[str] = Field(default_factory=list, description="Discovery keywords")
    conventions: str = Field("ACDD-1.3", description="Metadata conventions")
    naming_authority: str | None = Field(
        None, description="Naming authority, reverse DNS (e.g. at.ac.tuwien)"
    )
    stac_link: str | None = Field(
        None, description="Link to the store's item in the catalog, relative"
    )
    persistent_identifier: str | None = Field(
        None, description="DOI or other persistent identifier (FAIR F1)"
    )
    standard_name_vocabulary: str | None = Field(None)


# §2 — Creator
class Creator(BaseModel):
    name: str = Field(..., description="Creator name")
    email: str = Field(..., description="Creator email")
    orcid: str | None = Field(None, description="ORCID identifier")
    type: str = Field("Personal", description="Creator type: Personal, Organizational")
    institution: str = Field(..., description="Institution name")
    institution_ror: str | None = Field(None, description="ROR identifier")
    department: str | None = Field(None)
    research_group: str | None = Field(None)
    website: str | None = Field(None)


# §3 — Publisher & Rights
class Publisher(BaseModel):
    name: str | None = Field(None, description="Publisher name")
    type: str = Field("Institutional", description="Publisher type")
    url: str | None = Field(None, description="Publisher URL")
    license: str | None = Field(None, description="SPDX license identifier")
    license_uri: str | None = Field(None, description="License URI")


# §4 — Temporal Extent
class TemporalExtent(BaseModel):
    created: str = Field(..., description="Store creation timestamp (ISO 8601)")
    updated: str = Field(..., description="Last update timestamp (ISO 8601)")
    collected_start: str | None = Field(None, description="Earliest data epoch")
    collected_end: str | None = Field(None, description="Latest data epoch")
    time_coverage_start: str | None = Field(None)
    time_coverage_end: str | None = Field(None)
    time_coverage_duration: str | None = Field(None, description="ISO 8601 duration")
    time_coverage_resolution: str | None = Field(None, description="ISO 8601 duration")


# §5 — Spatial Extent & Site
class SiteInfo(BaseModel):
    name: str = Field(..., description="Site name")
    description: str | None = Field(None)
    country: str | None = Field(None)


class SpatialExtent(BaseModel):
    site: SiteInfo
    geospatial_lat: float | None = Field(None, description="WGS84 latitude")
    geospatial_lon: float | None = Field(None, description="WGS84 longitude")
    geospatial_alt_m: float | None = Field(None, description="Altitude in meters")
    geospatial_lat_min: float | None = Field(None)
    geospatial_lat_max: float | None = Field(None)
    geospatial_lon_min: float | None = Field(None)
    geospatial_lon_max: float | None = Field(None)
    geospatial_vertical_crs: str = Field("EPSG:4979", description="Vertical CRS")
    bbox: list[float] | None = Field(None, description="STAC bbox [W, S, E, N]")
    extent_temporal_interval: list[list[str | None]] | None = Field(
        None, description="STAC temporal interval"
    )


# §6 — Receivers & Instruments
class ReceiverInfo(BaseModel):
    type: str = Field(..., description="reference or canopy")
    directory: str = Field(..., description="Data subdirectory")
    reader_format: str = Field("auto", description="Reader format")
    description: str | None = Field(None)
    recipe: str | None = Field(None, description="Naming recipe name")
    epochs: int | None = Field(None, description="Number of epochs ingested")
    sids: int | None = Field(None, description="Number of SIDs observed")
    variables: list[str] | None = Field(None, description="Variable names")
    temporal_range: list[str] | None = Field(None, description="[start, end] ISO")
    position_ecef_m: list[float] | None = Field(
        None,
        description=("Median of the stored files' header positions [X, Y, Z], ECEF, m"),
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Freeform receiver metadata"
    )


class VodAnalysisInfo(BaseModel):
    """One VOD analysis a VOD store holds: the receivers it pairs."""

    canopy_receiver: str
    reference_receiver: str


class Instruments(BaseModel):
    platform: str = Field("ground-based GNSS", description="Platform type")
    instruments: list[str] = Field(
        default_factory=lambda: ["GNSS receiver"],
        description="Instrument list",
    )
    receivers: dict[str, ReceiverInfo] = Field(
        default_factory=dict, description="Per-receiver info"
    )


# §7 — Software Provenance
class ProcessingProvenance(BaseModel):
    software: dict[str, str] = Field(
        default_factory=dict, description="Package versions"
    )
    python: str | None = Field(None, description="Python version")
    uv_version: str | None = Field(None, description="uv version")
    level: str = Field("L1", description="Processing level")
    lineage: str | None = Field(None, description="Processing lineage description")
    facility: str | None = Field(None, description="Processing facility")
    datetime: str | None = Field(None, description="Processing timestamp")


# §8 — Environment
class Environment(BaseModel):
    hostname: str | None = Field(None)
    os: str | None = Field(None, description="Platform string")
    arch: str | None = Field(None, description="Machine architecture")
    cpu_count: int | None = Field(None)
    memory_gb: float | None = Field(None, description="Total system RAM in GB")
    disk_free_gb: float | None = Field(None, description="Free disk at store path")
    dask_workers: int | None = Field(None)
    dask_threads_per_worker: int | None = Field(None)
    uv_lock_hash: str | None = Field(
        None, description="SHA256 of uv.lock for quick comparison"
    )
    pyproject_toml_text: str | None = Field(
        None,
        description="Raw pyproject.toml content for env reproduction",
    )
    uv_lock_text: str | None = Field(
        None,
        description="Raw uv.lock content for env reproduction",
    )


# §9 — Config Snapshot
class ConfigSnapshot(BaseModel):
    processing: dict[str, Any] | None = Field(None)
    preprocessing: dict[str, Any] | None = Field(None)
    aux_data: dict[str, Any] | None = Field(None)
    compression: dict[str, Any] | None = Field(None)
    icechunk: dict[str, Any] | None = Field(None)
    sids: dict[str, Any] | None = Field(None)
    config_hash: str | None = Field(None, description="SHA256 of serialized config")


# §10 — References
class PublicationRef(BaseModel):
    doi: str
    citation: str | None = None


class FundingRef(BaseModel):
    funder: str
    funder_ror: str | None = None
    grant_number: str | None = None
    award_title: str | None = None


class References(BaseModel):
    software_repository: str | None = Field(None)
    documentation: str | None = Field(None)
    access_url: str | None = Field(
        None, description="URL where data is accessible (FAIR A1)"
    )
    related_stores: list[str] = Field(default_factory=list)
    publications: list[PublicationRef] = Field(default_factory=list)
    funding: list[FundingRef] = Field(default_factory=list)


# §11 — Summaries
class Summaries(BaseModel):
    total_epochs: int | None = Field(None)
    total_sids: int | None = Field(None)
    constellations: list[str] | None = Field(None)
    variables: list[str] | None = Field(None)
    temporal_resolution_s: float | None = Field(None)
    file_count: int | None = Field(None)
    store_size_mb: float | None = Field(None)
    history: list[str] = Field(
        default_factory=list,
        description="Processing log entries (stores before ADR 0014 only)",
    )

    def __getattribute__(self, name: str) -> Any:
        if name == "history":
            # FutureWarning, which Python shows by default; pydantic's own
            # field deprecation warns with DeprecationWarning only.
            warnings.warn(
                "summaries.history is left over from development and will be "
                "removed with the next major version. The history of a store is "
                "its commit log: show_metadata lists it.",
                FutureWarning,
                stacklevel=2,
            )
        return super().__getattribute__(name)


# ── Root model ──────────────────────────────────────────────────────────────

_METADATA_VERSION = "1.0.0"
_METADATA_KEY = "canvod_metadata"
#: Version of the metadata form of ADR 0014 (repository metadata, root
#: copy, snapshot summary, commit metadata).
FORM_VERSION = "2.0.0"


class Amendment(BaseModel):
    """One recorded change of an amendable field."""

    field: str
    old: Any = None
    new: Any = None
    reason: str
    who: str
    when: str


class StoreMetadata(BaseModel):
    """Root metadata model composing all 11 sections."""

    metadata_version: str = Field(_METADATA_VERSION, description="Schema version")
    identity: StoreIdentity
    creator: Creator
    publisher: Publisher = Field(default_factory=Publisher)
    temporal: TemporalExtent
    spatial: SpatialExtent
    instruments: Instruments = Field(default_factory=Instruments)
    processing: ProcessingProvenance = Field(default_factory=ProcessingProvenance)
    environment: Environment = Field(default_factory=Environment)
    config: ConfigSnapshot = Field(default_factory=ConfigSnapshot)
    references: References = Field(default_factory=References)
    summaries: Summaries = Field(default_factory=Summaries)
    vod_analyses: dict[str, VodAnalysisInfo] = Field(
        default_factory=dict, description="VOD analyses of a VOD store"
    )
    amendments: list[Amendment] = Field(default_factory=list)
    written_before_migration: bool = Field(
        False,
        description=(
            "Read from a snapshot written before the store kept repository "
            "metadata (ADR 0014)"
        ),
    )

    def to_root_attrs(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for Zarr root attrs."""
        return {_METADATA_KEY: self.model_dump(mode="json")}

    @classmethod
    def _from_old_root_attrs(cls, attrs: dict[str, Any]) -> StoreMetadata:
        """Read a snapshot written before ADR 0014 (one ``canvod_metadata``)."""
        data = {**attrs[_METADATA_KEY], "written_before_migration": True}
        return cls.model_validate(data)

    @classmethod
    @deprecated(
        "StoreMetadata.from_root_attrs() is left over from development and will "
        "be removed with the next major version. Use read_metadata(), which "
        "reads every snapshot, also those written before the migration."
    )
    def from_root_attrs(cls, attrs: dict[str, Any]) -> StoreMetadata:
        """Reconstruct from Zarr root attrs dict (the form before ADR 0014)."""
        return cls._from_old_root_attrs(attrs)


# ── Repository metadata (ADR 0014) ──────────────────────────────────────────
#
# The part of the metadata that describes the store as a whole, kept in
# Icechunk's repository metadata. Field names match ``StoreMetadata``, so
# ``RepositoryMetadata.from_store_metadata`` drops the per-snapshot and
# per-commit fields. The id, UUID, naming authority and catalog link are
# required here: a store is never created without them.


class RepositoryIdentity(BaseModel):
    id: str
    uuid: str
    store_type: str
    source_format: str
    naming_authority: str
    stac_link: str
    title: str
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    persistent_identifier: str | None = None


class RepositoryTemporal(BaseModel):
    created: str


class RepositorySpatial(BaseModel):
    site: SiteInfo
    geospatial_lat: float | None = None
    geospatial_lon: float | None = None
    geospatial_alt_m: float | None = None
    geospatial_vertical_crs: str = "EPSG:4979"


class RepositoryReceiver(BaseModel):
    type: str
    directory: str
    reader_format: str = "auto"
    description: str | None = None
    recipe: str | None = None
    metadata: dict[str, Any] | None = None


class RepositoryInstruments(BaseModel):
    platform: str = "ground-based GNSS"
    instruments: list[str] = Field(default_factory=lambda: ["GNSS receiver"])
    receivers: dict[str, RepositoryReceiver] = Field(default_factory=dict)


class RepositoryMetadata(BaseModel):
    """What describes a store as a whole: fixed and amendable fields."""

    metadata_version: str = Field(FORM_VERSION)
    identity: RepositoryIdentity
    creator: Creator
    publisher: Publisher = Field(default_factory=Publisher)
    temporal: RepositoryTemporal
    spatial: RepositorySpatial
    instruments: RepositoryInstruments = Field(default_factory=RepositoryInstruments)
    references: References = Field(default_factory=References)
    vod_analyses: dict[str, VodAnalysisInfo] = Field(default_factory=dict)
    amendments: list[Amendment] = Field(default_factory=list)

    @classmethod
    def from_store_metadata(cls, metadata: StoreMetadata) -> RepositoryMetadata:
        """Take the repository part of ``metadata``, in the current form."""
        data = metadata.model_dump(mode="json")
        data["metadata_version"] = FORM_VERSION
        return cls.model_validate(data)
