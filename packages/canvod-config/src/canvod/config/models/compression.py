"""NetCDF compression and Icechunk storage-engine configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .base import _StrictModel


class NetcdfCompressionConfig(_StrictModel):
    """NetCDF compression settings used by RINEX readers when writing .nc files.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    zlib: bool = Field(True, description="Compress the NetCDF files with zlib")
    complevel: int = Field(5, ge=0, le=9, description="Compression level")


CompressionConfig = NetcdfCompressionConfig  # deprecated alias


class ChunkStrategy(_StrictModel):
    """Chunking strategy for a dimension.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    epoch: int = Field(
        ...,
        ge=1,
        description=(
            "Epochs per chunk, for groups created from now on: a group keeps "
            "the chunk size it was created with"
        ),
    )
    sid: int = Field(
        -1,
        ge=-1,
        description=(
            "Signals per chunk, for groups created from now on; -1 puts all "
            "signals in one chunk."
        ),
    )

    @field_validator("sid")
    @classmethod
    def _sid_is_not_zero(cls, v: int) -> int:
        if v == 0:
            msg = "sid is -1 (all signals in one chunk) or a positive number of signals"
            raise ValueError(msg)
        return v


class ChunkStrategies(_StrictModel):
    """Chunking strategy per store type.

    Notes
    -----
    This is a Pydantic model for configuration validation. A fixed field per
    store type, so a misspelled store type fails validation instead of
    leaving that store unchunked.
    """

    # Each day of a group is stored in whole chunks (ADR 0016), padded where
    # its epochs do not fill the last one. 180 = one 15-minute file at a 5 s
    # sampling interval, and 1 s to 1 min days need no padding.
    gnss_store: ChunkStrategy = Field(
        default_factory=lambda: ChunkStrategy(epoch=180, sid=-1),
        description=(
            "Chunks of the GNSS store. A day of ceil(86400 s / cadence) epochs "
            "is stored in whole chunks, padded with empty epochs where it does "
            "not fill the last one: with 180, days at 1 s, 5 s, 15 s, 30 s or "
            "1 min need no padding, a day at 15 min gets 84 empty epochs."
        ),
    )
    vod_store: ChunkStrategy = Field(
        default_factory=lambda: ChunkStrategy(epoch=180, sid=-1),
        description=(
            "Chunks of the VOD store. As in the GNSS store, each day is stored "
            "in whole chunks, padded with empty epochs where it does not fill "
            "the last one."
        ),
    )


class IcechunkConfig(_StrictModel):
    """Icechunk storage configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    compression_level: int = Field(
        3, ge=0, le=22, description="Zstandard compression level, 0 to 22"
    )
    compression_algorithm: Literal["zstd"] = Field(
        "zstd", description="Compression algorithm; Icechunk 2 offers only 'zstd'"
    )
    inline_chunk_threshold_bytes: int = Field(
        512,
        ge=0,
        description=(
            "Chunks up to this size in bytes are stored in the manifest "
            "instead of in their own file"
        ),
    )
    get_partial_values_concurrency: int = Field(
        1, ge=1, description="Concurrent requests when reading part of a chunk"
    )
    max_concurrent_requests: int | None = Field(
        None,
        ge=1,
        description=(
            "Limit on concurrent storage requests (null = Icechunk's default)"
        ),
    )
    zarr_async_concurrency: int | None = Field(
        None,
        ge=1,
        description=(
            "Limit on Zarr's concurrent chunk writes per array, for the writes "
            "made through the store's own write methods; null keeps Zarr's "
            "default of 10. The GNSS store writes of 'canvodpy run' and the "
            "day-block writes don't use it. A lower value, for example 2 to 4, "
            "makes the writes it covers slower."
        ),
    )
    cache_num_chunk_refs: int | None = Field(
        None,
        ge=0,
        description=(
            "Number of chunk references Icechunk keeps in memory (null = "
            "Icechunk's default)"
        ),
    )
    cache_num_bytes_chunks: int | None = Field(
        None,
        ge=0,
        description=(
            "Bytes of chunk data Icechunk keeps in memory (null = Icechunk's default)"
        ),
    )
    chunk_strategies: ChunkStrategies = Field(
        default_factory=ChunkStrategies,
        description=(
            "Chunk shape of each store: a chunk is the piece of an array that "
            "is read, compressed, and written as one"
        ),
    )
    manifest_preload_enabled: bool = Field(
        False,
        description=("Read the manifests of matching arrays when a store is opened"),
    )
    manifest_preload_max_refs: int = Field(
        10_000,
        ge=0,
        description="Limit on the chunk references read in advance",
    )
    manifest_preload_max_arrays_to_scan: int = Field(
        500,
        ge=1,
        description="Limit on the arrays checked for reading in advance",
    )
    manifest_preload_pattern: str = Field(
        r"^(epoch|sid)$",
        description=(
            "Regular expression for the names of the arrays to read in advance"
        ),
    )
    manifest_splitting_enabled: bool = Field(
        True,
        description="Enable manifest splitting for stores with large arrays (recommended)",
    )
    manifest_splitting_epoch_range: int = Field(
        17280,
        ge=1,
        description=(
            "Epoch chunks per manifest: Icechunk starts a new manifest of an "
            "array every N chunks along the epoch dimension (N chunks, not N "
            "epochs)."
        ),
    )
    num_updates_per_repo_info_file: int | None = Field(
        None,
        ge=1,
        le=65535,
        description=(
            "Number of updates that share one 'repo' file before Icechunk "
            "starts a new one (null = Icechunk's default). A low value makes "
            "each write smaller but makes reading the history slower."
        ),
    )
    repo_update_max_tries: int | None = Field(
        None,
        ge=1,
        description=(
            "Attempts, the first included, to update the 'repo' file, for "
            "example when several writers update it (null = Icechunk's default, "
            "currently 100)"
        ),
    )
    repo_update_initial_backoff_ms: int | None = Field(
        None,
        ge=0,
        description=(
            "First wait in milliseconds between attempts to update the 'repo' "
            "file (null = Icechunk's default, currently 50)"
        ),
    )
    repo_update_max_backoff_ms: int | None = Field(
        None,
        ge=0,
        description=(
            "Longest wait in milliseconds between attempts to update the 'repo' "
            "file (null = Icechunk's default, currently 30,000)"
        ),
    )
