"""Validate store metadata against zarr conventions, ACDD 1.3, DataCite, STAC, FAIR.

A failure breaks a standard; a store created in the current form has none.
Recommendations (``[recommended]``) and FAIR advice are listed with
``recommended=True``. CF and the ACDD variable attributes are checked on a
netCDF export by IOOS compliance-checker in the tests.
"""

from __future__ import annotations

import functools
from importlib import resources
from pathlib import Path
from typing import Any

import zarr_cm

from .schema import RepositoryMetadata, StoreMetadata, check_rules
from .snapshot import root_copy

#: ACDD 1.3 global attributes (https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery_1-3).
ACDD_HIGHLY_RECOMMENDED = ("title", "summary", "keywords", "Conventions")
ACDD_RECOMMENDED = (
    "id",
    "naming_authority",
    "history",
    "source",
    "processing_level",
    "comment",
    "acknowledgement",
    "license",
    "standard_name_vocabulary",
    "date_created",
    "creator_name",
    "creator_email",
    "creator_url",
    "institution",
    "project",
    "publisher_name",
    "publisher_email",
    "publisher_url",
    "geospatial_bounds",
    "geospatial_bounds_crs",
    "geospatial_bounds_vertical_crs",
    "geospatial_lat_min",
    "geospatial_lat_max",
    "geospatial_lon_min",
    "geospatial_lon_max",
    "geospatial_vertical_min",
    "geospatial_vertical_max",
    "geospatial_vertical_positive",
    "time_coverage_start",
    "time_coverage_end",
    "time_coverage_duration",
    "time_coverage_resolution",
)

#: The ACDD 1.3 values of a variable's ``coverage_content_type``.
COVERAGE_CONTENT_TYPES = (
    "image",
    "thematicClassification",
    "physicalMeasurement",
    "auxiliaryInformation",
    "qualityInformation",
    "referenceInformation",
    "modelResult",
    "coordinate",
)

# Where a root attribute comes from, for the message.
_ACDD_SOURCE = {
    "title": "identity.title",
    "summary": "identity.description",
    "keywords": "identity.keywords",
    "creator_url": "creator.website",
    "publisher_name": "publisher.name",
    "publisher_url": "publisher.url",
    "geospatial_lat_min": "spatial.geospatial_lat",
    "geospatial_lat_max": "spatial.geospatial_lat",
    "geospatial_lon_min": "spatial.geospatial_lon",
    "geospatial_lon_max": "spatial.geospatial_lon",
    "geospatial_vertical_min": "spatial.geospatial_alt_m",
    "geospatial_vertical_max": "spatial.geospatial_alt_m",
    "geospatial_vertical_positive": "spatial.geospatial_alt_m",
}


def root_attributes(metadata: StoreMetadata) -> dict[str, Any]:
    """The root group attributes a commit writes for ``metadata``.

    Raises
    ------
    ValueError
        If ``metadata`` is in the form from before the migration (no UUID,
        naming authority or STAC link).
    """
    identity = metadata.identity
    missing = [
        name
        for name in ("uuid", "naming_authority", "stac_link")
        if not getattr(identity, name)
    ]
    if missing:
        msg = (
            f"The metadata has no identity.{', identity.'.join(missing)}: it is "
            "from before the migration. Migrate the store: canvodpy store "
            "migrate-metadata."
        )
        raise ValueError(msg)
    repository = RepositoryMetadata.from_store_metadata(
        metadata, existing=True
    ).model_dump(mode="json")
    temporal = metadata.temporal.model_dump(
        include={
            "updated",
            "time_coverage_start",
            "time_coverage_end",
            "time_coverage_duration",
            "time_coverage_resolution",
        }
    )
    summary = {"temporal": temporal, "spatial": {}, "receivers": {}, "summaries": {}}
    return root_copy(repository, summary)


def _check_field(obj: object, field: str, label: str) -> str | None:
    """Return an issue string if field is None or empty."""
    val = getattr(obj, field, None)
    if val is None or val == "" or val == []:
        return f"{label}.{field} is missing or empty"
    return None


def validate_datacite(metadata: StoreMetadata) -> list[str]:
    """Check DataCite 4.5 mandatory fields."""
    issues: list[str] = []

    checks = [
        (metadata.identity, "id", "identity"),
        (metadata.identity, "title", "identity"),
        (metadata.creator, "name", "creator"),
        (metadata.creator, "institution", "creator"),
        (metadata.temporal, "created", "temporal"),
        (metadata.identity, "store_type", "identity"),
    ]
    for obj, field, label in checks:
        issue = _check_field(obj, field, label)
        if issue:
            issues.append(issue)

    if metadata.publisher.name is None:
        issues.append("publisher.name is missing (DataCite mandatory)")

    return issues


def validate_acdd(metadata: StoreMetadata, *, recommended: bool = True) -> list[str]:
    """Check the root attributes against the ACDD 1.3 global attributes.

    A missing highly recommended attribute is a failure; a missing
    recommended one is listed with ``recommended=True``.
    """
    try:
        attrs = root_attributes(metadata)
    except ValueError as exc:
        return [str(exc)]
    issues = [
        _acdd_issue(name, "highly recommended")
        for name in ACDD_HIGHLY_RECOMMENDED
        if attrs.get(name) in (None, "")
    ]
    if recommended:
        issues += [
            f"[recommended] {_acdd_issue(name, 'recommended')}"
            for name in ACDD_RECOMMENDED
            if attrs.get(name) in (None, "")
        ]
    return issues


def _acdd_issue(name: str, level: str) -> str:
    source = _ACDD_SOURCE.get(name)
    where = f" (from {source})" if source else ""
    return f"ACDD 1.3 {level} attribute `{name}` is missing{where}"


def validate_zarr_conventions(metadata: StoreMetadata) -> list[str]:
    """Check the zarr conventions in the root attributes with zarr-cm."""
    try:
        attrs = root_attributes(metadata)
    except ValueError as exc:
        return [str(exc)]
    try:
        zarr_cm.validate_all(attrs)
    except Exception as exc:  # zarr-cm raises per convention, with its reason
        return [f"zarr conventions: {exc}"]
    return []


def validate_stac(metadata: StoreMetadata, *, recommended: bool = True) -> list[str]:
    """Check STAC 1.1 Collection required fields."""
    issues: list[str] = []

    if not metadata.identity.id:
        issues.append("identity.id required for STAC Collection")
    if not metadata.identity.title:
        issues.append("identity.title required for STAC Collection")
    if recommended and not metadata.identity.description:
        issues.append("[recommended] identity.description for STAC Collection")
    if metadata.spatial.bbox is None:
        issues.append("spatial.bbox required for STAC spatial extent")
    if metadata.spatial.extent_temporal_interval is None:
        issues.append(
            "spatial.extent_temporal_interval required for STAC temporal extent"
        )
    if metadata.publisher.license is None:
        issues.append("publisher.license required for STAC Collection")

    return issues


def validate_fair(metadata: StoreMetadata) -> list[str]:
    """Check FAIR data principles compliance.

    Checks each sub-principle (F1–F4, A1–A2, I1–I3, R1.1–R1.3)
    and returns actionable issues for anything missing.
    """
    issues: list[str] = []

    # F1 — Globally unique, persistent identifier
    if not metadata.identity.id:
        issues.append("[F1] identity.id is missing: data must have a unique identifier")
    if not metadata.identity.persistent_identifier:
        issues.append(
            "[F1] identity.persistent_identifier is missing: "
            "assign a DOI or other persistent identifier for long-term findability"
        )

    # F2 — Rich metadata
    rich_fields = [
        (metadata.identity, "title", "identity"),
        (metadata.identity, "description", "identity"),
        (metadata.identity, "keywords", "identity"),
        (metadata.creator, "name", "creator"),
        (metadata.creator, "institution", "creator"),
        (metadata.temporal, "collected_start", "temporal"),
        (metadata.spatial, "geospatial_lat", "spatial"),
    ]
    missing_rich = sum(
        1 for obj, field, _ in rich_fields if _check_field(obj, field, "") is not None
    )
    if missing_rich > 2:
        issues.append(
            f"[F2] {missing_rich} of {len(rich_fields)} recommended descriptive "
            "fields are missing: rich metadata improves findability"
        )

    # F3 — Metadata clearly includes identifier of the data
    # Satisfied by design: identity.id is part of the metadata blob

    # F4 — Registered in searchable resource
    # We can't verify external registration, but we can check STAC readiness
    if metadata.spatial.bbox is None:
        issues.append(
            "[F4] spatial.bbox is missing: needed for STAC catalog registration"
        )

    # A1 — Retrievable by identifier using standardised protocol
    if not metadata.references.access_url:
        issues.append(
            "[A1] references.access_url is missing: "
            "provide a URL (S3, HTTP, or local) where data can be accessed"
        )

    # A2 — Metadata accessible even when data is no longer available
    # This is an architectural concern; we note it as advice
    # (metadata is coupled to data in root attrs)

    # I1 — Formal, shared knowledge representation
    # Satisfied: JSON in Zarr root attrs with Pydantic schema

    # I2 — Use FAIR-compliant vocabularies
    if not metadata.identity.conventions:
        issues.append(
            "[I2] identity.conventions is missing: "
            "declare metadata conventions (e.g. ACDD-1.3)"
        )

    # I3 — Qualified references to other metadata
    if not metadata.references.related_stores and not metadata.references.publications:
        issues.append(
            "[I3] No related_stores or publications: "
            "cross-references improve interoperability"
        )

    # R1.1 — Clear, accessible data usage license
    if not metadata.publisher.license:
        issues.append(
            "[R1.1] publisher.license is missing: "
            "specify an SPDX license (e.g. CC-BY-4.0) for reusability"
        )

    # R1.2 — Detailed provenance
    if not metadata.processing.software:
        issues.append(
            "[R1.2] processing.software is empty: "
            "record software versions for provenance"
        )
    if metadata.environment.uv_lock_hash is None:
        issues.append(
            "[R1.2] environment.uv_lock_hash is missing: "
            "store the lock file for environment reproducibility"
        )

    # R1.3 — Meet domain-relevant community standards
    # Checked by the other validators (DataCite, ACDD, STAC)

    return issues


def _catalog_link_warnings(metadata: StoreMetadata, store_path: Path) -> list[str]:
    """A warning when the store's catalog link has no item file yet.

    The link is written when the store is created and dangles until the
    first catalog write, so a dangling link is no failure (ADR 0015).
    """
    link = metadata.identity.stac_link
    if not link or (store_path / link).exists():
        return []
    return [
        f"[warning] identity.stac_link points to {link}, which has no item "
        "file yet: write the catalog with canvodpy stac write"
    ]


def validate_all(
    metadata: StoreMetadata,
    *,
    recommended: bool = True,
    store_path: Path | None = None,
) -> dict[str, list[str]]:
    """Run all validators, return issues grouped by standard.

    ``rules`` lists the fields that break a rule of their standard (e.g. a
    license outside SPDX), which a store read from disk may hold.

    Parameters
    ----------
    recommended
        Also list ACDD recommendations, FAIR advice and warnings. With
        ``False`` only failures are listed: a store created in the current
        form has none.
    store_path
        The local store ``metadata`` was read from. Given, the STAC check
        also warns when the store's catalog link has no item file yet.
    """
    stac = validate_stac(metadata, recommended=recommended)
    if recommended and store_path is not None:
        stac += _catalog_link_warnings(metadata, store_path)
    return {
        "rules": [str(rule_break) for rule_break in check_rules(metadata)],
        "zarr_conventions": validate_zarr_conventions(metadata),
        "acdd": validate_acdd(metadata, recommended=recommended),
        "datacite": validate_datacite(metadata),
        "stac": stac,
        "fair": validate_fair(metadata) if recommended else [],
    }


@functools.cache
def cf_standard_names() -> frozenset[str]:
    """The names and aliases of the CF standard name table vendored here."""
    text = (
        resources.files("canvod.store_metadata")
        .joinpath("standards/cf_standard_names_v95.txt")
        .read_text()
    )
    return frozenset(
        line for line in text.splitlines() if line and not line.startswith("#")
    )
