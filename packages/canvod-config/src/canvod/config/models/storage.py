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
            "Turn on canvodpy store maintain-due. Off by default. Before you "
            "turn it on, run garbage_collect(dry_run=True) against your store "
            "and check what it would delete."
        ),
    )
    dry_run_until_confirmed: bool = Field(
        True,
        description=(
            "Make every run of canvodpy store maintain-due a dry run until you "
            "set this to false. An unattended job can't answer the question "
            "that maintain --execute asks; this setting is that answer."
        ),
    )
    retention_days: int = Field(
        90,
        ge=7,
        description=(
            "Days of snapshots the scheduled clean-up keeps; older snapshots "
            "are expired and their data collected as garbage. canvodpy store "
            "maintain --expire-days, run by hand, doesn't use it."
        ),
    )
    expire_interval_days: int = Field(
        45,
        ge=1,
        description=(
            "Days from one expiration by the scheduled clean-up to the next, "
            "counted from the last expiration in the store's operations log."
        ),
    )
    gc_delay_days: int = Field(
        20,
        ge=1,
        description=(
            "Days the scheduled clean-up waits after the last expiration before "
            "it collects garbage, so it deletes data only some time after their "
            "snapshots expired."
        ),
    )
    manifests_enabled: bool = Field(
        False,
        description=(
            "Let canvodpy store maintain-due rewrite the manifests, whatever "
            "'enabled' says. A rewrite is an ordinary commit: it changes no "
            "history and deletes nothing."
        ),
    )
    manifest_count_threshold: int = Field(
        3000,
        ge=1,
        description=(
            "Number of manifest files in the store at which canvodpy store "
            "maintain-due rewrites the manifests."
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
            "Folder of the stores: each site's GNSS store and VOD store are "
            "under it. Must exist and be writable."
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
            "Folder of an orbit and clock cache that several sites share (SP3 "
            "and CLK, interpolated). null (default): no shared cache; each "
            "site's cache is in aux_data_dir and rebuilt every run. Orbit and "
            "clock products are the same for every site, so sites that point at "
            "the same folder share one cache entry per agency, product and date "
            "instead of each building its own."
        ),
    )
    gnss_store_strategy: Literal["skip", "overwrite", "unsafe_append"] = Field(
        "skip",
        description=(
            "What a run does with a file that is already in the GNSS store; new "
            "files are always written. 'skip' (default): nothing is written. "
            "'overwrite': the run replaces the file's stored data. "
            "'unsafe_append': the file is written again next to the stored "
            "data. In a store made of day blocks, 'overwrite' and "
            "'unsafe_append' both replace the file's slots; in a store written "
            "by appending, 'unsafe_append' stores the file's epochs twice."
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
            "Tag every commit of a receiver and day as "
            "keep/{receiver}/{yyyydoy}, so a later clean-up can expire "
            "everything else. Off by default: the cost of tagging a large store "
            "hasn't been measured yet."
        ),
    )
    maintenance: MaintenanceConfig = Field(
        default_factory=MaintenanceConfig,
        description="Scheduled clean-up of old snapshots (canvodpy store maintain-due)",
    )

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
