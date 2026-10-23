"""File registry (ingest ledger) helpers for Icechunk-backed stores.

This module manages the per-file tracking table stored at
``{group}/metadata/table`` inside an Icechunk store. Each row records
a single ingested file: its hash, temporal range, filename, path, etc.

**Not to be confused with** ``canvod.store_metadata`` (the separate package),
which manages store-level provenance: identity, creator, environment,
software versions, STAC/DataCite/ACDD compliance, etc.

Terminology
-----------
- **File registry** (this module): *which files* went into a store group.
- **Store metadata** (``canvod.store_metadata``): *who/what/when/how* about
  the store as a whole.
"""

from typing import Any

import structlog


class FileRegistryManager:
    """Manage file registry table CRUD, backups, and deduplication for groups.

    Parameters
    ----------
    logger : Any, optional
        Logger-like object to use. Defaults to the configured context logger.
    """

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger or structlog.get_logger(__name__)

    # TODO: Future refactor — extract metadata table methods from MyIcechunkStore.
