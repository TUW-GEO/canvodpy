"""canvod-store-metadata — Store-level provenance for Icechunk stores.

This package manages *store metadata*: identity, creator, environment,
software provenance, and standards compliance (DataCite/ACDD/STAC).

Not to be confused with the *file registry* in ``canvod.store``
(``{group}/metadata/table``), which tracks individual ingested files.
"""

from .collectors import collect_config_snapshot, collect_metadata
from .inventory import (
    scan_stores,
    scan_stores_as_stac,
    to_stac_collection,
    to_stac_collection_json,
    write_stac_catalog,
    write_stac_collection,
)
from .io import (
    apply_updates,
    commit_with_rebase,
    metadata_exists,
    read_metadata,
    update_metadata,
    write_metadata,
)
from .schema import StoreMetadata
from .show import extract_env, format_metadata, show_metadata
from .summary import summarize_store
from .validate import validate_all, validate_datacite, validate_fair

__all__ = [
    "StoreMetadata",
    "apply_updates",
    "collect_config_snapshot",
    "collect_metadata",
    "commit_with_rebase",
    "extract_env",
    "format_metadata",
    "metadata_exists",
    "read_metadata",
    "scan_stores",
    "scan_stores_as_stac",
    "show_metadata",
    "summarize_store",
    "to_stac_collection",
    "to_stac_collection_json",
    "update_metadata",
    "validate_all",
    "validate_datacite",
    "validate_fair",
    "write_metadata",
    "write_stac_catalog",
    "write_stac_collection",
]
