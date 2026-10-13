"""Icechunk/Zarr store path and strategy configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from canvod.utils.tools import deprecated

from .base import _StrictModel


class MaintenanceConfig(_StrictModel):
    """Scheduled Icechunk maintenance (expiration + garbage collection).

    Settings for `canvodpy store maintain-due`, which expires old
    snapshots, collects garbage and compacts manifests when they are due.
    It asks nothing, so a scheduled job (for example cron) can run it.
    `canvodpy store maintain` does the same work but asks for confirmation
    before it deletes anything, so it can't run unattended.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    enabled: bool = Field(
        False,
        description=(
            "Master switch for `canvodpy store maintain-due`. Off by "
            "default. Before you turn it on, run garbage_collect(dry_run="
            "True) against your store and check what it would delete."
        ),
    )
    dry_run_until_confirmed: bool = Field(
        True,
        description=(
            "Force every `maintain-due` invocation to dry-run only, "
            "regardless of due-ness, until explicitly set False per "
            "deployment. The interactive CLI's `maintain --execute` "
            "requires a typer.confirm a cron job can't answer; this is "
            "the config-level equivalent gate for the unattended path."
        ),
    )
    retention_days: int = Field(
        90,
        ge=7,
        description=(
            "Snapshot retention window passed to expire_old_snapshots()/ "
            "garbage_collect() by the scheduled job (weeks-to-months, a "
            "generous margin past any realistic write-session duration). "
            "Mirrors MyIcechunkStore.maintenance()'s own default; kept "
            "separate so a human running `maintain --expire-days` "
            "interactively is unaffected by this value."
        ),
    )
    expire_interval_days: int = Field(
        45,
        ge=1,
        description=(
            "How often (wall-clock days since the most recent "
            "ExpirationRan entry in the store's own ops log) the "
            "scheduled job re-runs expiration. Skill-doc guidance: every "
            "1-2 months."
        ),
    )
    gc_delay_days: int = Field(
        20,
        ge=1,
        description=(
            "Extra days to wait after the most recent expiration before "
            "running garbage_collect(), so physical deletion always lags "
            "the (reversible-in-effect) soft-delete by a safety buffer. "
            "Skill-doc guidance: GC every 15-30 days, offset from expire."
        ),
    )
    manifests_enabled: bool = Field(
        False,
        description=(
            "Enable scheduled manifest compaction (rewrite_manifests()) "
            "under maintain-due, independent of `enabled`'s expire/GC "
            "gate -- rewrite_manifests() is an ordinary commit (no "
            "history rewrite or physical deletion), a different risk "
            "profile than expire/GC, safe to validate and enable "
            "separately. Off by default until confirmed against the "
            "real store (see maintain-due's dry-run path)."
        ),
    )
    manifest_count_threshold: int = Field(
        3000,
        ge=1,
        description=(
            "Trigger rewrite_manifests() when the store's on-disk "
            "manifest count (MyIcechunkStore.dir_entry_counts()) reaches "
            "this. A direct fragmentation measurement, not a time "
            "interval -- rewrite_manifests() has no distinguishing "
            "ops-log entry (it logs as an ordinary NewCommit, "
            "indistinguishable from any data-ingest commit), so "
            "'how fragmented is the store right now' is the available "
            "and more meaningful signal here, unlike expire/GC's "
            "ExpirationRan/GCRan-based due-check."
        ),
    )


class StorageConfig(_StrictModel):
    """Storage strategy configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    stores_root_dir: Path = Field(
        ...,
        description=(
            "Directory where canvodpy writes all processed results "
            "(Icechunk/Zarr stores). Must exist and be writable. "
            "Wizard prompt: 'Where should processed results be stored?'"
        ),
    )
    gnss_store_name: str = Field(
        "rinex",
        description="Name of the GNSS observation Icechunk store directory",
    )
    vod_store_name: str = Field(
        "vod",
        description="Name of the VOD Icechunk store directory",
    )
    statistics_store_name: str = Field(
        "statistics",
        description="Name of the statistics Zarr store directory",
    )
    rollup_store_name: str = Field(
        "rollup",
        description="Name of the hemigrid rollup Icechunk store directory",
    )
    aux_data_dir: Path | None = Field(
        None,
        description=(
            "Directory for downloaded auxiliary files (SP3, CLK) and "
            "transient Zarr caches. Raw files persist; caches are rebuilt "
            "each run. Defaults to system temp directory if not set."
        ),
    )
    shared_aux_cache_dir: Path | None = Field(
        None,
        description=(
            "Network-wide, fingerprint-keyed aux (SP3/CLK Hermite) cache "
            "root. None (default) = disabled, falls "
            "back to per-site aux_data_dir/aux_{date}.zarr, rebuilt every "
            "run. Ephemeris products are satellite-based, not site-based, "
            "so pointing multiple sites at the same path lets them share "
            "one cache entry per (agency, product, date) instead of each "
            "rebuilding it independently."
        ),
    )
    gnss_store_strategy: Literal["skip", "overwrite", "unsafe_append"] = Field(
        "skip",
        description=(
            "How to handle a file whose hash/time-range already exists in "
            "the GNSS store (new files are always written regardless of "
            "this setting). 'skip' (default, recommended): do nothing -- "
            "the normal case, since a re-run over already-ingested files "
            "should be a no-op, not a rewrite. 'overwrite': delete the old "
            "epochs for that file's range first, then write the new "
            "version -- for correcting already-ingested data after a "
            "pipeline bug fix (reader logic, ephemeris source, etc.), not "
            "because the raw GNSS file itself changed. 'unsafe_append': "
            "write the file's data again on top of what's already there, "
            "with NO epoch-level uniqueness check. This produces duplicate "
            "epoch coordinate values in the Zarr array, and xarray does not "
            "enforce unique index values. The two built-in pipeline read "
            "paths already guard against it -- GnssResearchSite."
            "read_receiver_data() routes through read_group_deduplicated() "
            "whenever this strategy is set (manager.py), and VodComputer."
            "compute_bulk() unconditionally deduplicates every read via "
            "_dedup_sort() regardless of strategy -- but MyIcechunkStore."
            "read_group() itself (the low-level API used directly by "
            "custom scripts and notebooks) has no such guard: `.sel()` on a "
            "duplicated label can raise or return multiple matches, and "
            "aligning two duplicated datasets (e.g. canopy vs. reference) "
            "produces a cartesian product at the duplicated epochs. The "
            "duplication is also physical, not just a read-time artifact -- "
            "Icechunk stores the extra chunks permanently; dedup-on-read "
            "does not undo that. Avoid 'unsafe_append' unless you have a "
            "specific reason, and be aware any read path outside the two "
            "guarded ones above is unprotected."
        ),
    )
    vod_store_strategy: Literal["skip", "overwrite", "unsafe_append"] | None = Field(
        None,
        description=(
            "Deprecated, has no effect. VOD writes always skip a result "
            "whose source files or epoch range are already in the VOD "
            "store. To recompute VOD for days already stored, write to a "
            "new VOD store (set another vod_store_name)."
        ),
    )
    keeper_tags: bool = Field(
        False,
        description=(
            "Tag every (receiver, date) Icechunk commit as "
            "keep/{receiver}/{yyyydoy} so a future retention job can expire "
            "everything else. Off by default: the cost of create_tag() "
            "on large stores hasn't been measured yet."
        ),
    )
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)

    @model_validator(mode="before")
    @classmethod
    def _warn_vod_store_strategy(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("vod_store_strategy") is not None:
            import warnings

            warnings.warn(
                "The storage setting 'vod_store_strategy' is left over from development and will be removed with the next major version. "
                "It has no effect: VOD writes always skip results already in the store. "
                "Remove it from your settings; to recompute VOD, set another 'vod_store_name'.",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @field_validator("stores_root_dir", mode="before")
    @classmethod
    def validate_stores_dir(cls, v: object) -> object:
        """Expand ~ and reject placeholder values and URLs in stores_root_dir.

        Checked before the value becomes a ``Path``, which would turn
        ``s3://bucket/prefix`` into the local path ``s3:/bucket/prefix``.
        """
        if isinstance(v, str):
            if "://" in v:
                raise ValueError(
                    f"stores_root_dir is set to {v!r}: processing writes "
                    "stores to a local directory only; writing stores to S3 "
                    "comes later. Set a local directory in canvod-settings.yaml."
                )
            if v.strip() in {"/path/to/stores", "/path/to/your/stores"}:
                raise ValueError(
                    f"stores_root_dir is set to placeholder {v!r}: "
                    "set a real directory path in canvod-settings.yaml"
                )
            return Path(v).expanduser()
        return v

    def get_gnss_store_path(self, site_name: str) -> Path:
        """Get the GNSS store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's GNSS store.
        """
        return self.stores_root_dir / site_name / self.gnss_store_name

    @deprecated(
        "StorageConfig.get_rinex_store_path() is left over from development and will be removed with the next major version. "
        "Use StorageConfig.get_gnss_store_path() instead."
    )
    def get_rinex_store_path(self, site_name: str) -> Path:
        """Deprecated: use get_gnss_store_path instead."""
        return self.get_gnss_store_path(site_name)

    def get_vod_store_path(self, site_name: str) -> Path:
        """Get the VOD store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's VOD store.
        """
        return self.stores_root_dir / site_name / self.vod_store_name

    def get_statistics_store_path(self, site_name: str) -> Path:
        """Get the statistics store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's statistics store.
        """
        return self.stores_root_dir / site_name / self.statistics_store_name

    def get_rollup_store_path(self, site_name: str) -> Path:
        """Get the hemigrid rollup store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's hemigrid rollup store.
        """
        return self.stores_root_dir / site_name / self.rollup_store_name

    def get_aux_data_dir(self) -> Path:
        """Get the directory for auxiliary data files.

        Returns
        -------
        Path
            Aux data directory (configured or system temp).
        """
        if self.aux_data_dir is not None:
            self.aux_data_dir.mkdir(parents=True, exist_ok=True)
            return self.aux_data_dir
        from tempfile import gettempdir

        return Path(gettempdir())

    def get_shared_aux_cache_dir(self) -> Path | None:
        """Get the network-wide shared aux cache directory, if configured.

        Returns
        -------
        Path | None
            The configured shared cache root, created if missing, or
            ``None`` when the feature is disabled (default).
        """
        if self.shared_aux_cache_dir is None:
            return None
        self.shared_aux_cache_dir.mkdir(parents=True, exist_ok=True)
        return self.shared_aux_cache_dir
