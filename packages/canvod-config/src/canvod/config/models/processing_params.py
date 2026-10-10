"""Processing-run parameters (resource limits, batching, ephemeris source, etc.)."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, model_validator

from .base import _StrictModel


class ProcessingParams(_StrictModel):
    """Processing parameters.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    resource_mode: Literal["auto", "manual"] = Field(
        "auto",
        description=(
            "'auto': OS auto-detects workers and memory (local machines). "
            "'manual': hard caps via n_max_threads, cpu_affinity and nice_priority "
            "(shared servers)."
        ),
    )
    n_max_threads: int | None = Field(
        None,
        ge=1,
        le=100,
        description=(
            "Max worker processes. Required when resource_mode='manual'. "
            "Ignored in 'auto'."
        ),
    )
    auto_uncapped: bool = Field(
        False,
        description=(
            "Remove the automatic CPU core cap in resource_mode='auto'. "
            "WARNING: enabling this on a shared machine can starve other users' "
            "processes. Only set True when the machine is exclusively yours."
        ),
    )
    keep_gnss_observables: list[str] = Field(
        default_factory=lambda: ["SNR"],
        description="GNSS observables to keep (SNR, Pseudorange, Phase, Doppler)",
    )
    rinex_v3_parser: Literal["validated", "unvalidated_fast"] = Field(
        "validated",
        description=(
            "How RINEX v3 observation files are parsed. 'validated': every "
            "epoch is checked (epoch line, satellite IDs, satellite count, "
            "observation fields); epochs that fail are dropped and logged. "
            "'unvalidated_fast': DANGEROUS. Parses by fixed columns without "
            "any check, so corrupted records can enter the store as partial "
            "or wrong values. On valid files both give the same dataset. "
            "canVODpy takes no responsibility for results of the unvalidated "
            "parser; checking the input files is entirely the user's "
            "responsibility. Every use emits an UnvalidatedParserWarning."
        ),
    )
    aggregate_glonass_fdma: bool = Field(
        True,
        description=(
            "Aggregate GLONASS FDMA sub-bands into effective G1/G2 bands. "
            "When False, the GLONASS signal IDs name the FDMA bands "
            "(G1_FDMA, G2_FDMA), for the observations and the orbit data "
            "alike. RINEX only: the SBF and NMEA readers refuse False. "
            "It changes the GLONASS signal IDs, so an existing store refuses "
            "data written with the other value."
        ),
    )
    store_radial_distance: bool = Field(
        False,
        description="Store radial distance (r) in the output store",
    )
    store_delta_snr: bool = Field(
        False,
        description=(
            "Store delta SNR (SNR_canopy − SNR_reference, dB) in the VOD store. "
            "Useful for diagnosing canopy attenuation without the angular correction."
        ),
    )
    store_radial_diff: bool = Field(
        False,
        description=(
            "Store radial distance difference (r_canopy − r_reference, m) in the "
            "VOD store. Requires store_radial_distance=true at ingest time so that "
            "r is available in both receiver datasets."
        ),
    )
    receiver_position_mode: Literal["shared", "per_receiver"] = Field(
        "shared",
        description=(
            "'shared': all receivers use the canopy receiver position for "
            "spherical coordinate computation (default, enables 1:1 SNR "
            "comparison). 'per_receiver': each receiver uses its own RINEX "
            "header position (physically correct geometry but breaks direct "
            "SNR comparability between receivers)."
        ),
    )
    file_pairing: Literal["complete", "paired"] = Field(
        "complete",
        description=(
            "'complete': discover files per-receiver independently (all data ingested). "
            "'paired': only process dates where both receivers in an analysis pair have data."
        ),
    )
    days_per_batch: int = Field(
        1,
        ge=1,
        le=30,
        description=(
            "Number of DOYs pooled per loky wave (1 = one day at a time). "
            "Raising this too high may cause connection issues with the "
            "ephemeris download server."
        ),
    )
    max_memory_gb: float | None = Field(
        None,
        gt=0,
        description=(
            "Left over from development; has no effect, canVODpy does not "
            "limit memory. Removed with the next major version."
        ),
    )
    cpu_affinity: list[int] | None = Field(
        None,
        description="Pin workers to specific CPU core IDs (None = no restriction)",
    )
    nice_priority: int = Field(
        -5,
        ge=-20,
        le=19,
        description=(
            "Process nice value (-20=highest priority, 0=normal, 19=lowest). "
            "Negative values raise worker priority above normal but require "
            "root/CAP_SYS_NICE on Linux -- silently has no effect otherwise "
            "(canvod.utils.tools.worker._worker_init swallows PermissionError)."
        ),
    )
    # TODO: investigate whether threads_per_worker is still needed after the loky /
    # ProcessPoolExecutor parallelisation refactor replaced Dask. If neither loky nor
    # the custom process-pool uses it, remove this field and its callsites in api.py.
    threads_per_worker: int | None = Field(
        None,
        ge=1,
        le=8,
        description=(
            "Threads per worker process. None lets the scheduler decide. "
            "Values >1 help with numpy/xarray ops and I/O (GIL-releasing) but not "
            "pure-Python RINEX text parsing."
        ),
    )
    ephemeris_source: Literal["final", "broadcast"] = Field(
        "final",
        description=(
            "'final': compute satellite coordinates from agency final products "
            "(SP3/CLK). 'broadcast': use broadcast ephemerides from SBF "
            "SatVisibility blocks (SBF reader_format only, skips SP3/CLK "
            "download). Broadcast is faster but less accurate (~1-2 m orbit)."
        ),
    )
    store_sbf_raw_observables: bool = Field(
        True,
        description=(
            "When reading SBF files, include the pre-correction 'raw' observable "
            "variables in obs_ds: SNR_raw (before CN0HighRes), "
            "Pseudorange_unsmoothed (before Hatch filter), "
            "Pseudorange_raw (before Hatch + multipath filters), and "
            "Phase_raw (before carrier multipath correction). "
            "Set to False to reduce dataset size when raw quantities are not needed."
        ),
    )
    store_sbf_metadata: bool = Field(
        True,
        description=(
            "When reading SBF files, store the per-file SBF metadata dataset "
            "(sbf_obs: SatVisibility geometry and its almanac/ephemeris source, "
            "MeasExtra, PVT, DOP, receiver status and quality indicators) under "
            "{group}/metadata/sbf_obs, in the same commit as the observations. "
            "Set to False to save space; broadcast geometry "
            "(ephemeris_source='broadcast') still works, since it uses sbf_obs "
            "in memory."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_max_memory_gb(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("max_memory_gb") is not None:
            import warnings

            warnings.warn(
                "The processing setting 'max_memory_gb' is left over from development and will be removed with the next major version. "
                "It has no effect: canVODpy does not limit memory. "
                "Remove it from your settings; to lower memory use, set fewer workers (n_max_threads) or a smaller days_per_batch.",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @model_validator(mode="after")
    def validate_resource_mode(self) -> ProcessingParams:
        """Validate resource_mode constraints.

        In 'manual' mode, ``n_max_threads`` must be set.
        In 'auto' mode, ``n_max_threads`` is ignored with a warning if set.
        """
        if self.resource_mode == "manual" and self.n_max_threads is None:
            msg = (
                "n_max_threads is required when resource_mode='manual'. "
                "Set n_max_threads to the number of worker processes you want."
            )
            raise ValueError(msg)
        if self.resource_mode == "auto" and self.n_max_threads is not None:
            import warnings

            warnings.warn(
                f"resource_mode='auto' ignores n_max_threads={self.n_max_threads}. "
                "Set resource_mode='manual' to enforce hard caps, "
                "or remove n_max_threads for auto mode.",
                UserWarning,
                stacklevel=2,
            )
        return self

    def resolve_resources(self) -> dict:
        """Resolve effective resource settings based on resource_mode.

        Returns
        -------
        dict
            Resolved resource values with keys: ``n_workers``,
            ``max_memory_gb``, ``cpu_affinity``, ``nice_priority``.
            In auto mode with ``auto_uncapped=False``, ``n_workers`` is
            ``max(1, cpu_count - 2)`` to leave headroom for the OS.
            With ``auto_uncapped=True``, ``n_workers`` is ``None`` (no cap).
        """
        if self.resource_mode == "auto":
            if self.auto_uncapped:
                n_workers = None
            else:
                n_workers = max(1, (os.cpu_count() or 2) - 2)
            return {
                "n_workers": n_workers,
                "max_memory_gb": None,
                "cpu_affinity": None,
                "nice_priority": -5,
                "threads_per_worker": self.threads_per_worker,
            }
        # manual mode
        return {
            "n_workers": self.n_max_threads,
            "max_memory_gb": self.max_memory_gb,
            "cpu_affinity": self.cpu_affinity,
            "nice_priority": self.nice_priority,
            "threads_per_worker": self.threads_per_worker,
        }
