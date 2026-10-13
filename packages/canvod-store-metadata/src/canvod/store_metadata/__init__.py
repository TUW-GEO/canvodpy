"""canvod-store-metadata: store-level provenance for Icechunk stores.

This package manages *store metadata*: identity, creator, environment,
software provenance, and standards compliance (DataCite/ACDD/STAC).

Not to be confused with the *file registry* in ``canvod.store``
(``{group}/metadata/table``), which tracks individual ingested files.
"""

from .amend import amend_metadata
from .catalog import build_catalog, create_release, store_item, write_catalog
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
    COMMIT_LOCK_NAME,
    MIGRATE_COMMAND,
    amendments_since,
    apply_updates,
    check_receivers,
    check_vod_analyses,
    commit_lock,
    commit_with_rebase,
    ensure_metadata,
    ensure_store_metadata,
    metadata_exists,
    read_metadata,
    read_repository_metadata,
    rewrite_manifests,
    update_metadata,
    write_metadata,
)
from .location import (
    LocalStoreLocation,
    S3StoreLocation,
    StoreLocation,
    open_repository,
    read_store_uuid,
    repository_config,
    store_exists,
    store_location,
)
from .migration import migrate_metadata
from .schema import MetadataRuleWarning, StoreMetadata
from .show import extract_env, format_metadata, show_metadata
from .snapshot import RESERVED_GROUP
from .summary import summarize_store
from .validate import validate_all, validate_datacite, validate_fair

__all__ = [
    "COMMIT_LOCK_NAME",
    "LocalStoreLocation",
    "MIGRATE_COMMAND",
    "MetadataRuleWarning",
    "RESERVED_GROUP",
    "S3StoreLocation",
    "StoreLocation",
    "StoreMetadata",
    "amend_metadata",
    "amendments_since",
    "build_catalog",
    "apply_updates",
    "check_receivers",
    "check_vod_analyses",
    "collect_config_snapshot",
    "collect_metadata",
    "commit_lock",
    "commit_with_rebase",
    "create_release",
    "ensure_metadata",
    "ensure_store_metadata",
    "extract_env",
    "format_metadata",
    "metadata_exists",
    "migrate_metadata",
    "open_repository",
    "store_exists",
    "read_metadata",
    "read_repository_metadata",
    "read_store_uuid",
    "repository_config",
    "rewrite_manifests",
    "scan_stores",
    "scan_stores_as_stac",
    "show_metadata",
    "store_item",
    "store_location",
    "summarize_store",
    "to_stac_collection",
    "to_stac_collection_json",
    "update_metadata",
    "validate_all",
    "validate_datacite",
    "validate_fair",
    "write_catalog",
    "write_metadata",
    "write_stac_catalog",
    "write_stac_collection",
]
