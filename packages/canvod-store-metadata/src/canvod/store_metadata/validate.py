"""Validate metadata completeness against FAIR, DataCite 4.5, ACDD 1.3, STAC 1.1."""

from __future__ import annotations

import functools
from importlib import resources

from .schema import StoreMetadata


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


def validate_acdd(metadata: StoreMetadata) -> list[str]:
    """Check ACDD 1.3 highly recommended + recommended fields."""
    issues: list[str] = []

    hr_checks = [
        (metadata.identity, "title", "identity"),
        (metadata.identity, "id", "identity"),
        (metadata.identity, "conventions", "identity"),
        (metadata.creator, "name", "creator"),
        (metadata.creator, "email", "creator"),
        (metadata.creator, "institution", "creator"),
        (metadata.temporal, "created", "temporal"),
    ]
    for obj, field, label in hr_checks:
        issue = _check_field(obj, field, label)
        if issue:
            issues.append(f"[highly recommended] {issue}")

    rec_checks = [
        (metadata.identity, "keywords", "identity"),
        (metadata.identity, "description", "identity"),
        (metadata.spatial, "geospatial_lat", "spatial"),
        (metadata.spatial, "geospatial_lon", "spatial"),
    ]
    for obj, field, label in rec_checks:
        issue = _check_field(obj, field, label)
        if issue:
            issues.append(f"[recommended] {issue}")

    return issues


def validate_stac(metadata: StoreMetadata) -> list[str]:
    """Check STAC 1.1 Collection required fields."""
    issues: list[str] = []

    if not metadata.identity.id:
        issues.append("identity.id required for STAC Collection")
    if not metadata.identity.title:
        issues.append("identity.title required for STAC Collection")
    if not metadata.identity.description:
        issues.append("identity.description recommended for STAC Collection")
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
        issues.append(
            "[F1] identity.id is missing — data must have a unique identifier"
        )
    if not metadata.identity.persistent_identifier:
        issues.append(
            "[F1] identity.persistent_identifier is missing — "
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
            "fields are missing — rich metadata improves findability"
        )

    # F3 — Metadata clearly includes identifier of the data
    # Satisfied by design: identity.id is part of the metadata blob

    # F4 — Registered in searchable resource
    # We can't verify external registration, but we can check STAC readiness
    if metadata.spatial.bbox is None:
        issues.append(
            "[F4] spatial.bbox is missing — needed for STAC catalog registration"
        )

    # A1 — Retrievable by identifier using standardised protocol
    if not metadata.references.access_url:
        issues.append(
            "[A1] references.access_url is missing — "
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
            "[I2] identity.conventions is missing — "
            "declare metadata conventions (e.g. ACDD-1.3)"
        )

    # I3 — Qualified references to other metadata
    if not metadata.references.related_stores and not metadata.references.publications:
        issues.append(
            "[I3] No related_stores or publications — "
            "cross-references improve interoperability"
        )

    # R1.1 — Clear, accessible data usage license
    if not metadata.publisher.license:
        issues.append(
            "[R1.1] publisher.license is missing — "
            "specify an SPDX license (e.g. CC-BY-4.0) for reusability"
        )

    # R1.2 — Detailed provenance
    if not metadata.processing.software:
        issues.append(
            "[R1.2] processing.software is empty — "
            "record software versions for provenance"
        )
    if metadata.environment.uv_lock_hash is None:
        issues.append(
            "[R1.2] environment.uv_lock_hash is missing — "
            "store the lock file for environment reproducibility"
        )

    # R1.3 — Meet domain-relevant community standards
    # Checked by the other validators (DataCite, ACDD, STAC)

    return issues


def validate_all(metadata: StoreMetadata) -> dict[str, list[str]]:
    """Run all validators, return issues grouped by standard."""
    return {
        "fair": validate_fair(metadata),
        "datacite": validate_datacite(metadata),
        "acdd": validate_acdd(metadata),
        "stac": validate_stac(metadata),
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
