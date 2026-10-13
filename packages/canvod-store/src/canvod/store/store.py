import contextlib
import io
import json
import os
import sys
import time
from collections.abc import Generator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import icechunk
import numpy as np
import polars as pl
import structlog
import xarray as xr
import zarr
from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingMismatchError,
    describe_settings,
    preprocessing_record,
    preprocessing_settings,
    preprocessing_steps,
    split_preprocessing,
    vod_preprocessing_settings,
)
from canvod.readers.base import validate_vod_dataset
from canvod.store_metadata import RESERVED_GROUP
from canvod.store_metadata.icechunk_logs import apply_icechunk_log_filter
from canvod.store_metadata.io import (
    commit_lock,
    commit_with_rebase,
    rewrite_manifests,
    store_command,
)
from canvod.store_metadata.location import open_repository, repository_config
from canvod.store_metadata.summary import cadence_ranges
from canvod.utils.logging import get_run_id, stage_timer
from canvod.utils.tools import (
    deprecated,
    get_version_from_pyproject,
    sanitize_directory,
)
from icechunk.session import ForkSession
from icechunk.xarray import to_icechunk
from zarr.dtype import VariableLengthUTF8

from canvod.store.prepare import prepare_write
from canvod.store.time_encoding import with_time_units
from canvod.store.viewer import add_rich_display_to_store
from canvod.store.zarr_concurrency import scoped_zarr_concurrency

apply_icechunk_log_filter()  # see canvod.store_metadata.icechunk_logs

if TYPE_CHECKING:
    from canvod.config.models import CanvodConfig
    from icechunk import AncestryGraph


class _PatchedAncestryGraph:
    """Wraps icechunk AncestryGraph to make SVG text readable in both color schemes."""

    def __init__(self, graph: "AncestryGraph") -> None:  # noqa: UP037
        self._graph = graph

    def _repr_html_(self) -> str:
        import uuid

        svg = self._graph._repr_svg_()
        # Wrap the SVG in a <div> with a unique ID so CSS selectors are scoped
        # and cannot bleed into surrounding notebook/DOM styles.
        # _repr_html_ takes priority over _repr_svg_ in Jupyter/marimo display.
        _id = f"icg{uuid.uuid4().hex[:8]}"
        style = (
            f"<style>"
            f"#{_id} rect{{fill:#f9fafb!important;stroke:#e5e7eb!important}}"
            f"#{_id} text{{fill:#1f2937!important}}"
            f"@media(prefers-color-scheme:dark){{"
            f"#{_id} rect{{fill:#1a1a1a!important;stroke:#374151!important}}"
            f"#{_id} text{{fill:#ffffff!important}}"
            f"}}"
            f"</style>"
            f'<div id="{_id}">{svg}</div>'
        )
        return style

    def __repr__(self) -> str:
        return repr(self._graph)

    def __str__(self) -> str:
        return str(self._graph)


def _with_run_id(commit_message: str) -> str:
    """Append the current run_id (if any) to a commit message.

    Lets a human or an agent correlate an Icechunk commit with the run
    that produced it, by grepping the same run_id across the commit log
    and the agent-diagnostic log (see ``canvod.utils.logging.run_context``).
    Append-only: does not change caller-provided commit message content.
    """
    run_id = get_run_id()
    if run_id is None:
        return commit_message
    return f"{commit_message} (run={run_id})"


class BranchMovedError(RuntimeError):
    """A branch moved while work for it was staged on a temporary branch.

    Promoting the temporary branch would drop the commits made in the
    meantime, so canVODpy refuses and keeps the temporary branch.
    """


def _json_log_row(row: dict[str, Any]) -> dict[str, Any]:
    """A log-book row with JSON or plain-text values only.

    The dataset attributes (``dataset_attrs``, as the run passes them, or
    ``attrs``) become JSON in the ``attrs`` column; the preprocessing record
    they carry moves to the ``preprocessing`` column; paths become text.
    """
    row = dict(row)
    attrs = row.pop("dataset_attrs", row.get("attrs", {}))
    if isinstance(attrs, str):
        attrs = json.loads(attrs) if attrs else {}
    attrs, record = split_preprocessing(attrs)
    row["attrs"] = json.dumps(attrs, default=str)
    row.setdefault("preprocessing", record)
    return {k: str(v) if isinstance(v, Path) else v for k, v in row.items()}


def _written_rows_overlapping(
    df: pl.DataFrame, start: np.datetime64, end: np.datetime64
) -> pl.DataFrame:
    """Log-book rows whose data overlap ``[start, end]``, without rows of
    files skipped as already ingested (nothing was written for them)."""
    start_ns = np.datetime64(start, "ns")
    end_ns = np.datetime64(end, "ns")
    rows = df.filter((pl.col("start") <= end_ns) & (pl.col("end") >= start_ns))
    # Older rows have no action, only ``exists``; API rows have no ``exists``.
    exists = pl.col("exists") == "True" if "exists" in rows.columns else pl.lit(False)
    if "action" in rows.columns:
        skipped = (pl.col("action") == "skipped") | ((pl.col("action") == "") & exists)
    else:
        skipped = exists
    return rows.filter(~skipped)


#: Log-book action of a row that describes a change to the whole group
#: (:meth:`MyIcechunkStore.add_group_variables`), not the data of one file.
#: Its ``start`` and ``end`` are empty (NaT) and its ``rinex_hash`` is "", so
#: the duplicate checks never match it; its ``preprocessing`` record holds
#: only the steps it applied to the data already in the group.
GROUP_WIDE_ACTION = "add_variables"

#: What a VOD write does with a result already in the store: it skips it.
#: Recorded in the ``write_strategy`` column of the VOD store's log book.
VOD_WRITE_STRATEGY = "skip"


def _extend_record(record: str, added: list[str], vod: bool) -> str:
    """``record`` with the steps of the group-wide records ``added`` appended.

    For a VOD store, ``record`` holds the GNSS records behind a result
    (``vod_preprocessing_record``); the steps are appended to each of them.
    """
    if not added:
        return record
    if vod:
        sources = json.loads(record) if record else {"": [""]}
        return json.dumps(
            {
                name: [_extend_record(r, added, vod=False) for r in records]
                for name, records in sources.items()
            },
            sort_keys=True,
        )
    steps = preprocessing_steps(record)
    software = dict(json.loads(record).get("software", {})) if record else {}
    for group_wide in added:
        steps += preprocessing_steps(group_wide)
        software.update(json.loads(group_wide)["software"])
    return preprocessing_record(steps, software)


def _effective_preprocessing(df: pl.DataFrame, vod: bool) -> pl.DataFrame:
    """File rows of a log book, each with the preprocessing its data have now.

    That is the row's own record plus the steps of every group-wide row
    (:data:`GROUP_WIDE_ACTION`) written after it. Group-wide rows are left
    out.
    """
    if "action" not in df.columns or "preprocessing" not in df.columns:
        return df
    is_group_wide = pl.col("action") == GROUP_WIDE_ACTION
    group_wide = df.filter(is_group_wide).sort("index")
    files = df.filter(~is_group_wide)
    if group_wide.is_empty():
        return files
    gw_index = group_wide["index"].to_list()
    gw_records = group_wide["preprocessing"].to_list()
    cache: dict[tuple[str, int], str] = {}
    effective = []
    for index, record in zip(
        files["index"].to_list(), files["preprocessing"].to_list(), strict=True
    ):
        first_later = next(
            (i for i, gw in enumerate(gw_index) if gw > index), len(gw_index)
        )
        key = (record, first_later)
        if key not in cache:
            cache[key] = _extend_record(record, gw_records[first_later:], vod)
        effective.append(cache[key])
    return files.with_columns(pl.Series("preprocessing", effective))


def _time_or_none(value: np.datetime64) -> np.datetime64 | None:
    """``value`` in ns for a log-book row; ``None`` for NaT (a group-wide row)."""
    value = np.datetime64(value, "ns")
    return None if np.isnat(value) else value


def _describe(record: str, settings_of: Any) -> str:
    """Operations and settings of a GNSS or VOD record, as text."""
    return describe_settings(settings_of(record))


def _append_log_rows(zmeta: zarr.Group, df: pl.DataFrame) -> None:
    """Append rows to a log-book table (``{group}/metadata/table``).

    Assigns continuous ``index`` values and keeps every column at the
    table's row count: a column new to the table is backfilled for the rows
    already stored, and a stored column absent from ``df`` is padded (``""``
    for strings, ``NaT`` for ``start``/``end``). Tables written by different
    ingest paths, or by older canVODpy versions with fewer columns, therefore
    stay readable as one DataFrame.
    """
    start_index = 0
    existing_len = 0
    if "index" in zmeta:
        existing_len = zmeta["index"].shape[0]
        start_index = int(zmeta["index"][-1].item()) + 1 if existing_len > 0 else 0

    df_with_index = df.with_columns(
        (pl.arange(start_index, start_index + df.height)).alias("index")
    )

    def _column_spec(col_name: str) -> tuple[Any, Any]:
        """(dtype, fill value) of a log-book column."""
        if col_name == "index":
            return "i8", 0
        if col_name in ("start", "end"):
            return "M8[ns]", np.datetime64("NaT", "ns")
        # strings / jsons / ids
        return VariableLengthUTF8(), ""

    for col_name in df_with_index.columns:
        col_data = df_with_index[col_name]
        dtype, fill = _column_spec(col_name)

        if col_name in ("index", "start", "end"):
            arr = col_data.to_numpy().astype(dtype)
        else:
            arr = col_data.to_list()

        if col_name not in zmeta:
            zmeta.create_array(
                name=col_name,
                shape=(existing_len,),
                dtype=dtype,
                chunks=(1024,),
                fill_value=fill,
                overwrite=True,
            )
            if existing_len:
                zmeta[col_name][:] = (
                    [fill] * existing_len
                    if isinstance(fill, str)
                    else np.full(existing_len, fill, dtype=dtype)
                )

        # Resize and append
        old_len = zmeta[col_name].shape[0]
        new_len = old_len + len(arr)
        zmeta[col_name].resize(new_len)
        zmeta[col_name][old_len:new_len] = arr

    for col_name in set(zmeta.array_keys()) - set(df_with_index.columns):
        dtype, fill = _column_spec(col_name)
        old_len = zmeta[col_name].shape[0]
        new_len = old_len + df_with_index.height
        zmeta[col_name].resize(new_len)
        zmeta[col_name][old_len:new_len] = (
            [fill] * df_with_index.height
            if isinstance(fill, str)
            else np.full(df_with_index.height, fill, dtype=dtype)
        )


@dataclass
class VodWriteItem:
    """One VOD analysis pair's write request, as passed into a batch write."""

    group_name: str
    dataset: xr.Dataset
    source_file_hashes: dict[str, str]
    source_gnss_stores: dict[str, str]
    calculator_name: str
    commit_message: str | None = None


@dataclass
class VodWritePlan:
    """A `VodWriteItem` after dedup-check + normalization, ready to write."""

    item: VodWriteItem
    action: str  # "write" | "append"
    start: np.datetime64
    end: np.datetime64
    commit_message: str  # per-group description, then the batch commit message
    dataset: xr.Dataset


def _vod_batch_commit(
    version: str, action: str, plans: Sequence[VodWritePlan]
) -> tuple[str, dict[str, str]]:
    """Commit message and metadata for the VOD groups sharing one commit.

    Sets each plan's ``commit_message`` to the returned message, so the
    log-book rows written for these groups match the commit exactly.
    """
    message = _with_run_id(
        f"[v{version}] {action} " + "; ".join(p.commit_message for p in plans)
    )
    metadata = {
        "groups": ",".join(p.item.group_name for p in plans),
        "total_groups": str(len(plans)),
        "start": str(min(p.start for p in plans)),
        "end": str(max(p.end for p in plans)),
        "source_file_hashes": json.dumps(
            {p.item.group_name: p.item.source_file_hashes for p in plans},
            sort_keys=True,
        ),
    }
    for plan in plans:
        plan.commit_message = message
    return message, metadata


@dataclass
class VodWriteResult:
    group_name: str
    written: bool
    skip_reason: str | None = None
    snapshot_id: str | None = None
    duration_seconds: float = 0.0


@add_rich_display_to_store
class MyIcechunkStore:
    """
    Core Icechunk store manager for GNSS data.

    This class encapsulates all operations on a single Icechunk repository,
    providing a clean interface for GNSS data storage and retrieval with
    integrated logging and proper resource management.

    Features:
    - Automatic repository creation/connection
    - Group management with validation
    - Session management with context managers
    - Integrated logging with file contexts
    - Configurable compression and chunking

    Note on "metadata"
    ------------------
    This class manages two distinct things both historically called "metadata":

    - **File registry** (``{group}/metadata/table``): per-file ingest ledger
      tracking hashes, temporal ranges, filenames, and paths. Managed by
      ``append_metadata()``, ``load_metadata()``, ``backup_metadata_table()``, etc.

    - **Store metadata** (``canvod.store_metadata`` package): store-level
      provenance (identity, creator, environment, compliance). Written to
      Zarr root attrs by the orchestrator. See ``canvod-store-metadata``.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store directory.
    store_type : str, default "gnss_store"
        Type of store ("gnss_store" or "vod_store").
    compression_level : int | None, optional
        Override default compression level.
    compression_algorithm : str | None, optional
        Override default compression algorithm.

    Attributes
    ----------
    store_path : Path
        Path to the Icechunk store directory.
    store_type : str
        Type of store ("gnss_store" or "vod_store").
    compression_level : int
        Compression level (1-9).
    compression_algorithm : icechunk.CompressionAlgorithm
        Compression algorithm enum.
    repo : icechunk.Repository
        The Icechunk repository instance.
    """

    def __init__(
        self,
        store_path: Path,
        store_type: str = "gnss_store",
        compression_level: int | None = None,
        compression_algorithm: str | None = None,
        *,
        config: CanvodConfig | None = None,
    ) -> None:
        """Initialize the Icechunk store manager.

        Parameters
        ----------
        store_path : Path
            Path to the Icechunk store directory.
        store_type : str, default "gnss_store"
            Type of store ("gnss_store" or "vod_store").
        compression_level : int | None, optional
            Override default compression level.
        compression_algorithm : str | None, optional
            Override default compression algorithm.
        config : CanvodConfig | None, optional
            The settings the store works with; every commit records them.
            ``None`` loads the settings.
        """
        self._logger = structlog.get_logger(__name__)

        from canvod.config import load_config

        # No fallback: settings that fail to load raise here, so a store is
        # never opened with defaults the user didn't choose.
        cfg = config if config is not None else load_config()
        self.settings = cfg
        ic_cfg = cfg.processing.icechunk
        _gnss_store_strategy = cfg.processing.storage.gnss_store_strategy
        _log_path_depth = cfg.processing.logging.log_path_depth

        self.store_path = Path(store_path)
        self.store_type = store_type

        # Compression — icechunk v2 only supports zstd
        self.compression_level = compression_level or ic_cfg.compression_level
        self.compression_algorithm = icechunk.CompressionAlgorithm.Zstd

        # Chunk strategy: one per store type, no silent fallback to no chunking
        if store_type not in type(ic_cfg.chunk_strategies).model_fields:
            msg = (
                f"Unknown store_type {store_type!r}; expected one of "
                f"{list(type(ic_cfg.chunk_strategies).model_fields)}"
            )
            raise ValueError(msg)
        strategy = getattr(ic_cfg.chunk_strategies, store_type)
        self.chunk_strategy = {"epoch": strategy.epoch, "sid": strategy.sid}

        # Storage config cached for metadata rows
        self._gnss_store_strategy = _gnss_store_strategy
        self._log_path_depth = _log_path_depth
        self._zarr_async_concurrency = ic_cfg.zarr_async_concurrency

        # The same repository configuration a run creates a new store with
        self.config = repository_config(
            ic_cfg, compression_level=self.compression_level
        )
        if ic_cfg.manifest_preload_enabled:
            self._logger.info(
                "Manifest preload enabled: "
                f"pattern={ic_cfg.manifest_preload_pattern!r}, "
                f"max_refs={ic_cfg.manifest_preload_max_refs}"
            )
        if ic_cfg.manifest_splitting_enabled:
            self._logger.info(
                "Manifest splitting enabled: "
                f"epoch_range={ic_cfg.manifest_splitting_epoch_range}"
            )

        self._repo = None

        # Remove .DS_Store files that corrupt icechunk ref listing on macOS
        self._clean_ds_store()
        self._open()

    def _to_icechunk_throttled(
        self, dataset: xr.Dataset, session, *, throttle: bool | None = None, **kwargs
    ) -> None:
        """Write via ``to_icechunk``, optionally capping zarr's async concurrency.

        Zarr v3 issues chunk writes for a single array as a concurrent
        ``asyncio.gather`` burst, sized by ``zarr.config``'s
        ``async.concurrency`` (default 10). On network-mounted (CIFS/NFS)
        stores that burst can trip connection-abort errors under load — but
        capping it costs throughput, so it's opt-in via
        ``IcechunkConfig.zarr_async_concurrency`` (None = untouched).

        ``throttle`` overrides the config-derived default when explicitly
        passed; leave it ``None`` to defer to config.
        """
        dataset = prepare_write(
            dataset, session.store, kwargs["group"], append_dim=kwargs.get("append_dim")
        )
        if "encoding" in kwargs:
            kwargs["encoding"] = with_time_units(dataset, kwargs["encoding"])
        should_throttle = (
            self._zarr_async_concurrency is not None if throttle is None else throttle
        )
        if not should_throttle:
            to_icechunk(dataset, session, **kwargs)
            return
        if self._zarr_async_concurrency is None:
            raise ValueError(
                "throttle=True requires IcechunkConfig.zarr_async_concurrency to be "
                "set; got None. Configure a cap (e.g. 2-4) or pass throttle=False/None."
            )
        with scoped_zarr_concurrency(self._zarr_async_concurrency):
            to_icechunk(dataset, session, **kwargs)

    def chunk_encoding_for(
        self, ds: xr.Dataset
    ) -> dict[str, dict[str, tuple[int, ...]]]:
        """Build ``{var: {"chunks": (...)}}`` matching ``self.chunk_strategy``.

        Only meaningful at group creation -- Zarr fixes an array's chunk
        shape the moment it's first written, so this must be passed as
        ``encoding=`` on the ``mode="w"`` call, never on an append (which
        must match whatever shape creation already fixed).

        Without this, ``chunk_strategies`` config only ever affected
        *read*-side chunking (the ``chunks=`` hint passed to
        ``xr.open_zarr`` elsewhere in this class) -- nothing applied it at
        write time, so the physical on-disk chunk shape was left to Zarr's
        own default, silently disconnected from config. Confirmed by
        grepping this file and processor.py for any ``encoding["chunks"]``
        assignment: there wasn't one anywhere (2026-07-18).

        A dim with a configured chunk size (e.g. ``epoch: 17280``) gets
        exactly that size regardless of how much data is in *this*
        particular write -- Zarr supports writing less than one full chunk
        in the first call and filling the rest on later appends, which is
        the whole point of fixing chunk shape once at creation. A dim
        configured ``-1`` (or unconfigured) gets one chunk spanning
        whatever this write's current size is (e.g. ``sid: -1`` -> the
        full SID universe already present at creation).
        """
        if not self.chunk_strategy:
            return {}
        encoding: dict[str, dict[str, tuple[int, ...]]] = {}
        for var in (*ds.data_vars, *ds.coords):
            dims = ds[var].dims
            if not dims:
                continue
            chunk_shape = tuple(
                ds.sizes[dim]
                if self.chunk_strategy.get(dim, -1) == -1
                else self.chunk_strategy[dim]
                for dim in dims
            )
            encoding[str(var)] = {"chunks": chunk_shape}
        return encoding

    def _for_group_creation(
        self, ds: xr.Dataset
    ) -> tuple[xr.Dataset, dict[str, dict[str, tuple[int, ...]]]]:
        """Return ``ds`` and the ``encoding=`` for a write that creates a group.

        The encoding sets the stored chunks to ``self.chunk_strategy`` (see
        :meth:`chunk_encoding_for`). A Dask-backed ``ds`` is rechunked to the
        same chunks, because a Dask chunk that spans two stored chunks can't
        be written safely.
        """
        if ds.chunks and self.chunk_strategy:
            strategy = self.chunk_strategy.items()
            ds = ds.chunk({dim: size for dim, size in strategy if dim in ds.dims})
        return ds, self.chunk_encoding_for(ds)

    def _clean_ds_store(self) -> None:
        """Remove .DS_Store files from the store directory tree.

        macOS creates these files automatically and they corrupt icechunk's
        ref listing, causing 'invalid ref type `.DS_Store`' errors.
        """
        for removed in sanitize_directory(self.store_path):
            self._logger.debug(f"Removed {removed}")

    def _normalize_encodings(self, ds: xr.Dataset) -> xr.Dataset:
        """Normalize dataset encodings for Icechunk.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to normalize.

        Returns
        -------
        xr.Dataset
            Dataset with normalized encodings.
        """
        for v in ds.data_vars:
            if "dtype" in ds[v].encoding:
                ds[v].encoding["dtype"] = np.dtype(ds[v].dtype)
        # Cast string-like / non-numeric coords to numpy object for Zarr V3.
        #
        # Why np.array(raw, dtype=object) instead of raw.astype(object):
        # In numpy 2.x, StringDType.astype(object) can silently return StringDType
        # when the array is a Dask lazy computation. np.array() box-constructs a
        # new object array from scratch, guaranteeing object dtype regardless of
        # input type or lazy-evaluation state.
        #
        # Batching strategy: collect all Dask-backed coords first, compute them in
        # one dask.compute() call (one scheduler pass), then handle numpy-backed
        # coords. Reduces ~7 separate graph walks to 1 on a lazy VOD dataset.
        _numeric_kinds = frozenset("fiucbmMV")
        str_coords: dict = {}
        dask_coords: dict = {}
        numpy_coords: dict = {}

        for name in list(ds.coords):
            da = ds[name]
            if da.dtype.kind in _numeric_kinds:
                continue
            if da.chunks is None and da.dtype == object:
                continue  # already correct numpy object
            if da.chunks is not None:
                dask_coords[name] = da
            else:
                numpy_coords[name] = da

        # Batch-compute all dask-backed string coords in ONE scheduler pass
        # (a coord that cannot be computed raises: dropping it would write
        # the dataset without it)
        if dask_coords:
            import dask

            computed = dask.compute(*dask_coords.values())
            for name, computed_da in zip(dask_coords.keys(), computed):
                raw = (
                    computed_da.values
                    if hasattr(computed_da, "values")
                    else np.asarray(computed_da)
                )
                if raw.dtype != object:
                    raw = np.array(raw, dtype=object)
                str_coords[name] = (
                    dask_coords[name].dims,
                    raw,
                    dask_coords[name].attrs,
                )

        # Numpy-backed non-object coords (StringDType, unicode kind 'U')
        for name, da in numpy_coords.items():
            raw = da.values
            if raw.dtype != object:
                raw = np.array(raw, dtype=object)
            str_coords[name] = (da.dims, raw, da.attrs)

        if str_coords:
            ds = ds.assign_coords(str_coords)
        for name in list(ds.data_vars):
            if ds[name].dtype.kind in ("U", "T"):
                ds[name] = ds[name].astype(object)
        # Eagerly compute any remaining Dask-backed object data variables
        import dask.array as da_mod

        for name in list(ds.data_vars):
            if ds[name].dtype == object and isinstance(ds[name].data, da_mod.Array):
                ds[name] = ds[name].compute()
        return ds

    def _open(self) -> None:
        """Open the store's repository; never create it.

        Only the step every run takes first (``ensure_store_metadata``)
        creates a store, so a mistyped path fails here instead of leaving
        an empty store behind.

        Raises
        ------
        FileNotFoundError
            If no store is at ``store_path``.
        """
        self._logger.info(f"Opening Icechunk store at {self.store_path}")
        self._repo = open_repository(self.store_path, config=self.config)

    @property
    def repo(self) -> icechunk.Repository:
        """Get the repository instance."""
        if self._repo is None:
            self._open()
        return self._repo

    @property
    def site_name(self) -> str:
        """The site this store was written for, from its repository metadata.

        Never the name of the directory the store sits in, so moving or
        renaming the directory doesn't change it.

        Raises
        ------
        ValueError
            If the store has no repository metadata.
        """
        site = self.repo.get_metadata().get("spatial", {}).get("site", {})
        name = site.get("name")
        if not name:
            msg = (
                f"The store at {self.store_path} has no repository metadata, "
                "so it doesn't say which site it holds. Move it to the "
                "current form with:\n"
                f"  {store_command('migrate-metadata', 'SITE', self.store_type)}"
            )
            raise ValueError(msg)
        return name

    @contextlib.contextmanager
    def readonly_session(
        self,
        branch: str = "main",
    ) -> Generator[icechunk.Session]:
        """Thin wrapper over ``repo.readonly_session()`` for this CM."""
        yield self.repo.readonly_session(branch)

    @contextlib.contextmanager
    def writable_session(
        self,
        branch: str = "main",
    ) -> Generator[icechunk.Session]:
        """Thin wrapper over ``repo.writable_session()`` for this CM."""
        yield self.repo.writable_session(branch)

    # ── Root-level store attributes ────────────────────────────────────────────

    def set_root_attrs(self, attrs: dict[str, Any], branch: str = "main") -> str:
        """Set root-level Zarr attributes on the store.

        Parameters
        ----------
        attrs : dict[str, Any]
            Key-value pairs to merge into root attrs.
        branch : str, default "main"
            Branch to write to.

        Returns
        -------
        str
            Snapshot ID from the commit.
        """
        message = f"Set root attrs: {list(attrs.keys())}"
        session = self.repo.writable_session(branch)
        try:
            root = zarr.open_group(session.store, mode="r+")
        except zarr.errors.GroupNotFoundError:
            root = zarr.open_group(session.store, mode="w")
        root.attrs.update(attrs)
        return commit_with_rebase(
            session, message, store_path=self.store_path, config=self.settings
        )

    def get_root_attrs(self, branch: str = "main") -> dict[str, Any]:
        """Read root-level Zarr attributes from the store.

        Returns
        -------
        dict[str, Any]
            Root attributes (empty dict if none set).
        """
        try:
            with self.readonly_session(branch) as session:
                root = zarr.open_group(session.store, mode="r")
                return dict(root.attrs)
        except Exception:
            return {}

    @property
    def source_format(self) -> str | None:
        """Return the ``source_format`` root attribute, or None."""
        return self.get_root_attrs().get("source_format")

    def get_branch_names(self) -> list[str]:
        """
        List all branches in the store.

        Returns
        -------
        list[str]
            List of branch names.
        """
        return list(self.repo.list_branches())

    def get_group_names(self, branch: str | None = None) -> dict[str, list[str]]:
        """
        List all groups in the store.

        Parameters
        ----------
        branch: Optional[str]
            Repository branch to examine. Defaults to listing groups from all branches.

        Returns
        -------
        dict[str, list[str]]
            Dictionary mapping branch names to lists of group names.

        """
        branches = [branch] if branch else self.get_branch_names()
        group_dict = {}
        for br in branches:
            with self.readonly_session(br) as session:
                try:
                    root = zarr.open(session.store, mode="r")
                    group_dict[br] = [
                        name for name in root.group_keys() if name != RESERVED_GROUP
                    ]
                except zarr.errors.GroupNotFoundError:
                    group_dict[br] = []
        return group_dict

    def list_groups(self, branch: str = "main") -> list[str]:
        """
        List all groups in a branch.

        Parameters
        ----------
        branch : str
            Branch name (default: "main")

        Returns
        -------
        list[str]
            List of group names in the branch
        """
        group_dict = self.get_group_names(branch=branch)
        if branch in group_dict:
            return group_dict[branch]
        return []

    @property
    def tree(self) -> None:
        """Print hierarchical tree of all branches and groups. See ``print_tree``."""
        self.print_tree(max_depth=None)

    def print_tree(self, max_depth: int | None = None) -> None:
        """
        Display hierarchical tree of all branches, groups, and subgroups.

        Parameters
        ----------
        max_depth : int | None
            Maximum depth to display. None for unlimited depth.
            - 0: Only show branches
            - 1: Show branches and top-level groups
            - 2: Show branches, groups, and first level of subgroups/arrays
            - etc.
        """
        try:
            branches = self.get_branch_names()

            for i, branch in enumerate(branches):
                is_last_branch = i == len(branches) - 1
                branch_prefix = "└── " if is_last_branch else "├── "

                if max_depth is not None and max_depth < 1:
                    continue

                session = self.repo.readonly_session(branch)
                root = zarr.open(session.store, mode="r")

                if i == 0:
                    sys.stdout.write(f"{self.store_path}\n")

                sys.stdout.write(f"{branch_prefix}{branch}\n")
                # Build tree recursively
                branch_indent = "    " if is_last_branch else "│   "
                self._build_tree(root, branch_indent, max_depth, current_depth=1)

        except Exception as e:
            self._logger.warning(f"Failed to generate tree for {self!r}: {e}")
            sys.stdout.write(f"Error generating tree: {e}\n")

    def _build_tree(
        self,
        group: zarr.Group,
        prefix: str,
        max_depth: int | None,
        current_depth: int = 0,
    ) -> None:
        """Recursively build a tree structure.

        Parameters
        ----------
        group : zarr.Group
            Root group to traverse.
        prefix : str
            Prefix string for tree formatting.
        max_depth : int | None
            Maximum depth to display. None for unlimited.
        current_depth : int, default 0
            Current recursion depth.

        Returns
        -------
        None
        """
        if max_depth is not None and current_depth >= max_depth:
            return

        # Get all groups and arrays (not the reserved group at the root)
        groups = [
            name
            for name in group.group_keys()
            if not (current_depth == 0 and name == RESERVED_GROUP)
        ]
        arrays = list(group.array_keys())
        items = groups + arrays

        for i, item_name in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "

            if item_name in groups:
                # It's a group
                sys.stdout.write(f"{prefix}{connector}{item_name}\n")

                # Recurse into subgroup
                subgroup = group[item_name]
                new_prefix = prefix + ("    " if is_last else "│   ")
                self._build_tree(subgroup, new_prefix, max_depth, current_depth + 1)
            else:
                # It's an array
                arr = group[item_name]
                shape_str = str(arr.shape)
                dtype_str = str(arr.dtype)
                sys.stdout.write(
                    f"{prefix}{connector}{item_name} {shape_str} {dtype_str}\n"
                )

    def group_exists(self, group_name: str, branch: str = "main") -> bool:
        """
        Check if a group exists.

        Parameters
        ----------
        group_name : str
            Name of the group to check. May be a nested path (e.g. VOD's
            ``"{calculator}/{analysis_name}"``), not just a top-level name.
        branch : str, default "main"
            Repository branch to examine.

        Returns
        -------
        bool
            True if the group exists, False otherwise.

        Notes
        -----
        Checks membership directly against the opened root group rather
        than via :meth:`get_group_names`/:meth:`list_groups` -- those only
        enumerate *top-level* Zarr group keys (``root.group_keys()``), so
        for a nested ``group_name`` like a VOD analysis group, membership
        in that flat list is always ``False`` even when the group exists.
        Confirmed 2026-07-21: this previously caused every VOD write after
        a group's first to take the ``mode="w"`` (full overwrite) branch in
        :meth:`write_or_append_vod_group` instead of appending, silently
        destroying all previously-written VOD data on each subsequent
        write. Zarr's ``Group.__contains__`` supports slash-separated
        nested paths directly, so this works for both flat GNSS receiver
        names (no behavior change there) and nested VOD group names (the
        actual fix).
        """
        try:
            with self.readonly_session(branch) as session:
                root = zarr.open_group(session.store, mode="r")
                exists = group_name in root
        except Exception:
            exists = False

        self._logger.debug(
            f"Group '{group_name}' exists on branch '{branch}': {exists}"
        )
        return exists

    def preprocessing_records(
        self,
        group_name: str,
        start: np.datetime64 | None = None,
        end: np.datetime64 | None = None,
        branch: str = "main",
    ) -> list[str]:
        """Preprocessing records in ``group_name``'s log book, without repeats.

        In ingest order; rows written before the record existed give ``""``.
        Each file row's record includes the steps of the group-wide rows
        written after it (:meth:`add_group_variables`): it describes the
        data as they are now.
        With ``start`` and ``end``, only rows whose data overlap that range,
        without rows of files skipped as already ingested (as
        :meth:`source_file_hashes`). A group without a log book gives none.
        """
        try:
            with self.readonly_session(branch) as session:
                df = self.load_metadata(session.store, group_name)
        except KeyError, zarr.errors.GroupNotFoundError:
            return []
        df = _effective_preprocessing(df, vod=self.store_type == "vod_store")
        if start is not None and end is not None:
            df = _written_rows_overlapping(df, start, end)
        if df.is_empty():
            return []
        if "preprocessing" not in df.columns:
            return [""]
        return list(dict.fromkeys(df.sort("index")["preprocessing"].to_list()))

    def check_preprocessing_matches(
        self, group_name: str, dataset: xr.Dataset, branch: str = "main"
    ) -> None:
        """Refuse data preprocessed differently from the data in ``group_name``.

        Compares the operations and settings of the record ``dataset``
        carries (:data:`~canvod.config.models.PREPROCESSING_ATTR`; none
        counts as no preprocessing) with every record in the group's log
        book. The results of the operations (e.g. the input sampling) may
        differ. In a VOD store, the records are those of the GNSS data
        behind each result (``vod_preprocessing_record``).

        Parameters
        ----------
        group_name : str
            Store group about to receive ``dataset``.
        dataset : xr.Dataset
            Data to write.
        branch : str, default "main"
            Repository branch to examine.

        Raises
        ------
        PreprocessingMismatchError
            If the group holds data preprocessed differently.
        """
        _, new = split_preprocessing(dataset.attrs)
        self.check_settings_match(
            group_name, self._settings_of(new), "the new data have", branch
        )

    def check_settings_match(
        self,
        group_name: str,
        settings: list[dict[str, Any]],
        source: str = "this run has",
        branch: str = "main",
    ) -> None:
        """Refuse preprocessing settings unlike those of the data in ``group_name``.

        Lets a run compare its configured preprocessing (see
        ``canvod.ops.planned_settings``) with a group before it processes
        any data; :meth:`check_preprocessing_matches` applies the same
        comparison to a dataset at write time. A group that does not exist
        yet accepts any settings.

        Parameters
        ----------
        group_name : str
            Store group the data will be written to.
        settings : list[dict]
            Operations and settings, as
            ``canvod.config.models.preprocessing_settings`` gives them.
        source : str, default "this run has"
            Names the new data in the error message.
        branch : str, default "main"
            Repository branch to examine.

        Raises
        ------
        PreprocessingMismatchError
            If the group holds data preprocessed differently.
        """
        for stored in self.preprocessing_records(group_name, branch=branch):
            if self._settings_of(stored) != settings:
                msg = (
                    f"Group '{group_name}' in {self.store_path} holds data "
                    f"with preprocessing {_describe(stored, self._settings_of)}, "
                    f"but {source} {describe_settings(settings)}. One group "
                    "must not mix both: restore the previous "
                    "processing.preprocessing setting, or write to a new store."
                )
                raise PreprocessingMismatchError(msg)

    def _settings_of(self, record: str) -> list[dict[str, Any]]:
        """Operations and settings of a record of this store's type."""
        if self.store_type == "vod_store":
            return vod_preprocessing_settings(record)
        return preprocessing_settings(record)

    def add_group_variables(
        self,
        group_name: str,
        variables: xr.Dataset,
        step: dict[str, Any],
        software: dict[str, str],
        branch: str = "main",
    ) -> str:
        """Add variables computed from the data already in a group.

        For example the grid cells of every observation
        (``canvod.ops.assign_grid_cells_in_store``). Only the new variables are
        written; the group's other variables, its log book and its other
        subgroups stay as they are. The write is staged on a temporary
        branch and moved to ``branch`` with :meth:`promote_branch`.

        The log book receives one group-wide row (:data:`GROUP_WIDE_ACTION`)
        whose preprocessing record holds ``step``. From then on, the
        preprocessing of the data already in the group counts as their own
        plus ``step`` (:meth:`preprocessing_records`), so a later write is
        accepted only if it was preprocessed with ``step`` as well, and
        thus carries the new variables too.

        Parameters
        ----------
        group_name : str
            Store group, e.g. ``"canopy_01"`` or a VOD analysis group.
        variables : xr.Dataset
            The new variables, with the group's dimensions and coordinate
            values (all of its epochs and signals, in the same order).
        step : dict
            The operation that computed them, as a preprocessing step
            ``{"op", "settings", "result"}`` (``canvod.ops.OpResult.step``).
        software : dict[str, str]
            Version of each package whose code computed them.
        branch : str, default "main"
            Branch to change.

        Returns
        -------
        str
            The new tip of ``branch``.

        Raises
        ------
        ValueError
            If the group does not exist, already has one of the variables,
            or ``variables`` do not match its dimensions and coordinates; or
            if the temporary branch already exists.
        BranchMovedError
            If ``branch`` moved meanwhile; the work stays on the temporary
            branch.
        """
        if not self.group_exists(group_name, branch):
            raise ValueError(f"Group '{group_name}' does not exist on '{branch}'")
        with self.readonly_session(branch) as session:
            existing = xr.open_zarr(session.store, group=group_name, consolidated=False)
        new_names = [str(name) for name in variables.data_vars]
        if not new_names:
            raise ValueError("No variables to add")
        present = sorted(set(new_names) & {str(v) for v in existing.variables})
        if present:
            raise ValueError(
                f"Group '{group_name}' already has {present}; they are not replaced."
            )
        for dim in variables.dims:
            if dim not in existing.dims:
                raise ValueError(f"Group '{group_name}' has no dimension '{dim}'")
            if variables.sizes[dim] != existing.sizes[dim] or (
                dim in variables.coords
                and not np.array_equal(variables[dim].values, existing[dim].values)
            ):
                raise ValueError(
                    f"The new variables do not cover the {dim!r} values of group "
                    f"'{group_name}' exactly (all of them, in the same order)"
                )

        to_write = variables.drop_vars(list(variables.coords))
        for name in new_names:
            to_write[name].encoding.clear()
            template = next(
                (
                    existing[v]
                    for v in existing.data_vars
                    if existing[v].dims == to_write[name].dims
                ),
                None,
            )
            if template is not None and "chunks" in template.encoding:
                chunks = template.encoding["chunks"]
                # Variables computed from read_group carry its dask chunks;
                # each must lie within one zarr chunk of the group.
                to_write[name] = to_write[name].chunk(
                    dict(zip(to_write[name].dims, chunks, strict=True))
                )
                to_write[name].encoding["chunks"] = chunks

        tip = self.repo.lookup_branch(branch)
        temp_branch = f"add_variables_{group_name.replace('/', '__')}"
        if temp_branch in self.repo.list_branches():
            raise ValueError(
                f"Temporary branch '{temp_branch}' already exists (e.g. from an "
                "earlier call that could not be promoted). Inspect it, then "
                "delete it with delete_branch()."
            )
        self.repo.create_branch(temp_branch, tip)

        commit_message = _with_run_id(
            f"Added {', '.join(new_names)} to {group_name} ({step['op']})"
        )
        session = self.repo.writable_session(temp_branch)
        self._to_icechunk_throttled(to_write, session, group=group_name, mode="a")
        self._append_metadata_row(
            zroot=zarr.open_group(session.store, mode="a"),
            group_name=group_name,
            rinex_hash="",
            start=np.datetime64("NaT", "ns"),
            end=np.datetime64("NaT", "ns"),
            snapshot_id="",
            action=GROUP_WIDE_ACTION,
            commit_msg=commit_message,
            dataset_attrs={
                PREPROCESSING_ATTR: preprocessing_record([step], software),
                "variables": new_names,
            },
        )
        commit_with_rebase(
            session, commit_message, store_path=self.store_path, config=self.settings
        )
        new_tip = self.promote_branch(temp_branch, branch, tip)
        self.repo.delete_branch(temp_branch)
        return new_tip

    def read_group(
        self,
        group_name: str,
        branch: str = "main",
        time_slice: slice | None = None,
        date: str | None = None,
        chunks: dict[str, Any] | None = None,
    ) -> xr.Dataset:
        """
        Read data from a group.

        Parameters
        ----------
        group_name : str
            Name of the group to read.
        branch : str, default "main"
            Repository branch.
        time_slice : slice | None, optional
            Optional label-based time slice for filtering (passed to ``ds.sel``).
        date : str | None, optional
            YYYYDOY string (e.g. ``"2025001"``) selecting a single calendar day.
            Converted to a ``time_slice``; mutually exclusive with ``time_slice``.
        chunks : dict[str, Any] | None, optional
            Dask chunks for reading. If None, the chunks stored in the group.

        Returns
        -------
        xr.Dataset
            Dataset from the group.
        """
        self._logger.info(f"Reading group '{group_name}' from branch '{branch}'")

        if date is not None:
            from canvod.utils.tools.date_utils import YYYYDOY

            _d = YYYYDOY.from_str(date).date
            time_slice = slice(str(_d), str(_d + timedelta(days=1)))

        with self.readonly_session(branch) as session:
            # The stored chunks, not chunk_strategy: a group keeps the chunks
            # it was written with, which the settings may no longer match.
            ds = xr.open_zarr(
                session.store,
                group=group_name,
                chunks={} if chunks is None else chunks,
                consolidated=False,
            )

            if time_slice is not None:
                ds = ds.sel(epoch=time_slice)
                self._logger.debug(f"Applied time slice: {time_slice}")

            self._logger.info(
                f"Successfully read group '{group_name}' - shape: {dict(ds.sizes)}"
            )
            return ds

    def read_group_deduplicated(
        self,
        group_name: str,
        branch: str = "main",
        keep: str = "last",
        time_slice: slice | None = None,
        chunks: dict[str, Any] | None = None,
    ) -> xr.Dataset:
        """
        Read data from a group with automatic deduplication.

        This method calls read_group() then removes duplicates using metadata table
        intelligence when available, falling back to simple epoch deduplication.

        Parameters
        ----------
        group_name : str
            Name of the group to read.
        branch : str, default "main"
            Repository branch.
        keep : str, default "last"
            Deduplication strategy for duplicate epochs.
        time_slice : slice | None, optional
            Optional time slice for filtering.
        chunks : dict[str, Any] | None, optional
            Chunking specification (uses config defaults if None).

        Returns
        -------
        xr.Dataset
            Dataset with duplicates removed (latest data only).
        """

        if keep not in ["last"]:
            raise ValueError("Currently only 'last' is supported for keep parameter.")

        self._logger.info(f"Reading group '{group_name}' with deduplication")

        # First, read the raw data
        ds = self.read_group(
            group_name, branch=branch, time_slice=time_slice, chunks=chunks
        )

        # Then deduplicate using metadata table intelligence
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]

                # Load metadata and get latest entries for each time range
                data = {col: zmeta[col][:] for col in zmeta.array_keys()}
                df = pl.DataFrame(data)

                # Ensure datetime dtypes
                df = df.with_columns(
                    [
                        pl.col("start").cast(pl.Datetime("ns")),
                        pl.col("end").cast(pl.Datetime("ns")),
                    ]
                )

                # Get latest entry for each unique (start, end) combination
                latest_entries = df.sort("written_at").unique(
                    subset=["start", "end"], keep=keep
                )

                if latest_entries.height > 0:
                    # Create time masks for latest data only
                    time_masks = []
                    for row in latest_entries.iter_rows(named=True):
                        start_time = np.datetime64(row["start"], "ns")
                        end_time = np.datetime64(row["end"], "ns")
                        mask = (ds.epoch >= start_time) & (ds.epoch <= end_time)
                        time_masks.append(mask)

                    # Combine all masks with OR logic
                    if time_masks:
                        combined_mask = time_masks[0]
                        for mask in time_masks[1:]:
                            combined_mask = combined_mask | mask
                        ds = ds.isel(epoch=combined_mask)

                        self._logger.info(
                            "Deduplicated using metadata table: kept "
                            f"{len(latest_entries)} time ranges"
                        )

            except Exception as e:
                # Fall back to simple deduplication
                self._logger.warning(
                    f"Metadata-based deduplication failed, using simple approach: {e}"
                )
                ds = ds.drop_duplicates("epoch", keep="last")
                self._logger.info("Applied simple epoch deduplication (keep='last')")

        return ds

    def _cleanse_dataset_attrs(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove any attributes that might interfere with Icechunk storage."""

        attrs_to_remove = [
            "Created",
            "File Path",
            "File Type",
            "Date",
            "institution",
            "Time of First Observation",
            "GLONASS COD",
            "GLONASS PHS",
            "GLONASS BIS",
            "Leap Seconds",
        ]
        for attr in attrs_to_remove:
            if attr in dataset.attrs:
                del dataset.attrs[attr]
        return dataset

    def write_dataset(
        self,
        dataset: xr.Dataset,
        group_name: str,
        session: Any,
        mode: str = "a",
        chunks: dict[str, int] | None = None,
    ) -> None:
        """
        Write a dataset to Icechunk with proper chunking.

        Parameters
        ----------
        dataset : xr.Dataset
            Dataset to write
        group_name : str
            Group path in store
        session : Any
            Active writable session or store handle.
        mode : str
            Write mode: 'w' (overwrite) or 'a' (append)
        chunks : dict[str, int] | None
            Chunking spec. If None, uses store's chunk_strategy.
            Example: {'epoch': 17280, 'sid': -1}
        """
        # Use explicit chunks, or fall back to store's chunk strategy
        if chunks is None:
            chunks = self.chunk_strategy

        # Apply chunking if strategy defined
        if chunks:
            dataset = dataset.chunk(chunks)
            self._logger.info(f"Rechunked to {dict(dataset.chunks)} before write")

        # Normalize encodings
        dataset = self._normalize_encodings(dataset)

        # Calculate dataset metrics for tracing
        dataset_size_mb = dataset.nbytes / 1024 / 1024
        num_variables = len(dataset.data_vars)

        # Write to Icechunk, timed via the lightweight stage_timer (see
        # canvod.utils.logging.stage_timer) -- replaces the removed
        # OpenTelemetry-based telemetry.py, which required an optional
        # dependency that was never actually installed.
        with stage_timer(
            "icechunk.write",
            group=group_name,
            size_mb=round(dataset_size_mb, 2),
            num_variables=num_variables,
        ):
            self._to_icechunk_throttled(dataset, session, group=group_name, mode=mode)

        self._logger.info(f"Wrote dataset to group '{group_name}' (mode={mode})")

    def write_initial_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        branch: str = "main",
        commit_message: str | None = None,
    ) -> None:
        """Write initial data to a new group."""
        if self.group_exists(group_name, branch):
            raise ValueError(
                f"Group '{group_name}' already exists. Use append_to_group() instead."
            )

        dataset = self._normalize_encodings(dataset)

        rinex_hash = dataset.attrs.get("File Hash")
        if rinex_hash is None:
            raise ValueError("Dataset missing 'File Hash' attribute")
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        if commit_message is None:
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Initial commit to group '{group_name}'"

        dataset, encoding = self._for_group_creation(dataset)
        with self.writable_session(branch) as session:
            self._to_icechunk_throttled(
                dataset, session, group=group_name, mode="w", encoding=encoding
            )
            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action="write",
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            commit_with_rebase(
                session,
                _with_run_id(commit_message),
                store_path=self.store_path,
                config=self.settings,
            )

        self._logger.info(
            f"Created group '{group_name}' with {len(dataset.epoch)} epochs, "
            f"hash={rinex_hash}"
        )

    def backup_metadata_table(
        self,
        group_name: str,
        session: Any,
    ) -> pl.DataFrame | None:
        """Backup the metadata table to a Polars DataFrame.

        Parameters
        ----------
        group_name : str
            Group name.
        session : Any
            Active session for reading.

        Returns
        -------
        pl.DataFrame | None
            DataFrame with metadata rows, or None if missing.

        Raises
        ------
        RuntimeError
            If the table exists but cannot be read.
        """
        try:
            zroot = zarr.open_group(session.store, mode="r")
            meta_group_path = f"{group_name}/metadata/table"

            if (
                "metadata" not in zroot[group_name]
                or "table" not in zroot[group_name]["metadata"]
            ):
                self._logger.info(
                    "No metadata table found for group "
                    f"'{group_name}' - nothing to backup"
                )
                return None

            zmeta = zroot[meta_group_path]

            # Load all columns into a dictionary
            data = {}
            for col_name in zmeta.array_keys():
                data[col_name] = zmeta[col_name][:]

            # Convert to Polars DataFrame
            df = pl.DataFrame(data)

            self._logger.info(
                "Backed up metadata table with "
                f"{df.height} rows for group '{group_name}'"
            )
            return df

        except Exception as e:
            # Raise: a rewrite would otherwise delete the log book unnoticed
            raise RuntimeError(
                f"Could not back up the metadata table of group '{group_name}': {e}"
            ) from e

    def restore_metadata_table(
        self,
        group_name: str,
        df: pl.DataFrame,
        session: Any,
    ) -> None:
        """Restore the metadata table from a Polars DataFrame.

        This recreates the full Zarr structure for the metadata table.

        Parameters
        ----------
        group_name : str
            Group name.
        df : pl.DataFrame
            Metadata table to restore.
        session : Any
            Active session for writing.

        Returns
        -------
        None
        """
        if df is None or df.height == 0:
            self._logger.info(f"No metadata to restore for group '{group_name}'")
            return

        try:
            zroot = zarr.open_group(session.store, mode="a")
            meta_group_path = f"{group_name}/metadata/table"

            # Create the metadata subgroup
            zmeta = zroot.require_group(meta_group_path)

            # Create all arrays from the DataFrame
            for col_name in df.columns:
                col_data = df[col_name]

                if col_name == "index":
                    # Index column as int64
                    arr = col_data.to_numpy().astype("i8")
                    dtype = "i8"
                elif col_name in ("start", "end"):
                    # Datetime columns
                    arr = col_data.to_numpy().astype("datetime64[ns]")
                    dtype = "M8[ns]"
                else:
                    # String columns - use VariableLengthUTF8
                    arr = col_data.to_list()  # Convert to list for VariableLengthUTF8
                    dtype = VariableLengthUTF8()

                # Create the array
                zmeta.create_array(
                    name=col_name,
                    shape=(len(arr),),
                    dtype=dtype,
                    chunks=(1024,),
                    overwrite=True,
                )

                # Write the data
                zmeta[col_name][:] = arr

            self._logger.info(
                "Restored metadata table with "
                f"{df.height} rows for group '{group_name}'"
            )

        except Exception as e:
            self._logger.error(
                f"Failed to restore metadata table for group '{group_name}': {e}"
            )
            raise RuntimeError(
                f"Critical error: could not restore metadata table: {e}"
            ) from e

    def rewrite_group(
        self,
        session: Any,
        group_name: str,
        dataset: xr.Dataset,
        drop_ranges: Sequence[tuple[np.datetime64, np.datetime64]],
        metadata_parts: dict[str, list[xr.Dataset]] | None = None,
    ) -> None:
        """Rewrite *group_name* with *dataset* and keep its ``metadata/``.

        A ``mode="w"`` write deletes the group's subgroups. The log book
        comes back unchanged; every other metadata dataset (e.g. ``sbf_obs``)
        comes back from the session's base snapshot without its epochs
        inside *drop_ranges* (the replaced data), merged in epoch order with
        the datasets in *metadata_parts* (name -> per-file datasets). A
        metadata dataset left without epochs is not written back. Writes
        into *session* without committing.
        """
        path = f"{group_name}/metadata"
        table = self.backup_metadata_table(group_name, session)
        base = self.repo.readonly_session(snapshot_id=session.snapshot_id)
        stored_meta = zarr.open_group(base.store, mode="r").get(path)
        stored_names = (
            set(stored_meta.group_keys()) - {"table"}
            if stored_meta is not None
            else set()
        )
        parts = metadata_parts or {}

        self._to_icechunk_throttled(
            self._normalize_encodings(dataset), session, group=group_name, mode="w"
        )
        if table is not None:
            self.restore_metadata_table(group_name, table, session)

        for name in sorted(stored_names | set(parts)):
            datasets = [
                self._cleanse_dataset_attrs(self._normalize_encodings(part))
                for part in parts.get(name, [])
            ]
            if name in stored_names:
                stored = xr.open_zarr(
                    base.store, group=f"{path}/{name}", consolidated=False
                )
                if "epoch" in stored.dims:
                    epochs = stored["epoch"].values
                    keep = np.ones(epochs.size, dtype=bool)
                    for start, end in drop_ranges:
                        keep &= (epochs < start) | (epochs > end)
                    stored = stored.isel(epoch=keep)
                if stored.sizes.get("epoch", 1) > 0:
                    datasets.insert(0, stored)
            if not datasets:
                continue
            rewrite = (
                xr.concat(datasets, dim="epoch", combine_attrs="override").sortby(
                    "epoch"
                )
                if len(datasets) > 1
                else datasets[0]
            )
            self._to_icechunk_throttled(
                self._normalize_encodings(rewrite),
                session,
                group=f"{path}/{name}",
                mode="w",
            )

    def overwrite_file_in_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
        commit_message: str | None = None,
    ) -> None:
        """Overwrite a file's contribution to the group (same hash, new epoch range).

        The group's epochs outside ``[start, end]`` and ``dataset`` are merged
        and rewritten in epoch order, so ``epoch`` stays monotonic when the
        replaced range lies before the latest stored data. The log book and
        the other metadata datasets are kept (:meth:`rewrite_group`).
        """

        dataset = self._normalize_encodings(dataset)

        # --- Step 3: rewrite store ---
        with self.writable_session(branch) as session:
            ds_from_store = xr.open_zarr(
                session.store, group=group_name, consolidated=False
            ).compute(
                scheduler="synchronous"
            )  # synchronous avoids Dask serialization error

            mask = (ds_from_store.epoch.values < start) | (
                ds_from_store.epoch.values > end
            )
            ds_rewrite = xr.concat(
                [ds_from_store.isel(epoch=mask), dataset],
                dim="epoch",
                combine_attrs="override",
            ).sortby("epoch")
            self.rewrite_group(session, group_name, ds_rewrite, [(start, end)])

            if commit_message is None:
                version = get_version_from_pyproject()
                commit_message = (
                    f"[v{version}] Overwrote file {rinex_hash} in group '{group_name}'"
                )
            commit_message = _with_run_id(commit_message)

            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action="overwrite",
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            commit_with_rebase(
                session,
                commit_message,
                store_path=self.store_path,
                config=self.settings,
            )

    def get_group_info(self, group_name: str, branch: str = "main") -> dict[str, Any]:
        """
        Get metadata about a group.

        Parameters
        ----------
        group_name : str
            Name of the group.
        branch : str, default "main"
            Repository branch to examine.

        Returns
        -------
        dict[str, Any]
            Group metadata.

        Raises
        ------
        ValueError
            If the group does not exist.
        """
        if not self.group_exists(group_name, branch):
            raise ValueError(f"Group '{group_name}' does not exist")

        ds = self.read_group(group_name, branch)

        info = {
            "group_name": group_name,
            "store_type": self.store_type,
            "dimensions": dict(ds.sizes),
            "variables": list(ds.data_vars.keys()),
            "coordinates": list(ds.coords.keys()),
            "attributes": dict(ds.attrs),
        }

        # Add temporal information if epoch dimension exists
        if "epoch" in ds.sizes:
            info["temporal_info"] = {
                "start": str(ds.epoch.min().values),
                "end": str(ds.epoch.max().values),
                "count": ds.sizes["epoch"],
                **_cadence_info(ds.epoch.values),
            }

        return info

    # ── Generic metadata datasets ─────────────────────────────────────────────

    def metadata_dataset_exists(
        self, group_name: str, name: str, branch: str = "main"
    ) -> bool:
        """Return True if a metadata dataset *name* exists for *group_name*."""
        try:
            session = self.repo.readonly_session(branch)
            root = zarr.open_group(session.store, mode="r")
            meta = root.get(f"{group_name}/metadata", None)
            return meta is not None and name in meta
        except Exception:
            return False

    def write_metadata_dataset(
        self,
        meta_ds: xr.Dataset,
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> str:
        """Write a pre-concatenated metadata dataset to *{group_name}/metadata/{name}*.

        Always writes with ``mode="w"`` (full overwrite for the day).

        Parameters
        ----------
        meta_ds : xr.Dataset
            Pre-concatenated ``(epoch, sid)`` metadata dataset.
        group_name : str
            Target group (receiver name).
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch to write to.

        Returns
        -------
        str
            Icechunk snapshot ID.
        """
        version = get_version_from_pyproject()
        path = f"{group_name}/metadata/{name}"
        ds = self._normalize_encodings(meta_ds)
        ds = self._cleanse_dataset_attrs(ds)
        with self.writable_session(branch) as session:
            self._to_icechunk_throttled(ds, session, group=path, mode="w")
            return commit_with_rebase(
                session,
                _with_run_id(f"[v{version}] metadata/{name} for {group_name}"),
                store_path=self.store_path,
                config=self.settings,
            )

    def write_metadata_parts(
        self,
        parts: list[xr.Dataset],
        group_name: str,
        name: str,
        session: Any,
    ) -> int:
        """Add per-file metadata datasets to *{group_name}/metadata/{name}*.

        Writes into *session* without committing, so the caller commits the
        metadata together with the observations it belongs to. Creates the
        dataset if it does not exist yet, otherwise appends along ``epoch``.

        Parameters
        ----------
        parts : list[xr.Dataset]
            Per-file metadata datasets with an ``epoch`` dim, one per file
            whose observations are written in the same session.
        group_name : str
            Target group (the observations' store group).
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        session : Session or ForkSession
            Open writable session of the observations' write.

        Returns
        -------
        int
            Number of epochs written.
        """
        if not parts:
            msg = "parts list is empty"
            raise ValueError(msg)

        path = f"{group_name}/metadata/{name}"
        clean = [
            self._cleanse_dataset_attrs(self._normalize_encodings(part))
            for part in parts
        ]
        exists = zarr.open_group(session.store, mode="r").get(path) is not None
        for i, part in enumerate(clean):
            if i == 0 and not exists:
                self._to_icechunk_throttled(part, session, group=path, mode="w")
            else:
                self._to_icechunk_throttled(
                    part, session, group=path, append_dim="epoch"
                )
        return sum(part.sizes.get("epoch", 0) for part in clean)

    def append_metadata_datasets(
        self,
        parts: list[xr.Dataset],
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> str:
        """Append metadata datasets in their own commit: no in-memory concat.

        Creates *{group_name}/metadata/{name}* if it does not exist yet,
        otherwise appends along ``epoch``. Prefer
        :meth:`write_metadata_parts` inside the session that writes the
        observations, so both land in one commit.

        Parameters
        ----------
        parts : list[xr.Dataset]
            Individual per-file metadata datasets with an ``epoch`` dim.
        group_name : str
            Target group (receiver name).
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch to write to.

        Returns
        -------
        str
            Icechunk snapshot ID.
        """
        version = get_version_from_pyproject()
        with self.writable_session(branch) as session:
            total_epochs = self.write_metadata_parts(parts, group_name, name, session)
            return commit_with_rebase(
                session,
                _with_run_id(
                    f"[v{version}] metadata/{name} for {group_name} "
                    f"({total_epochs} epochs)"
                ),
                store_path=self.store_path,
                config=self.settings,
            )

    def read_metadata_dataset(
        self,
        group_name: str,
        name: str,
        branch: str = "main",
        chunks: dict | None = None,
    ) -> xr.Dataset:
        """Read a metadata dataset *name* for *group_name*.

        Parameters
        ----------
        group_name : str
            Group (receiver) name.
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch.
        chunks : dict | None, optional
            Dask chunks for reading. If None, the chunks stored in the
            dataset.

        Returns
        -------
        xr.Dataset
            Lazy ``(epoch, sid)`` metadata dataset.
        """
        path = f"{group_name}/metadata/{name}"
        with self.readonly_session(branch) as session:
            return xr.open_zarr(
                session.store,
                group=path,
                chunks={} if chunks is None else chunks,
                consolidated=False,
            )

    def get_metadata_dataset_info(
        self,
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Get info about metadata dataset *name* for *group_name*.

        Parameters
        ----------
        group_name : str
            Group (receiver) name.
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch.

        Returns
        -------
        dict[str, Any]
            Info dict with the same structure as ``get_group_info()``.

        Raises
        ------
        ValueError
            If the metadata dataset does not exist.
        """
        if not self.metadata_dataset_exists(group_name, name, branch):
            raise ValueError(f"No metadata dataset '{name}' for group '{group_name}'")
        ds = self.read_metadata_dataset(group_name, name, branch, chunks={})
        info: dict[str, Any] = {
            "group_name": group_name,
            "store_path": f"{group_name}/metadata/{name}",
            "store_type": f"metadata/{name}",
            "dimensions": dict(ds.sizes),
            "variables": list(ds.data_vars.keys()),
            "coordinates": list(ds.coords.keys()),
            "attributes": dict(ds.attrs),
        }
        if "epoch" in ds.sizes:
            info["temporal_info"] = {
                "start": str(ds.epoch.min().values),
                "end": str(ds.epoch.max().values),
                "count": ds.sizes["epoch"],
                **_cadence_info(ds.epoch.values),
            }
        return info

    # Convenience aliases (SBF)
    def sbf_metadata_exists(self, group_name: str, branch: str = "main") -> bool:
        """Return True if an SBF metadata dataset exists for *group_name*."""
        return self.metadata_dataset_exists(group_name, "sbf_obs", branch)

    def write_sbf_metadata(
        self, meta_ds: xr.Dataset, group_name: str, branch: str = "main"
    ) -> str:
        """Write SBF metadata dataset."""
        return self.write_metadata_dataset(meta_ds, group_name, "sbf_obs", branch)

    def read_sbf_metadata(
        self, group_name: str, branch: str = "main", chunks: dict | None = None
    ) -> xr.Dataset:
        """Read SBF metadata dataset."""
        return self.read_metadata_dataset(group_name, "sbf_obs", branch, chunks)

    def get_sbf_metadata_info(
        self, group_name: str, branch: str = "main"
    ) -> dict[str, Any]:
        """Get SBF metadata info."""
        return self.get_metadata_dataset_info(group_name, "sbf_obs", branch)

    def rel_path_for_commit(self, file_path: Path) -> str:
        """
        Generate relative path for commit messages.

        Parameters
        ----------
        file_path : Path
            Full file path.

        Returns
        -------
        str
            Relative path string with log_path_depth parts.
        """
        return str(Path(*file_path.parts[-self._log_path_depth :]))

    def get_store_stats(self) -> dict[str, Any]:
        """
        Get statistics about the store.

        Returns
        -------
        dict[str, Any]
            Store statistics.
        """
        groups = self.get_group_names()
        # groups maps branch name -> list of group names (e.g. {"main": ["canopy_01"]});
        # flatten + dedup to count distinct groups rather than branches.
        all_group_names = {name for names in groups.values() for name in names}
        stats = {
            "store_path": str(self.store_path),
            "store_type": self.store_type,
            "compression_level": self.compression_level,
            # icechunk v2's CompressionAlgorithm has no .name attribute
            # (PyO3 enum wrapper, unlike Python's enum.Enum): str() gives
            # "CompressionAlgorithm.Zstd"; take the part after the dot.
            "compression_algorithm": str(self.compression_algorithm).rsplit(".", 1)[-1],
            "total_groups": len(all_group_names),
            "groups": groups,
        }

        # Add group-specific stats (from "main": get_group_info()'s default branch)
        for group_name in groups.get("main", []):
            try:
                info = self.get_group_info(group_name)
                stats[f"group_{group_name}"] = {
                    "dimensions": info["dimensions"],
                    "variables_count": len(info["variables"]),
                    "has_temporal_data": "temporal_info" in info,
                }
            except Exception as e:
                self._logger.warning(
                    f"Failed to get stats for group '{group_name}': {e}"
                )

        return stats

    def append_to_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        action: str = "write",
        commit_message: str | None = None,
    ) -> None:
        """Append data to an existing group."""
        if not self.group_exists(group_name, branch):
            raise ValueError(
                f"Group '{group_name}' does not exist. Use write_initial_group() first."
            )

        dataset = self._normalize_encodings(dataset)

        rinex_hash = dataset.attrs.get("File Hash")
        if rinex_hash is None:
            raise ValueError("Dataset missing 'File Hash' attribute")
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        # Guard: check hash + temporal overlap before appending
        exists, matches = self.metadata_row_exists(
            group_name, rinex_hash, start, end, branch
        )
        if exists and action != "overwrite":
            self._logger.warning(
                "append_blocked_by_guardrail",
                group=group_name,
                hash=rinex_hash[:16],
                range=f"{start} → {end}",
                reason="hash_or_temporal_overlap",
                matching_files=matches.height if not matches.is_empty() else 0,
            )
            return

        if commit_message is None and action == "write":
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Wrote to group '{group_name}'"
        elif commit_message is None and action == "append":
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Appended to group '{group_name}'"
        elif commit_message is None:
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] {action} to group '{group_name}'"

        with self.writable_session(branch) as session:
            self._to_icechunk_throttled(
                dataset, session, group=group_name, append_dim=append_dim
            )
            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action=action,
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            commit_with_rebase(
                session,
                _with_run_id(commit_message),
                store_path=self.store_path,
                config=self.settings,
            )

        if action == "append":
            self._logger.info(
                f"Appended {len(dataset.epoch)} epochs to group '{group_name}', "
                f"hash={rinex_hash}"
            )
        elif action == "write":
            self._logger.info(
                f"Wrote {len(dataset.epoch)} epochs to group '{group_name}', "
                f"hash={rinex_hash}"
            )
        else:
            self._logger.info(
                f"Action '{action}' completed for group '{group_name}', "
                f"hash={rinex_hash}"
            )

    def write_or_append_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        commit_message: str | None = None,
        dedup: bool = False,
        metadata_datasets: dict[str, xr.Dataset] | None = None,
    ) -> bool:
        """Write or append a dataset to a group.

        By default (``dedup=False``) no guardrails are applied — suitable for
        VOD stores and other derived-data stores where rinex-style dedup does
        not apply.

        When ``dedup=True`` the method runs a full hash-match + temporal-overlap
        check (via :meth:`should_skip_file`) **before** opening a write session.
        This makes the store the authoritative final gate for RINEX/SBF ingest
        paths, backstopping any pre-checks in the caller.

        If the group does not exist, creates it (``mode='w'``).
        If it exists, appends along ``append_dim``.

        Parameters
        ----------
        dataset : xr.Dataset
            Dataset to write or append.
        group_name : str
            Target Icechunk group.
        append_dim : str, default "epoch"
            Dimension along which to append when the group already exists.
        branch : str, default "main"
            Icechunk branch to write to.
        commit_message : str or None
            Commit message.  Auto-generated if ``None``.
        dedup : bool, default False
            When ``True``, check for duplicate hash or temporal overlap before
            writing.  If the dataset would be a duplicate, the write is skipped,
            a warning is logged, and ``False`` is returned.  Set to ``True`` for
            RINEX/SBF ingest; leave ``False`` for VOD and derived-data stores.
        metadata_datasets : dict[str, xr.Dataset] or None
            Per-file metadata datasets (e.g. ``{"sbf_obs": meta_ds}``) added
            to ``{group_name}/metadata/<name>`` in the same commit as
            *dataset*, see :meth:`write_metadata_parts`.

        Returns
        -------
        bool
            ``True`` if the dataset was written, ``False`` if skipped
            (only possible when ``dedup=True``).
        """
        if dedup:
            file_hash = dataset.attrs.get("File Hash")
            time_start = dataset.epoch.min().values
            time_end = dataset.epoch.max().values
            skip, reason = self.should_skip_file(
                group_name=group_name,
                file_hash=file_hash,
                time_start=time_start,
                time_end=time_end,
                branch=branch,
            )
            if skip:
                self._logger.warning(
                    "write_or_append_group skipped duplicate",
                    group=group_name,
                    reason=reason,
                    file_hash=file_hash,
                )
                return False

        self.check_preprocessing_matches(group_name, dataset, branch)
        dataset = self._normalize_encodings(dataset)

        if self.group_exists(group_name, branch):
            with self.writable_session(branch) as session:
                self._to_icechunk_throttled(
                    dataset, session, group=group_name, append_dim=append_dim
                )
                for name, meta_ds in (metadata_datasets or {}).items():
                    self.write_metadata_parts([meta_ds], group_name, name, session)
                if commit_message is None:
                    commit_message = f"Appended to group '{group_name}'"
                commit_message = _with_run_id(commit_message)
                self._log_group_write(
                    session, group_name, dataset, "append", commit_message
                )
                commit_with_rebase(
                    session,
                    commit_message,
                    store_path=self.store_path,
                    config=self.settings,
                )
            self._logger.info(
                f"Appended {len(dataset.epoch)} epochs to group '{group_name}'"
            )
        else:
            dataset, encoding = self._for_group_creation(dataset)
            with self.writable_session(branch) as session:
                self._to_icechunk_throttled(
                    dataset, session, group=group_name, mode="w", encoding=encoding
                )
                for name, meta_ds in (metadata_datasets or {}).items():
                    self.write_metadata_parts([meta_ds], group_name, name, session)
                if commit_message is None:
                    commit_message = f"Created group '{group_name}'"
                commit_message = _with_run_id(commit_message)
                self._log_group_write(
                    session, group_name, dataset, "write", commit_message
                )
                commit_with_rebase(
                    session,
                    commit_message,
                    store_path=self.store_path,
                    config=self.settings,
                )
            self._logger.info(
                f"Created group '{group_name}' with {len(dataset.epoch)} epochs"
            )
        return True

    def _log_group_write(
        self,
        session: Any,
        group_name: str,
        dataset: xr.Dataset,
        action: str,
        commit_message: str,
    ) -> None:
        """Log-book row of a :meth:`write_or_append_group` write, in its session.

        Records the file hash, epoch range, attributes and preprocessing
        record of ``dataset``, so the write is traceable and the duplicate
        check of later writes sees it.
        """
        self._append_metadata_row(
            zroot=zarr.open_group(session.store, mode="a"),
            group_name=group_name,
            rinex_hash=str(dataset.attrs.get("File Hash", "")),
            start=dataset.epoch.min().values,
            end=dataset.epoch.max().values,
            snapshot_id="",
            action=action,
            commit_msg=commit_message,
            dataset_attrs=dict(dataset.attrs),
            canonical_name=dataset.attrs.get("canonical_name"),
            physical_path=dataset.attrs.get("physical_path"),
        )

    def _append_metadata_row(
        self,
        zroot: zarr.Group,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        dataset_attrs: dict,
        canonical_name: str | None = None,
        physical_path: str | None = None,
    ) -> None:
        """Write one metadata row into an already-open zarr group (no session/commit).

        Must be called inside an active writable session or transaction so the
        caller controls the commit boundary. This is the canonical implementation;
        ``append_metadata`` is a thin standalone wrapper around it.

        Schema:
            index           int64 (continuous row id)
            rinex_hash      str   (UTF-8, VariableLengthUTF8)
            start           datetime64[ns]
            end             datetime64[ns]
            snapshot_id     str   (UTF-8; empty string when written inside a
                                  combined data+metadata commit — the commit ID
                                  is recoverable via repo.ancestry())
            action          str   (UTF-8, e.g. "write"|"append"|"overwrite")
            commit_msg      str   (UTF-8)
            written_at      str   (UTF-8, ISO8601, UTC)
            write_strategy  str   (UTF-8)
            attrs           str   (UTF-8, JSON dump of dataset attrs)
            preprocessing   str   (UTF-8, JSON preprocessing record, see
                                  ``canvod.config.models.preprocessing_record``;
                                  "" in rows written before it existed)
            canonical_name  str   (UTF-8)
            physical_path   str   (UTF-8)
        """
        dataset_attrs, record = split_preprocessing(dataset_attrs)
        written_at = datetime.now(UTC).isoformat()
        row = {
            "rinex_hash": str(rinex_hash),
            "start": _time_or_none(start),
            "end": _time_or_none(end),
            "snapshot_id": str(snapshot_id),
            "action": str(action),
            "commit_msg": str(commit_msg),
            "written_at": written_at,
            "write_strategy": str(self._gnss_store_strategy)
            if self.store_type == "gnss_store"
            else VOD_WRITE_STRATEGY,
            "attrs": json.dumps(dataset_attrs, default=str),
            "preprocessing": record,
            "canonical_name": str(canonical_name) if canonical_name else "",
            "physical_path": str(physical_path) if physical_path else "",
        }
        df_row = pl.DataFrame(
            [row],
            schema_overrides={"start": pl.Datetime("ns"), "end": pl.Datetime("ns")},
        )
        zmeta = zroot.require_group(f"{group_name}/metadata/table")
        _append_log_rows(zmeta, df_row)

    def append_metadata(
        self,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        dataset_attrs: dict,
        branch: str = "main",
        canonical_name: str | None = None,
        physical_path: str | None = None,
    ) -> None:
        """Standalone metadata-row append: commits on its own.

        For ingest paths (write_initial_group, append_to_group) use
        _append_metadata_row directly inside the data-write session to avoid
        an extra commit per file.
        """
        message = f"Appended metadata row for {group_name}, hash={rinex_hash}"
        session = self.repo.writable_session(branch)
        zroot = zarr.open_group(session.store, mode="a")
        self._append_metadata_row(
            zroot=zroot,
            group_name=group_name,
            rinex_hash=rinex_hash,
            start=start,
            end=end,
            snapshot_id=snapshot_id,
            action=action,
            commit_msg=commit_msg,
            dataset_attrs=dataset_attrs,
            canonical_name=canonical_name,
            physical_path=physical_path,
        )
        commit_with_rebase(
            session, message, store_path=self.store_path, config=self.settings
        )

        self._logger.info(
            f"Metadata appended for group '{group_name}': "
            f"hash={rinex_hash}, snapshot={snapshot_id}, action={action}"
        )

    def append_metadata_bulk(
        self,
        group_name: str,
        rows: list[dict[str, Any]],
        session: icechunk.Session | icechunk.ForkSession | None = None,
    ) -> None:
        """
        Append multiple metadata rows in one commit.

        Parameters
        ----------
        group_name : str
            Group name (e.g. "canopy", "reference")
        rows : list[dict[str, Any]]
            List of metadata records matching the schema used in
            append_metadata().
        session : icechunk.Session or icechunk.ForkSession, optional
            If provided, rows are written into this session (caller commits later).
            If None, this method opens its own writable session and commits once.
        """
        if not rows:
            self._logger.info(f"No metadata rows to append for group '{group_name}'")
            return

        # Ensure datetime conversions for consistency. Explicitly pinned to
        # "ns" (not just "any string -> datetime64", which leaves an
        # already-datetime64 value at whatever unit it arrived in, e.g. "s"
        # for a bare-string-derived epoch): mixing datetime64 units across
        # separate `pl.DataFrame()` constructions in the same process
        # triggers a polars/numpy interop bug where a later, differently-
        # shaped construction misreads a boxed `datetime.datetime` value as
        # needing `float()` coercion (confirmed 2026-07-21 with a minimal
        # repro -- `_append_vod_metadata_row` already pins to "ns" for the
        # same reason, this was the one remaining unpinned call site).
        rows = [_json_log_row(row) for row in rows]
        for row in rows:
            if row.get("start") is not None:
                row["start"] = np.datetime64(row["start"], "ns")
            if row.get("end") is not None:
                row["end"] = np.datetime64(row["end"], "ns")
            if "written_at" not in row:
                row["written_at"] = datetime.now(UTC).isoformat()

        # Prepare the Polars DataFrame
        df = pl.DataFrame(rows)

        def _do_append(session_obj: icechunk.Session | icechunk.ForkSession) -> None:
            """Append metadata rows to a writable session.

            Parameters
            ----------
            session_obj : icechunk.Session or icechunk.ForkSession
                Writable session to update.

            Returns
            -------
            None
            """
            zroot = zarr.open_group(session_obj.store, mode="a")
            meta_group_path = f"{group_name}/metadata/table"
            zmeta = zroot.require_group(meta_group_path)

            _append_log_rows(zmeta, df)

            self._logger.info(
                f"Appended {df.height} metadata rows to group '{group_name}'"
            )

        if session is not None:
            _do_append(session)
        else:
            with self.writable_session() as sess:
                _do_append(sess)
                commit_with_rebase(
                    sess,
                    _with_run_id(f"Bulk metadata append for {group_name}"),
                    store_path=self.store_path,
                    config=self.settings,
                )

    # ------------------------------------------------------------------
    # VOD store: {model}/{analysis_name} group hierarchy + dedicated ledger
    # ------------------------------------------------------------------
    #
    # A VOD computation reads from *two* receivers, so there is no single
    # "File Hash" to dedup on (unlike RINEX ingest). The methods below are
    # a parallel, VOD-shaped equivalent of should_skip_file()/
    # metadata_row_exists()/append_to_group() — same hash+temporal-overlap
    # guardrail pattern, but keyed on a combined per-receiver hash dict
    # instead of one flat rinex_hash column, and with a ledger schema that
    # also records calculator_name and per-receiver provenance
    # (source_gnss_stores).

    def _append_vod_metadata_row(
        self,
        zroot: zarr.Group,
        group_name: str,
        source_file_hashes: dict[str, str],
        source_gnss_stores: dict[str, str],
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        calculator_name: str,
        dataset_attrs: dict,
    ) -> None:
        """Write one VOD metadata row into an already-open zarr group.

        Must be called inside an active writable session so the caller
        controls the commit boundary (mirrors ``_append_metadata_row``).

        Schema:
            index               int64
            source_file_hashes  str (UTF-8, JSON dict {receiver_name: hash},
                                 sorted keys — doubles as the dedup key)
            source_gnss_stores  str (UTF-8, JSON dict {receiver_name: store_path})
            start               datetime64[ns]
            end                 datetime64[ns]
            snapshot_id         str (UTF-8)
            action              str (UTF-8, "write"|"append"|"overwrite")
            commit_msg          str (UTF-8, the message of the commit that
                                 holds the row, including its run_id)
            run_id              str (UTF-8, "" outside a run)
            written_at          str (UTF-8, ISO8601, UTC)
            write_strategy      str (UTF-8)
            calculator_name     str (UTF-8)
            attrs               str (UTF-8, JSON dump of dataset attrs)
            preprocessing       str (UTF-8, JSON {receiver_name: [records]}:
                                 the preprocessing records of the GNSS data
                                 behind the result, see
                                 ``canvod.config.models.vod_preprocessing_record``)
        """
        dataset_attrs, record = split_preprocessing(dataset_attrs)
        written_at = datetime.now(UTC).isoformat()
        row = {
            "source_file_hashes": json.dumps(source_file_hashes, sort_keys=True),
            "source_gnss_stores": json.dumps(source_gnss_stores, sort_keys=True),
            "start": _time_or_none(start),
            "end": _time_or_none(end),
            "snapshot_id": str(snapshot_id),
            "action": str(action),
            "commit_msg": str(commit_msg),
            "run_id": get_run_id() or "",
            "written_at": written_at,
            "write_strategy": VOD_WRITE_STRATEGY,
            "calculator_name": str(calculator_name),
            "attrs": json.dumps(dataset_attrs, default=str),
            "preprocessing": record,
        }
        df_row = pl.DataFrame(
            [row],
            schema_overrides={"start": pl.Datetime("ns"), "end": pl.Datetime("ns")},
        )
        zmeta = zroot.require_group(f"{group_name}/metadata/table")
        _append_log_rows(zmeta, df_row)

    def _vod_metadata_row_exists(
        self,
        group_name: str,
        source_hash_key: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, pl.DataFrame]:
        """Check whether a VOD computation already exists or overlaps temporally.

        Analogous to :meth:`metadata_row_exists`, but compares against the
        ``source_file_hashes`` column (a canonical, sorted-keys JSON string)
        instead of a single flat hash column.

        Parameters
        ----------
        group_name : str
            ``{model}/{analysis_name}`` group path.
        source_hash_key : str
            ``json.dumps(source_file_hashes, sort_keys=True)`` for the
            incoming computation.
        start, end : np.datetime64
            Epoch range of the incoming VOD dataset.
        branch : str, default "main"

        Returns
        -------
        tuple[bool, pl.DataFrame]
            ``(True, matching_rows)`` when this should be skipped,
            ``(False, empty_df)`` when it is safe to write.
        """
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
            except Exception:
                return False, pl.DataFrame()

            data = {col: zmeta[col][:] for col in zmeta.array_keys()}
            df = pl.DataFrame(data)
            df = df.with_columns(
                [
                    pl.col("start").cast(pl.Datetime("ns")),
                    pl.col("end").cast(pl.Datetime("ns")),
                ]
            )

            hash_matches = df.filter(pl.col("source_file_hashes") == source_hash_key)
            if not hash_matches.is_empty():
                return True, hash_matches

            start_ns = np.datetime64(start, "ns")
            end_ns = np.datetime64(end, "ns")
            overlaps = df.filter(
                (pl.col("start") <= end_ns) & (pl.col("end") >= start_ns)
            )
            if not overlaps.is_empty():
                self._logger.warning(
                    "vod_temporal_overlap_detected",
                    group=group_name,
                    incoming_range=f"{start} → {end}",
                    existing_range=(
                        f"{overlaps['start'].min()} → {overlaps['end'].max()}"
                    ),
                    overlapping_rows=overlaps.height,
                )
                return True, overlaps

            return False, pl.DataFrame()

    def should_skip_vod_write(
        self,
        group_name: str,
        source_file_hashes: dict[str, str],
        time_start: np.datetime64,
        time_end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, str]:
        """Check whether a VOD write should be skipped as a duplicate.

        Parameters
        ----------
        group_name : str
            ``{model}/{analysis_name}`` group path.
        source_file_hashes : dict[str, str]
            ``{receiver_name: "File Hash"}`` for every receiver the
            computation read from.
        time_start, time_end : np.datetime64
            Epoch range of the incoming VOD dataset.
        branch : str, default "main"

        Returns
        -------
        tuple[bool, str]
            ``(True, "hash_match")``, ``(True, "temporal_overlap")``, or
            ``(False, "")``.
        """
        source_hash_key = json.dumps(source_file_hashes, sort_keys=True)
        exists, matches = self._vod_metadata_row_exists(
            group_name, source_hash_key, time_start, time_end, branch
        )
        if not exists:
            return False, ""
        if (
            not matches.is_empty()
            and (matches["source_file_hashes"] == source_hash_key).any()
        ):
            return True, "hash_match"
        return True, "temporal_overlap"

    def write_or_append_vod_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        source_file_hashes: dict[str, str],
        source_gnss_stores: dict[str, str],
        calculator_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        commit_message: str | None = None,
        dedup: bool = True,
    ) -> bool:
        """Write or append a VOD analysis dataset, with its own metadata ledger.

        ``group_name`` is expected to be ``{model}/{analysis_name}`` (e.g.
        ``"tau_omega_zeroth_order/canopy_01_vs_reference_01"``): the model
        layer disambiguates results from different VOD calculators sharing
        the same analysis pair. Data write and metadata-row write happen in
        one Icechunk commit, mirroring :meth:`append_to_group`.

        Parameters
        ----------
        dataset : xr.Dataset
            Computed VOD dataset to write or append.
        group_name : str
            Target ``{model}/{analysis_name}`` group.
        source_file_hashes : dict[str, str]
            ``{receiver_name: "File Hash"}`` for every receiver the
            computation read from — the dedup key (no single hash exists
            for a two-receiver computation).
        source_gnss_stores : dict[str, str]
            ``{receiver_name: gnss_store_path}`` — provenance back to the
            GNSS store(s) the inputs came from.
        calculator_name : str
            Registered ``VODFactory`` name (e.g. ``"tau_omega"``).
        append_dim : str, default "epoch"
        branch : str, default "main"
        commit_message : str or None
            Auto-generated if ``None``.
        dedup : bool, default True
            When ``True``, skip the write if this exact source-hash
            combination was already written, or if the incoming epoch
            range temporally overlaps an existing row. Set ``False`` to
            force a write regardless (e.g. explicit overwrite/reprocessing).

        Returns
        -------
        bool
            ``True`` if written, ``False`` if skipped as a duplicate.

        Raises
        ------
        ValueError
            If ``dataset`` does not meet the VOD dataset contract
            (:func:`canvod.readers.base.validate_vod_dataset`).
        """
        validate_vod_dataset(dataset)
        self.check_preprocessing_matches(group_name, dataset, branch)
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        if dedup:
            skip, reason = self.should_skip_vod_write(
                group_name=group_name,
                source_file_hashes=source_file_hashes,
                time_start=start,
                time_end=end,
                branch=branch,
            )
            if skip:
                self._logger.warning(
                    "write_or_append_vod_group_skipped_duplicate",
                    group=group_name,
                    reason=reason,
                    calculator=calculator_name,
                )
                return False

        dataset = self._normalize_encodings(dataset)
        action = "append" if self.group_exists(group_name, branch) else "write"
        if commit_message is None:
            version = get_version_from_pyproject()
            commit_message = (
                f"[v{version}] {action} VOD group '{group_name}' "
                f"(calculator={calculator_name})"
            )
        # The log-book row must carry the message the commit actually gets.
        commit_message = _with_run_id(commit_message)

        with self.writable_session(branch) as session:
            self._logger.info(
                "icechunk_write_data_started",
                group=group_name,
                action=action,
                n_data_vars=len(dataset.data_vars),
                data_vars=list(dataset.data_vars.keys()),
                n_epochs=int(dataset.sizes.get("epoch", 0)),
                approx_size_mb=round(dataset.nbytes / 1e6, 2),
                zarr_async_concurrency=self._zarr_async_concurrency,
            )
            t_write_start = time.perf_counter()
            try:
                if action == "append":
                    self._to_icechunk_throttled(
                        dataset, session, group=group_name, append_dim=append_dim
                    )
                else:
                    self._to_icechunk_throttled(
                        dataset,
                        session,
                        group=group_name,
                        mode="w",
                        encoding=self.chunk_encoding_for(dataset),
                    )
            except Exception:
                self._logger.error(
                    "icechunk_write_data_error",
                    group=group_name,
                    action=action,
                    elapsed_seconds=round(time.perf_counter() - t_write_start, 2),
                )
                raise
            self._logger.info(
                "icechunk_write_data_succeeded",
                group=group_name,
                action=action,
                elapsed_seconds=round(time.perf_counter() - t_write_start, 2),
            )
            zroot = zarr.open_group(session.store, mode="a")
            self._append_vod_metadata_row(
                zroot=zroot,
                group_name=group_name,
                source_file_hashes=source_file_hashes,
                source_gnss_stores=source_gnss_stores,
                start=start,
                end=end,
                snapshot_id="",
                action=action,
                commit_msg=commit_message,
                calculator_name=calculator_name,
                dataset_attrs=dict(dataset.attrs),
            )
            commit_with_rebase(
                session,
                commit_message,
                store_path=self.store_path,
                config=self.settings,
            )

        self._logger.info(
            f"{action.capitalize()}d VOD group '{group_name}' "
            f"({len(dataset.epoch)} epochs, calculator={calculator_name})"
        )
        return True

    def _prepare_vod_write(
        self,
        item: VodWriteItem,
        branch: str = "main",
        dedup: bool = True,
    ) -> tuple[VodWriteResult | None, VodWritePlan | None]:
        """Dedup-check + normalize one VOD write ahead of a forked batch.

        Mirrors the pre-write half of `write_or_append_vod_group`, minus the
        session/write/commit -- `group_name`-scoped only (its own metadata
        table), zero cross-group reads, so safe to run for every item in a
        batch before any fork exists. Returns `(skip_result, None)` if this
        item should be skipped as a duplicate, else `(None, plan)`. Raises
        `ValueError` if the dataset does not meet the VOD dataset contract.
        """
        validate_vod_dataset(item.dataset)
        self.check_preprocessing_matches(item.group_name, item.dataset, branch)
        start = item.dataset.epoch.min().values
        end = item.dataset.epoch.max().values

        if dedup:
            skip, reason = self.should_skip_vod_write(
                group_name=item.group_name,
                source_file_hashes=item.source_file_hashes,
                time_start=start,
                time_end=end,
                branch=branch,
            )
            if skip:
                self._logger.warning(
                    "write_or_append_vod_group_skipped_duplicate",
                    group=item.group_name,
                    reason=reason,
                    calculator=item.calculator_name,
                )
                return (
                    VodWriteResult(
                        group_name=item.group_name, written=False, skip_reason=reason
                    ),
                    None,
                )

        dataset = self._normalize_encodings(item.dataset)
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values
        action = "append" if self.group_exists(item.group_name, branch) else "write"
        # A description of this group's write; the batch combines the
        # descriptions of all groups sharing a commit into its message.
        commit_message = item.commit_message or (
            f"VOD {item.group_name} (calculator={item.calculator_name})"
        )
        return None, VodWritePlan(
            item=item,
            action=action,
            start=start,
            end=end,
            commit_message=commit_message,
            dataset=dataset,
        )

    def _write_vod_into_fork(
        self,
        fork_session: ForkSession,
        plan: VodWritePlan,
    ) -> VodWriteResult:
        """Append one VOD analysis group's dataset into its own fork.

        Runs inside the cross-group thread pool, one call per group. Only
        ever called for `action == "append"` --
        `write_or_append_vod_groups_batch`'s pre-pass fully handles any
        brand-new group before this is ever invoked. Unlike GNSS receiver
        groups (many files per group per day), a VOD write is exactly one
        dataset per group per call, so there is no "remaining data" left
        over for a newly-created group the way there is for GNSS -- the
        pre-pass write IS that group's entire contribution to the batch.
        """
        group_name = plan.item.group_name
        dataset = plan.dataset
        t_start = time.perf_counter()
        self._logger.info(
            "icechunk_write_data_started",
            group=group_name,
            action=plan.action,
            n_data_vars=len(dataset.data_vars),
            data_vars=list(dataset.data_vars.keys()),
            n_epochs=int(dataset.sizes.get("epoch", 0)),
            approx_size_mb=round(dataset.nbytes / 1e6, 2),
            zarr_async_concurrency=self._zarr_async_concurrency,
        )
        try:
            self._to_icechunk_throttled(
                dataset, fork_session, group=group_name, append_dim="epoch"
            )
        except Exception:
            self._logger.error(
                "icechunk_write_data_error",
                group=group_name,
                action=plan.action,
                elapsed_seconds=round(time.perf_counter() - t_start, 2),
            )
            raise
        self._logger.info(
            "icechunk_write_data_succeeded",
            group=group_name,
            action=plan.action,
            elapsed_seconds=round(time.perf_counter() - t_start, 2),
        )
        zroot = zarr.open_group(fork_session.store, mode="a")
        self._append_vod_metadata_row(
            zroot=zroot,
            group_name=group_name,
            source_file_hashes=plan.item.source_file_hashes,
            source_gnss_stores=plan.item.source_gnss_stores,
            start=plan.start,
            end=plan.end,
            snapshot_id="",
            action=plan.action,
            commit_msg=plan.commit_message,
            calculator_name=plan.item.calculator_name,
            dataset_attrs=dict(dataset.attrs),
        )
        return VodWriteResult(
            group_name=group_name,
            written=True,
            duration_seconds=time.perf_counter() - t_start,
        )

    def write_or_append_vod_groups_batch(
        self,
        items: Sequence[VodWriteItem],
        branch: str = "main",
        dedup: bool = True,
    ) -> dict[str, VodWriteResult]:
        """Write/append multiple VOD analysis groups in one fork/merge batch.

        The same cross-group parallelization `RinexDataProcessor` uses for
        GNSS receiver groups (`_write_receiver_batch_forked`), applied to VOD
        analysis groups: any brand-new analysis group is created directly on
        its own clean session that commits alone (pre-pass) -- verified
        empirically (see `_write_receiver_batch_forked`'s docstring) that
        `Session.merge()` silently drops a fork's data if the base session
        it merges into had its own pending uncommitted writes before
        `.fork()` was called, so new-group creation and forked appends can
        never safely share one session. Only groups that already exist go
        through the fork/merge phase; a brand-new group's pre-pass write is
        its entire contribution to this batch (a VOD write is exactly one
        dataset per group per call, unlike GNSS's many-files-per-group-per-
        day case, so there is never leftover data for a newly-created group
        to append afterward).

        Fail-fast: if any group's forked write raises, no merge or commit
        happens for the fork/merge phase -- a partial merge would silently
        drop a group's data from an apparently-successful commit. A
        pre-pass commit that already landed before a later fork failure is
        safe to leave in place: the next retry's dedup check sees that
        group's data as already-committed and won't re-attempt it.
        """
        version = get_version_from_pyproject()
        log = self._logger
        results: dict[str, VodWriteResult] = {}

        new_plans: list[VodWritePlan] = []
        append_plans: dict[str, VodWritePlan] = {}

        for item in items:
            skip_result, plan = self._prepare_vod_write(item, branch, dedup)
            if skip_result is not None:
                results[item.group_name] = skip_result
                continue
            assert plan is not None
            if plan.action == "write":
                new_plans.append(plan)
            else:
                append_plans[item.group_name] = plan

        if not new_plans and not append_plans:
            return results

        # Pre-pass: brand-new groups, sequential, one clean session, one commit.
        if new_plans:
            summary_parts: list[str] = []
            prepass_msg, prepass_metadata = _vod_batch_commit(
                version, "write", new_plans
            )
            with self.writable_session(branch) as prepass_session:
                for plan in new_plans:
                    t_start = time.perf_counter()
                    group_name = plan.item.group_name
                    self._logger.info(
                        "icechunk_write_data_started",
                        group=group_name,
                        action="write",
                        n_data_vars=len(plan.dataset.data_vars),
                        data_vars=list(plan.dataset.data_vars.keys()),
                        n_epochs=int(plan.dataset.sizes.get("epoch", 0)),
                        approx_size_mb=round(plan.dataset.nbytes / 1e6, 2),
                        zarr_async_concurrency=self._zarr_async_concurrency,
                    )
                    self._to_icechunk_throttled(
                        plan.dataset,
                        prepass_session,
                        group=group_name,
                        mode="w",
                        encoding=self.chunk_encoding_for(plan.dataset),
                    )
                    zroot = zarr.open_group(prepass_session.store, mode="a")
                    self._append_vod_metadata_row(
                        zroot=zroot,
                        group_name=group_name,
                        source_file_hashes=plan.item.source_file_hashes,
                        source_gnss_stores=plan.item.source_gnss_stores,
                        start=plan.start,
                        end=plan.end,
                        snapshot_id="",
                        action="write",
                        commit_msg=plan.commit_message,
                        calculator_name=plan.item.calculator_name,
                        dataset_attrs=dict(plan.dataset.attrs),
                    )
                    results[group_name] = VodWriteResult(
                        group_name=group_name,
                        written=True,
                        duration_seconds=time.perf_counter() - t_start,
                    )
                    summary_parts.append(group_name)

                if summary_parts:
                    prepass_snapshot_id = commit_with_rebase(
                        prepass_session,
                        prepass_msg,
                        metadata=prepass_metadata,
                        store_path=self.store_path,
                        config=self.settings,
                    )
                    for name in summary_parts:
                        results[name].snapshot_id = prepass_snapshot_id

        # Fork/merge phase: pre-existing groups only.
        if append_plans:
            # Fail-fast below: either every group lands in this commit or
            # none does, so the message can name all of them up front.
            commit_msg, agg_metadata = _vod_batch_commit(
                version, "append", list(append_plans.values())
            )
            with self.writable_session(branch) as base_session:
                forks = {name: base_session.fork() for name in append_plans}
                with ThreadPoolExecutor(max_workers=len(append_plans)) as tpe:
                    futures = {
                        tpe.submit(self._write_vod_into_fork, forks[name], plan): name
                        for name, plan in append_plans.items()
                    }
                    completed: dict[str, VodWriteResult] = {}
                    try:
                        for fut in as_completed(futures):
                            name = futures[fut]
                            completed[name] = fut.result()
                    except Exception:
                        log.error(
                            "vod_batch_write_failed",
                            succeeded=list(completed),
                            pending=[n for n in append_plans if n not in completed],
                        )
                        raise

                base_session.merge(*forks.values())
                batch_snapshot_id = commit_with_rebase(
                    base_session,
                    commit_msg,
                    metadata=agg_metadata,
                    store_path=self.store_path,
                    config=self.settings,
                )
                for name, result in completed.items():
                    result.snapshot_id = batch_snapshot_id
                    results[name] = result

        log.info(
            "vod_batch_write_complete",
            groups=list(results),
            written=[name for name, r in results.items() if r.written],
            skipped=[name for name, r in results.items() if not r.written],
        )
        return results

    def load_metadata(self, store: Any, group_name: str) -> pl.DataFrame:
        """Load metadata directly from Zarr into a Polars DataFrame.

        Parameters
        ----------
        store : Any
            Zarr store or session store handle.
        group_name : str
            Group name.

        Returns
        -------
        pl.DataFrame
            Metadata table.
        """
        zroot = zarr.open_group(store, mode="r")
        zmeta = zroot[f"{group_name}/metadata/table"]

        # Read all columns into a dict of numpy arrays
        data = {col: zmeta[col][...] for col in zmeta.array_keys()}

        # Build Polars DataFrame
        df = pl.DataFrame(data)

        # Convert numeric datetime64 columns back to proper Polars datetimes
        if "start" in df.columns and df["start"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("start").cast(pl.Datetime("ns")))
        if "end" in df.columns and df["end"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("end").cast(pl.Datetime("ns")))
        if "written_at" in df.columns and df["written_at"].dtype == pl.Utf8:
            df = df.with_columns(pl.col("written_at").str.to_datetime("%+"))
        return df

    def read_metadata_table(self, session: Any, group_name: str) -> pl.DataFrame:
        """Read the metadata table from a session.

        Parameters
        ----------
        session : Any
            Active session for reading.
        group_name : str
            Group name.

        Returns
        -------
        pl.DataFrame
            Metadata table.
        """
        zmeta = zarr.open_group(
            session.store,
            mode="r",
        )[f"{group_name}/metadata/table"]

        data = {col: zmeta[col][:] for col in zmeta.array_keys()}
        df = pl.DataFrame(data)

        # Ensure start/end are proper datetime
        df = df.with_columns(
            [
                pl.col("start").cast(pl.Datetime("ns")),
                pl.col("end").cast(pl.Datetime("ns")),
            ]
        )
        return df

    def metadata_row_exists(
        self,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, pl.DataFrame]:
        """
        Check whether a file already exists or temporally overlaps existing data.

        Performs two checks in order:

        1. **Hash match** — if ``rinex_hash`` already appears in the metadata
           table, the file was previously ingested (exact duplicate).
        2. **Temporal overlap** — if the incoming ``[start, end]`` interval
           overlaps any existing metadata interval, the file covers a time
           range that is already (partially) present in the store.  This
           catches cases like a daily concatenation file coexisting with the
           sub-daily files it was built from.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        rinex_hash : str
            Hash of the current GNSS dataset.
        start : np.datetime64
            Start epoch of the incoming file.
        end : np.datetime64
            End epoch of the incoming file.
        branch : str, default "main"
            Branch name in the Icechunk repository.

        Returns
        -------
        tuple[bool, pl.DataFrame]
            ``(True, overlapping_rows)`` when the file should be skipped,
            ``(False, empty_df)`` when it is safe to ingest.
        """
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
            except Exception:
                return False, pl.DataFrame()

            data = {col: zmeta[col][:] for col in zmeta.array_keys()}
            df = pl.DataFrame(data)

            df = df.with_columns(
                [
                    pl.col("start").cast(pl.Datetime("ns")),
                    pl.col("end").cast(pl.Datetime("ns")),
                ]
            )

            # --- Check 1: exact hash match (file already ingested) ---
            hash_matches = df.filter(pl.col("rinex_hash") == rinex_hash)
            if not hash_matches.is_empty():
                return True, hash_matches

            # --- Check 2: temporal overlap ---
            # Two intervals [A.start, A.end] and [B.start, B.end] overlap
            # iff A.start <= B.end AND A.end >= B.start
            start_ns = np.datetime64(start, "ns")
            end_ns = np.datetime64(end, "ns")

            overlaps = df.filter(
                (pl.col("start") <= end_ns) & (pl.col("end") >= start_ns)
            )

            if not overlaps.is_empty():
                n = overlaps.height
                existing_range = f"{overlaps['start'].min()} → {overlaps['end'].max()}"
                self._logger.warning(
                    "temporal_overlap_detected",
                    group=group_name,
                    incoming_hash=rinex_hash,
                    incoming_range=f"{start} → {end}",
                    existing_range=existing_range,
                    overlapping_files=n,
                )
                return True, overlaps

            return False, pl.DataFrame()

    def should_skip_file(
        self,
        group_name: str,
        file_hash: str | None,
        time_start: np.datetime64,
        time_end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, str]:
        """Check whether a file should be skipped before processing and writing.

        Thin public wrapper around :meth:`metadata_row_exists` that returns a
        simple ``(skip, reason)`` pair instead of a DataFrame, suitable for use
        in Airflow task functions as an early-exit optimization.

        This method is an early-exit optimization: it avoids opening a write
        session for files that are already present.  Pass ``dedup=True`` to
        :meth:`write_or_append_group` to make the store the authoritative
        final gate (runs the same check again before writing).

        Checks performed (in order):

        1. **Hash match** — file was previously ingested (exact duplicate).
        2. **Temporal overlap** — incoming time range overlaps existing epochs.

        Layer 3 (intra-batch overlap) is not applicable here because task
        functions process files one at a time.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        file_hash : str or None
            Hash from ``dataset.attrs["File Hash"]``.  When ``None`` the check
            is skipped and ``(False, "")`` is returned.
        time_start : np.datetime64
            First epoch of the incoming dataset.
        time_end : np.datetime64
            Last epoch of the incoming dataset.
        branch : str, default "main"
            Branch name in the Icechunk repository.

        Returns
        -------
        tuple[bool, str]
            ``(True, "hash_match")``: exact duplicate, skip.
            ``(True, "temporal_overlap")``: overlapping time range, skip.
            ``(False, "")``: safe to ingest.
        """
        if file_hash is None:
            return False, ""

        exists, matches = self.metadata_row_exists(
            group_name, file_hash, time_start, time_end, branch
        )
        if not exists:
            return False, ""

        if not matches.is_empty() and (matches["rinex_hash"] == file_hash).any():
            return True, "hash_match"
        return True, "temporal_overlap"

    def dir_entry_counts(self) -> dict[str, int]:
        """Cheap on-disk entry counts for ``manifests``/``snapshots``/``transactions``.

        A directional proxy for Icechunk-internal growth (manifest count,
        snapshot count) without walking the full store. Deliberately
        excludes ``chunks/`` (can reach millions of entries -- not cheap)
        and only applies to local-filesystem-backed stores; returns ``{}``
        for anything else (e.g. S3/GCS) since ``os.scandir`` doesn't apply.
        """
        counts: dict[str, int] = {}
        for name in ("manifests", "snapshots", "transactions"):
            d = self.store_path / name
            try:
                with os.scandir(d) as it:
                    counts[name] = sum(1 for _ in it)
            except OSError:
                continue
        return counts

    def metadata_row_count(self, group_name: str, branch: str = "main") -> int:
        """Row count of ``{group_name}/metadata/table``, or 0 if absent.

        Reads only the ``index`` array's shape (no full table load) -- cheap
        enough to log alongside every dedup check, so growth in
        ``batch_check``/``check_temporal_overlaps`` duration can be directly
        correlated against store size instead of assumed.
        """
        try:
            with self.readonly_session(branch) as session:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
                return int(zmeta["index"].shape[0])
        except Exception:
            return 0

    def source_file_hashes(
        self,
        group_name: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
    ) -> list[str]:
        """Hashes of the ingested files whose data overlaps ``[start, end]``.

        Read from ``group_name``'s log book, in ingest order and without
        duplicates. Rows recording a file that was skipped as already
        ingested (``exists`` is ``"True"`` and nothing was written) are
        ignored, so each file counts once however often it was re-run.

        Used as the provenance of a dataset read back from the store for
        that range, e.g. the daily inputs of a VOD computation.
        """
        df = self.load_metadata_for_dedup(group_name, branch=branch)
        if df is None or df.is_empty():
            return []

        rows = _written_rows_overlapping(df, start, end).sort("index")
        return list(dict.fromkeys(str(h) for h in rows["rinex_hash"].to_list()))

    def load_metadata_for_dedup(
        self, group_name: str, branch: str = "main"
    ) -> pl.DataFrame | None:
        """Load ``{group_name}``'s metadata table once, for reuse across dedup checks.

        ``batch_check_existing``/``check_temporal_overlaps`` each used to call
        ``load_metadata()`` independently -- two full-table reads per batch,
        growing with store size (confirmed
        against a real backfill: ``batch_check`` duration tracked
        ``metadata_rows`` almost exactly, ~5x over 41,597 rows). Callers
        needing both checks should load once here and pass the result to
        both via their ``metadata_df`` parameter. Returns ``None`` (not an
        empty DataFrame) when the group/metadata doesn't exist yet, so
        callers can distinguish "nothing to check against" from "failed to
        load" without re-attempting the load.
        """
        try:
            with self.readonly_session(branch) as session:
                t0 = time.perf_counter()
                df = self.load_metadata(session.store, group_name)
                self._logger.info(
                    "metadata_table_loaded",
                    duration_seconds=round(time.perf_counter() - t0, 4),
                    group=group_name,
                    rows=df.height,
                    caller="load_metadata_for_dedup",
                )
                return df
        except Exception:
            return None

    def batch_check_existing(
        self,
        group_name: str,
        file_hashes: list[str],
        metadata_df: pl.DataFrame | None = None,
    ) -> set[str]:
        """Check which file hashes already exist in metadata.

        Parameters
        ----------
        metadata_df : pl.DataFrame, optional
            Pre-loaded metadata table (see ``load_metadata_for_dedup``) to
            skip this call's own full-table read. Loads internally (original
            behavior) when not provided.
        """
        try:
            if metadata_df is None:
                with self.readonly_session("main") as session:
                    t0 = time.perf_counter()
                    df = self.load_metadata(session.store, group_name)
                    self._logger.info(
                        "metadata_table_loaded",
                        duration_seconds=round(time.perf_counter() - t0, 4),
                        group=group_name,
                        rows=df.height,
                        caller="batch_check_existing",
                    )
            else:
                df = metadata_df

            existing = df.filter(pl.col("rinex_hash").is_in(file_hashes))
            return set(existing["rinex_hash"].to_list())

        except Exception:
            # Branch/group/metadata doesn't exist yet (fresh store)
            return set()

    def check_temporal_overlaps(
        self,
        group_name: str,
        file_intervals: list[tuple[str, np.datetime64, np.datetime64]],
        branch: str = "main",
        metadata_df: pl.DataFrame | None = None,
    ) -> set[str]:
        """Check which files temporally overlap existing metadata intervals.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        file_intervals : list[tuple[str, np.datetime64, np.datetime64]]
            List of ``(rinex_hash, start, end)`` tuples for incoming files.
        branch : str, default "main"
            Branch name in the Icechunk repository.
        metadata_df : pl.DataFrame, optional
            Pre-loaded metadata table (see ``load_metadata_for_dedup``) to
            skip this call's own full-table read. Loads internally (original
            behavior) when not provided.

        Returns
        -------
        set[str]
            Hashes of files whose ``[start, end]`` overlaps any existing
            metadata interval.  Files whose hash already exists in the store
            are NOT included (use ``batch_check_existing`` for those).
        """
        if not file_intervals:
            return set()

        if metadata_df is None:
            try:
                with self.readonly_session(branch) as session:
                    t0 = time.perf_counter()
                    df = self.load_metadata(session.store, group_name)
                    self._logger.info(
                        "metadata_table_loaded",
                        duration_seconds=round(time.perf_counter() - t0, 4),
                        group=group_name,
                        rows=df.height,
                        caller="check_temporal_overlaps",
                    )
            except Exception:
                return set()
        else:
            df = metadata_df

        if df.is_empty():
            return set()

        df = df.with_columns(
            [
                pl.col("start").cast(pl.Datetime("ns")),
                pl.col("end").cast(pl.Datetime("ns")),
            ]
        )

        # Build from proper numpy datetime64[ns] *arrays*, not boxed scalars:
        # polars' dict-of-scalars inference silently reinterprets the
        # underlying int64 as microseconds regardless of the numpy dtype's
        # declared unit (produces garbage timestamps), where array dtype
        # metadata is read correctly.
        incoming = pl.DataFrame(
            {
                "incoming_hash": [h for h, _, _ in file_intervals],
                "incoming_start": np.array(
                    [s for _, s, _ in file_intervals], dtype="datetime64[ns]"
                ),
                "incoming_end": np.array(
                    [e for _, _, e in file_intervals], dtype="datetime64[ns]"
                ),
            }
        )

        t_loop = time.perf_counter()
        # Vectorized interval-overlap join replaces one .filter() scan per
        # incoming interval (O(intervals x rows) Python loop) with a single
        # sort-merge join.
        hits = incoming.join_where(
            df.select(["rinex_hash", "start", "end"]),
            pl.col("incoming_start") <= pl.col("end"),
            pl.col("incoming_end") >= pl.col("start"),
        )

        overlapping: set[str] = set()
        if not hits.is_empty():
            summary = hits.group_by(
                ["incoming_hash", "incoming_start", "incoming_end"]
            ).agg(pl.len().alias("existing_files"))
            for row in summary.iter_rows(named=True):
                overlapping.add(row["incoming_hash"])
                self._logger.warning(
                    "temporal_overlap_detected",
                    group=group_name,
                    incoming_hash=row["incoming_hash"][:16],
                    incoming_range=f"{row['incoming_start']} → {row['incoming_end']}",
                    existing_files=row["existing_files"],
                )

        self._logger.info(
            "temporal_overlap_scan_complete",
            duration_seconds=round(time.perf_counter() - t_loop, 4),
            group=group_name,
            intervals=len(file_intervals),
            rows=df.height,
        )
        return overlapping

    def expire_old_snapshots(
        self,
        days: int | None = None,
        branch: str = "main",
        delete_expired_branches: bool = False,
        delete_expired_tags: bool = False,
    ) -> set[str]:
        """
        Expire snapshots older than the given retention period.

        Metadata-only "soft delete": rewrites ancestry so expired snapshots
        become unreachable from any surviving branch/tag. No objects
        (manifests, chunks, snapshot files) are deleted at this stage —
        call ``garbage_collect()`` separately to reclaim storage.
        Keeping
        this expire-only (previously it also ran GC internally) is what
        lets a caller run GC exactly once via ``maintenance()`` instead of
        twice per call.

        Never invoke this automatically inside the pipeline's write path:
        it's an administrative operation, not safe to run casually
        alongside active writes. Use a generous ``days`` margin (weeks to
        months, not hours) so it can never touch anything from an
        in-flight write session.

        Parameters
        ----------
        days : int | None, optional
            Number of days to retain snapshots. Defaults to 90 (weeks-to-
            months cadence).
        branch : str, default "main"
            Branch to apply expiration on.
        delete_expired_branches : bool, default False
            Whether to delete branches pointing to expired snapshots.
            Matches Icechunk's own safe default: flip only deliberately.
        delete_expired_tags : bool, default False
            Whether to delete tags pointing to expired snapshots.
            **Do not set True** if using keeper tags (``create_keeper_tag``)
            — it would delete them along with any other expired-tip tag.

        Returns
        -------
        set[str]
            Expired snapshot IDs.
        """
        if days is None:
            days = 90
        cutoff = datetime.now(UTC) - timedelta(days=days)

        self._logger.info(
            f"Running expiration on store '{self.store_type}' "
            f"(branch '{branch}') with cutoff {cutoff.isoformat()}"
        )

        # Expire snapshots older than cutoff
        with commit_lock(self.store_path):
            expired_ids = self.repo.expire_snapshots(
                older_than=cutoff,
                delete_expired_branches=delete_expired_branches,
                delete_expired_tags=delete_expired_tags,
            )

        if expired_ids:
            self._logger.info(
                f"Expired {len(expired_ids)} snapshots: {sorted(expired_ids)}"
            )
        else:
            self._logger.info("No snapshots to expire.")

        return expired_ids

    def garbage_collect(self, days: int = 90, *, dry_run: bool = False) -> dict:
        """
        Physically delete objects no longer reachable from any branch/tag.

        Only removes what a prior ``expire_old_snapshots()`` (or manual ref
        deletion) already made unreachable — this does not itself expire
        anything. Always run with ``dry_run=True`` first on a store that
        hasn't been GC'd before, especially one with a large accumulated
        backlog: there's no documented cost model for GC time/memory at
        scale, so a first-ever run's duration is unknown until measured.

        **Not safe to run casually alongside active writes** — the cutoff
        must predate the start of any concurrently-running write session,
        and only one expire/GC operation should run at a time. Icechunk
        does have self-protection against races with *new* commits arriving
        mid-run (it restarts, bounded retries, rather than deleting
        something a concurrent writer needs), but that's not a substitute
        for a generous cutoff margin.

        Parameters
        ----------
        days : int, default 90
            Objects older than this (by the same write-time semantics as
            ``expire_old_snapshots``) are eligible for deletion.
        dry_run : bool, default False
            Report what would be deleted without deleting anything.

        Returns
        -------
        dict
            Summary of (would-be-)deleted objects.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with commit_lock(self.store_path):
            summary = self.repo.garbage_collect(
                delete_object_older_than=cutoff, dry_run=dry_run
            )
        self._logger.info(
            "garbage_collect_complete",
            dry_run=dry_run,
            cutoff=cutoff.isoformat(),
            bytes_deleted=summary.bytes_deleted,
            chunks_deleted=summary.chunks_deleted,
            manifests_deleted=summary.manifests_deleted,
            snapshots_deleted=summary.snapshots_deleted,
            attributes_deleted=summary.attributes_deleted,
            transaction_logs_deleted=summary.transaction_logs_deleted,
        )
        return {
            "dry_run": dry_run,
            "cutoff": cutoff.isoformat(),
            "bytes_deleted": summary.bytes_deleted,
            "chunks_deleted": summary.chunks_deleted,
            "manifests_deleted": summary.manifests_deleted,
            "snapshots_deleted": summary.snapshots_deleted,
            "attributes_deleted": summary.attributes_deleted,
            "transaction_logs_deleted": summary.transaction_logs_deleted,
        }

    def get_history(self, branch: str = "main", limit: int | None = None) -> list[dict]:
        """
        Return commit ancestry (history) for a branch.

        Parameters
        ----------
        branch : str, default "main"
            Branch name.
        limit : int | None, optional
            Maximum number of commits to return.

        Returns
        -------
        list[dict]
            Commit info dictionaries (id, message, written_at, parent_ids).
        """
        self._logger.info(f"Fetching ancestry for branch '{branch}'")

        history = []
        for i, ancestor in enumerate(self.repo.ancestry(branch=branch)):
            history.append(
                {
                    "snapshot_id": ancestor.id,
                    "commit_msg": ancestor.message,
                    "written_at": ancestor.written_at,
                    "parent_ids": ancestor.parent_id,
                }
            )
            if limit is not None and i + 1 >= limit:
                break

        return history

    def print_history(self, branch: str = "main", limit: int | None = 100) -> None:
        """
        Pretty-print the ancestry for quick inspection.
        """
        for entry in self.get_history(branch=branch, limit=limit):
            ts = entry["written_at"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts} {entry['snapshot_id'][:8]} {entry['commit_msg']}")

    def get_ops_log(self, limit: int | None = None) -> list[dict]:
        """
        Return the repository operations log (newest first).

        The ops log is an immutable audit trail of every structural mutation:
        commits, branch and tag operations, GC runs, config changes, etc.
        Unlike :meth:`get_history`, this is repo-wide (not per-branch) and
        covers all event types, not only commits.

        Parameters
        ----------
        limit : int | None, optional
            Maximum number of entries to return. ``None`` returns all.

        Returns
        -------
        list[dict]
            Each entry contains ``kind`` (str), ``updated_at`` (datetime),
            and ``backup_path`` (str).
        """
        entries = []
        try:
            for i, update in enumerate(self._repo.ops_log()):
                entries.append(
                    {
                        "kind": str(update.kind),
                        "updated_at": update.updated_at,
                        "backup_path": update.backup_path,
                    }
                )
                if limit is not None and i + 1 >= limit:
                    break
        except icechunk.IcechunkError as exc:
            if "repository version" in str(exc):
                self._logger.warning(
                    "ops_log requires icechunk v2 store format; "
                    "this store is v1. Returning empty log."
                )
            else:
                raise
        return entries

    def print_ops_log(self, limit: int | None = 50) -> None:
        """
        Pretty-print the repository operations log for quick inspection.

        Parameters
        ----------
        limit : int | None, optional
            Maximum number of entries to display (default: 50).
        """
        for entry in self.get_ops_log(limit=limit):
            ts = entry["updated_at"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts}  {entry['kind']}")

    def maintenance_due(
        self,
        expire_interval_days: int,
        gc_delay_days: int,
        manifest_count_threshold: int | None = None,
    ) -> dict[str, Any]:
        """
        Determine whether scheduled expiration/GC/manifest compaction are
        due.

        Used by ``canvodpy store maintain-due`` (a cron-safe, unattended
        entry point -- see ``processing.storage.maintenance`` config). The
        repo's own ops log (:meth:`get_ops_log`) is the source of truth for
        "when did maintenance last actually run": it is written atomically
        by Icechunk itself as part of the same operation, so it cannot
        drift the way a separate marker file could (deleted, stale-copied
        across hosts on a shared mount, or never written if a prior run
        crashed after the real operation completed but before a marker
        write). Confirmed empirically (2026-07-20, throwaway store): a real
        ``expire_old_snapshots()`` call always writes an ``ExpirationRan``
        entry (even when zero snapshots were actually expired -- root/tip
        snapshots are protected); ``garbage_collect(dry_run=True)`` does
        **not** write a ``GCRan`` entry, only a real (non-dry-run) GC does
        -- so a dry run correctly never counts as "GC happened" here.

        GC is only ever considered due *after* a qualifying expiration, and
        never again for the same expiration -- physical deletion should
        lag the (reversible-in-effect) soft-delete by ``gc_delay_days``,
        per the skill doc's "expire every 1-2 months, GC every 15-30 days"
        guidance.

        Parameters
        ----------
        expire_interval_days : int
            Re-run expiration if this many days have passed since the most
            recent ``ExpirationRan`` entry (or if there is none yet).
        gc_delay_days : int
            Run GC this many days after the most recent expiration, once
            per expiration (skipped if GC already ran since that
            expiration).
        manifest_count_threshold : int | None, optional
            Trigger ``rewrite_manifests()`` (manifest compaction) when
            :meth:`dir_entry_counts`'s ``manifests`` count reaches this.
            Unlike expiration/GC, ``rewrite_manifests()`` writes no
            distinguishing ops-log entry -- it logs as an ordinary
            ``NewCommit``, indistinguishable from a data-ingest commit --
            so due-ness is measured directly from current fragmentation
            rather than time-since-last-ops-log-entry. ``None`` (default)
            always reports ``manifests_due=False`` (caller opted out via
            ``manifests_enabled=False``). Returns ``False`` (not an
            error) if the store isn't local-filesystem-backed
            (:meth:`dir_entry_counts` returns ``{}`` for S3/GCS).

        Returns
        -------
        dict[str, Any]
            ``expire_due`` (bool), ``gc_due`` (bool), ``manifests_due``
            (bool), ``last_expire`` (datetime | None), ``last_gc``
            (datetime | None), ``manifest_count`` (int | None).
        """
        last_expire: datetime | None = None
        last_gc: datetime | None = None
        # Iterate the lazy Repository.ops_log() directly (not get_ops_log(),
        # which always fully materializes the log into a list) so the
        # early-break below actually short-circuits I/O instead of paying
        # an unbounded, ever-growing scan on every scheduled invocation --
        # ironic for a feature that exists because logs grow unbounded.
        for update in self._repo.ops_log():
            kind = str(update.kind)
            if last_expire is None and "ExpirationRan" in kind:
                last_expire = update.updated_at
            elif last_gc is None and "GCRan" in kind:
                last_gc = update.updated_at
            if last_expire is not None and last_gc is not None:
                break

        now = datetime.now(UTC)
        expire_due = last_expire is None or (now - last_expire) >= timedelta(
            days=expire_interval_days
        )
        gc_due = (
            last_expire is not None
            and (now - last_expire) >= timedelta(days=gc_delay_days)
            and (last_gc is None or last_gc < last_expire)
        )

        manifest_count: int | None = None
        manifests_due = False
        if manifest_count_threshold is not None:
            manifest_count = self.dir_entry_counts().get("manifests")
            manifests_due = (
                manifest_count is not None
                and manifest_count >= manifest_count_threshold
            )

        return {
            "expire_due": expire_due,
            "gc_due": gc_due,
            "manifests_due": manifests_due,
            "last_expire": last_expire,
            "last_gc": last_gc,
            "manifest_count": manifest_count,
        }

    def compact_manifests(self, branch: str = "main") -> str:
        """
        Consolidate all of a branch's fragmented manifests in one commit.

        Thin wrapper over ``repo.rewrite_manifests()``: canvodpy's write
        pattern (one ``to_icechunk()`` call per file within a batch, e.g.
        96 fifteen-minute files/receiver-day) creates one new manifest
        per flush, not per commit -- a single day's ingest for one
        receiver can create ~96 manifests. This rewrites them back to
        the currently-configured splitting boundaries.

        Uses ``commit_method="new_commit"`` deliberately, not ``"amend"``:
        amend replaces the immediately-preceding commit's own message/
        metadata rather than merging with it, and ``_append_to_icechunk``
        already attaches structured provenance (receiver, date, file
        hashes) to every ingest commit -- amending could silently clobber
        that. An explicit, separate, auditable commit matches the
        precedent expire/GC already set. Like every commit, it records
        software, environment and settings as commit metadata
        (:func:`canvod.store_metadata.rewrite_manifests`).

        Like ``expire_old_snapshots()``/``garbage_collect()``, this is an
        administrative operation -- never call it while a pipeline run is
        active against this branch (ordinary commit conflict-retry
        semantics apply, but a still-draining worker pool committing
        per-file would just make every retry lose, burning cycles for
        nothing).

        Does **not** shrink on-disk manifest count by itself -- confirmed
        empirically (2026-07-20, throwaway store, 300 commits): compaction
        adds a new, consolidated manifest set but leaves the old
        fragmented ones on disk (399 -> 401 manifests immediately after
        compacting); only a subsequent ``expire_old_snapshots()`` +
        ``garbage_collect()`` actually reclaims them (399 -> 2 in the same
        test). This mirrors GC's own relationship to expiration -- don't
        expect ``dir_entry_counts()['manifests']`` to drop right after
        calling this; it drops after the next expire/GC cycle instead.

        Parameters
        ----------
        branch : str, default "main"
            Branch to compact.

        Returns
        -------
        str
            Snapshot ID of the compaction commit.
        """
        self._logger.info(
            f"Compacting manifests on store '{self.store_type}' (branch '{branch}')"
        )
        new_snapshot = rewrite_manifests(
            self.store_path,
            f"Compact manifests ({self.store_type})",
            branch=branch,
            config=self.settings,
        )
        self._logger.info(f"Manifest compaction complete: snapshot {new_snapshot}")
        return new_snapshot

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.
        """
        display_names = {"gnss_store": "GNSS Store", "vod_store": "VOD Store"}
        display = display_names.get(self.store_type, self.store_type)
        return f"MyIcechunkStore(store_path={self.store_path}, store_type={display})"

    def __str__(self) -> str:
        """Return a human-readable summary.

        Returns
        -------
        str
            Summary string.
        """

        # Capture tree output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            self.print_tree()
            tree_output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        branches = self.get_branch_names()
        group_dict = self.get_group_names()
        total_groups = sum(len(groups) for groups in group_dict.values())

        return (
            f"MyIcechunkStore: {self.store_path}\n"
            f"Branches: {len(branches)} | Total Groups: {total_groups}\n\n"
            f"{tree_output}"
        )

    @staticmethod
    def _copy_zarr_subtree(source_group: Any, target_group: Any) -> int:
        """Recursively copy all arrays, subgroups, and attrs (byte-for-byte).

        Used to restore ``group_name``'s nested ``metadata/`` subtree after
        a destructive ``mode="w"`` rewrite of the group's data arrays wipes
        it. Copies raw Zarr arrays directly (no xarray/Polars round-trip),
        so there is no dtype/schema-reconstruction risk — the arrays here
        (file registry rows, SBF metadata, etc.) end up byte-identical to
        the source. Handles arbitrary nesting depth (e.g. ``metadata/table``
        and ``metadata/sbf_obs`` are both subgroups of ``metadata``, not
        direct arrays of it).

        Parameters
        ----------
        source_group : zarr.Group
            Group to copy from (e.g. the original ``group_name`` node).
        target_group : zarr.Group
            Group to copy into (must already exist).

        Returns
        -------
        int
            Total number of subgroups copied (recursively).
        """
        target_group.attrs.update(source_group.attrs)

        count = 0
        for array_name in source_group.array_keys():
            source_array = source_group[array_name]
            target_array = target_group.create_array(
                array_name,
                shape=source_array.shape,
                dtype=source_array.dtype,
                chunks=source_array.chunks,
                overwrite=True,
            )
            target_array[:] = source_array[:]
            target_array.attrs.update(source_array.attrs)

        for subgroup_name in source_group.group_keys():
            source_subgroup = source_group[subgroup_name]
            target_subgroup = target_group.create_group(subgroup_name, overwrite=True)
            count += 1
            count += MyIcechunkStore._copy_zarr_subtree(
                source_subgroup, target_subgroup
            )

        return count

    def rechunk_group(
        self,
        group_name: str,
        chunks: dict[str, int],
        source_branch: str = "main",
        temp_branch: str | None = None,
        promote_to_main: bool = True,
        delete_temp_branch: bool = True,
    ) -> str:
        """
        Rechunk a group with optimal chunk sizes.

        Zarr arrays have a fixed chunk shape once created — writing with
        ``mode="r+"`` onto an existing array cannot change chunk boundaries,
        it can only update values within the existing grid (verified
        2026-07-08: a previous version of this method used ``mode="r+"``,
        which silently failed to change on-disk chunking whenever the
        request didn't align with the current chunks). Actually changing
        chunk size requires a destructive ``mode="w"`` rewrite of the
        group, which also wipes the group's nested subgroups (``metadata/
        table``, ``metadata/sbf_obs``) — so this method copies that
        subtree back afterward via a raw recursive Zarr copy (see
        ``_copy_zarr_subtree``), all on a temporary branch, before ``main``
        is ever touched. The copy handles canvod-store's two-level-deep
        ``metadata/{table,sbf_obs}`` nesting.

        Both the data read and the subtree copy are pinned to the exact
        snapshot captured at the start of this call. If ``source_branch``
        moves before the promotion, the promotion is refused with
        ``BranchMovedError`` (the new commits would be dropped) and the
        rechunked data stays on ``temp_branch``.

        Parameters
        ----------
        group_name : str
            Name of the group to rechunk
        chunks : dict[str, int]
            Chunking specification, e.g. {'epoch': 17280, 'sid': -1}
        source_branch : str
            Branch to read original data from (default: "main")
        temp_branch : str | None
            Temporary branch name for rechunked data. If None, uses
            "{group_name}_rechunked".
        promote_to_main : bool
            If True, move ``source_branch`` to the rechunked snapshot after
            writing (see ``promote_branch``).
        delete_temp_branch : bool
            If True, delete temporary branch after promotion (only if
            promote_to_main=True).

        Returns
        -------
        str
            Snapshot ID of the rechunked data

        Raises
        ------
        ValueError
            If ``temp_branch`` already exists.
        BranchMovedError
            If ``source_branch`` moved during the rechunk.
        """
        if temp_branch is None:
            temp_branch = f"{group_name}_rechunked_temp"

        self._logger.info(
            f"Starting rechunk of group '{group_name}' with chunks={chunks}"
        )

        # Snapshot everything up front so the whole operation is pinned to
        # one consistent point in time, regardless of concurrent writers.
        current_snapshot = self.repo.lookup_branch(source_branch)

        # Create temp branch from that snapshot (preserves all existing groups)
        if temp_branch in self.repo.list_branches():
            raise ValueError(
                f"Temporary branch '{temp_branch}' already exists (e.g. from "
                "an earlier rechunk that could not be promoted). Inspect it, "
                "then delete it with delete_branch() or pass another "
                "temp_branch."
            )
        self.repo.create_branch(temp_branch, current_snapshot)
        self._logger.info(
            f"Created temporary branch '{temp_branch}' from current {source_branch}"
        )

        # Read original data, pinned to current_snapshot
        session = self.repo.readonly_session(snapshot_id=current_snapshot)
        ds_original = xr.open_zarr(session.store, group=group_name, consolidated=False)
        self._logger.info(f"Original chunks: {ds_original.chunks}")

        # Rechunk
        ds_rechunked = ds_original.chunk(chunks)
        self._logger.info(f"New chunks: {ds_rechunked.chunks}")

        # Clear encoding in-place on all variables and coords.
        # Assignment (= {}) creates a new dict on the returned copy and
        # is a no-op; .clear() mutates the shared dict the Dataset holds.
        for key in list(ds_rechunked.data_vars) + list(ds_rechunked.coords):
            ds_rechunked[key].encoding.clear()

        source_zroot = zarr.open_group(session.store, mode="r")
        source_group = source_zroot[group_name]
        subgroup_names = list(source_group.group_keys())

        # Force-write with mode="w": the only way to actually change chunk
        # boundaries on an existing array. This wipes group_name's entire
        # subtree, including all subgroups -- restored below, same
        # session, same commit, so the temp branch never has a subgroup-less
        # state that could be read by anything else.
        with self.writable_session(temp_branch) as session:
            self._to_icechunk_throttled(
                ds_rechunked, session, group=group_name, mode="w"
            )

            subgroup_count = 0
            if subgroup_names:
                ro_session = self.repo.readonly_session(snapshot_id=current_snapshot)
                ro_zroot = zarr.open_group(ro_session.store, mode="r")
                source_group = ro_zroot[group_name]

                target_zroot = zarr.open_group(session.store, mode="a")
                target_group = target_zroot[group_name]

                for subgroup_name in subgroup_names:
                    source_subgroup = source_group[subgroup_name]
                    target_subgroup = target_group.create_group(
                        subgroup_name, overwrite=True
                    )
                    subgroup_count += 1
                    subgroup_count += self._copy_zarr_subtree(
                        source_subgroup, target_subgroup
                    )

            snapshot_id = commit_with_rebase(
                session,
                _with_run_id(
                    f"Rechunked {group_name} with chunks={chunks} "
                    f"({subgroup_count} subgroups restored)"
                ),
                store_path=self.store_path,
                config=self.settings,
            )

        self._logger.info(
            f"Rechunked data written to branch '{temp_branch}', snapshot={snapshot_id}"
        )

        # Promote to main if requested
        if promote_to_main:
            self.promote_branch(temp_branch, source_branch, current_snapshot)

            # Delete temp branch if requested
            if delete_temp_branch:
                self.repo.delete_branch(temp_branch)
                self._logger.info(f"Deleted temporary branch '{temp_branch}'")

        return snapshot_id

    def promote_branch(
        self,
        temp_branch: str,
        target_branch: str,
        expected_tip: str,
    ) -> str:
        """Move ``target_branch`` to the tip of ``temp_branch``.

        Only if ``target_branch`` still points at ``expected_tip``, the
        snapshot ``temp_branch`` was created from. Otherwise other commits
        landed on ``target_branch`` meanwhile and moving it would drop them.

        Parameters
        ----------
        temp_branch : str
            Branch holding the staged work.
        target_branch : str
            Branch to move (usually ``"main"``).
        expected_tip : str
            Snapshot ID ``target_branch`` pointed at when ``temp_branch``
            was created.

        Returns
        -------
        str
            The new tip of ``target_branch``.

        Raises
        ------
        BranchMovedError
            If ``target_branch`` moved. ``temp_branch`` is left in place.
        """
        new_tip = self.repo.lookup_branch(temp_branch)
        try:
            with commit_lock(self.store_path):
                self.repo.reset_branch(
                    target_branch, new_tip, from_snapshot_id=expected_tip
                )
        except icechunk.IcechunkError as e:
            current_tip = self.repo.lookup_branch(target_branch)
            if current_tip == expected_tip:
                raise
            raise BranchMovedError(
                f"Branch '{target_branch}' moved from {expected_tip[:8]} to "
                f"{current_tip[:8]} while the work was staged on "
                f"'{temp_branch}'. '{target_branch}' was not changed, so the "
                f"new commits are kept; the staged work is still on "
                f"'{temp_branch}' (snapshot {new_tip[:8]}). Run the step "
                "again once the other writer is done."
            ) from e
        self._logger.info(
            f"Promoted '{temp_branch}' to '{target_branch}' (snapshot {new_tip[:8]})"
        )
        return new_tip

    def create_branch(self, branch_name: str, snapshot_id: str) -> None:
        """
        Create a branch pointing at a specific snapshot.

        Accepts either the full snapshot ID or an 8-character prefix as shown
        in ``plot_commit_graph()``.  Raises ``ValueError`` if the prefix is
        ambiguous or not found.

        Parameters
        ----------
        branch_name : str
            Name of the new branch (e.g. ``"explore/my-analysis"``).
        snapshot_id : str
            Full snapshot ID or 8-char prefix (case-insensitive).
        """
        if len(snapshot_id) < 32:
            prefix = snapshot_id.upper()
            history = self.get_history(limit=None)
            matches = [
                h
                for h in history
                if h.get("snapshot_id", "").upper().startswith(prefix)
            ]
            if not matches:
                raise ValueError(
                    f"No snapshot found with prefix '{snapshot_id}'. "
                    "Use get_history() to list available snapshots."
                )
            if len(matches) > 1:
                ids = [m["snapshot_id"] for m in matches]
                raise ValueError(
                    f"Ambiguous prefix '{snapshot_id}' "
                    f"matches {len(ids)} snapshots: {ids}"
                )
            snapshot_id = matches[0]["snapshot_id"]
        self.repo.create_branch(branch_name, snapshot_id)
        self._logger.info(
            f"Created branch '{branch_name}' at snapshot {snapshot_id[:8]}"
        )

    def create_release_tag(self, tag_name: str, snapshot_id: str | None = None) -> None:
        """
        Create an immutable tag for an important version.

        Parameters
        ----------
        tag_name : str
            Name for the tag (e.g., "v2024_complete", "before_reprocess")
        snapshot_id : str | None
            Snapshot to tag. If None, uses current tip of main branch.
        """
        if snapshot_id is None:
            # Tag current main branch tip
            snapshot_id = self.repo.lookup_branch("main")

        self.repo.create_tag(tag_name, snapshot_id)
        self._logger.info(f"Created tag '{tag_name}' at snapshot {snapshot_id[:8]}")

    def list_tags(self) -> list[str]:
        """List all tags in the repository."""
        return list(self.repo.list_tags())

    def delete_tag(self, tag_name: str) -> None:
        """Delete a tag (use with caution - tags are meant to be permanent)."""
        self.repo.delete_tag(tag_name)
        self._logger.warning(f"Deleted tag '{tag_name}'")

    def create_keeper_tag(self, receiver: str, yyyydoy: str, snapshot_id: str) -> bool:
        """
        Tag a per-(receiver, date) commit as a permanent retention keeper.

        Part of the tag-based retention scheme: tagging
        ``keep/{receiver}/{yyyydoy}`` after each commit means a later
        ``expire_old_snapshots(delete_expired_tags=False)`` run can safely
        prune everything else while these specific snapshots stay
        time-travelable forever. Additive and inert on its own — creating a
        tag doesn't expire or delete anything.

        Never raises: a tag name collision (already exists, or was
        previously deleted — Icechunk tag names are never reusable) is
        logged and skipped rather than failing the pipeline write that
        called this.

        Parameters
        ----------
        receiver : str
            Receiver/group name (e.g. ``"canopy_01"``).
        yyyydoy : str
            Date key (e.g. ``"2025001"``).
        snapshot_id : str
            Snapshot to tag — typically the just-committed snapshot.

        Returns
        -------
        bool
            True if the tag was created, False if skipped.
        """
        tag_name = f"keep/{receiver}/{yyyydoy}"
        try:
            self.repo.create_tag(tag_name, snapshot_id)
        except icechunk.IcechunkError as exc:
            self._logger.warning("keeper_tag_skipped", tag=tag_name, error=str(exc))
            return False
        self._logger.info("keeper_tag_created", tag=tag_name, snapshot=snapshot_id[:8])
        return True

    def plot_commit_graph(
        self,
        branch: str | None = None,
        *,
        plain: bool = False,
    ) -> AncestryGraph:
        """
        Visualize commit history as a graph.

        Delegates to icechunk's native ``repo.ancestry_graph()``. Renders as
        an SVG diagram in Jupyter/marimo notebooks, or as colored text in a
        terminal (``print(store.plot_commit_graph())``).

        Parameters
        ----------
        branch : str, optional
            Restrict the graph to this branch's linear history.
            When omitted, all branches are shown as a tree.
        plain : bool, optional
            Render without ANSI colors or SVG fill colors (useful for CI
            logs or piping to a file).

        Returns
        -------
        AncestryGraph
            Displayable object with ``_repr_svg_()`` for notebooks.
        """
        return self._repo.ancestry_graph(branch=branch, plain=plain)

    def cleanup_stale_branches(
        self, keep_patterns: list[str] | None = None
    ) -> list[str]:
        """
        Delete stale temporary branches (e.g., from failed rechunking).

        Parameters
        ----------
        keep_patterns : list[str] | None
            Patterns to preserve. Default: ["main", "dev"]

        Returns
        -------
        list[str]
            Names of deleted branches
        """
        if keep_patterns is None:
            keep_patterns = ["main", "dev"]

        deleted = []

        for branch in self.repo.list_branches():
            # Keep if matches any pattern
            should_keep = any(pattern in branch for pattern in keep_patterns)

            if not should_keep:
                # Check if it's a temp branch from rechunking
                if "_rechunked_temp" in branch or "_temp" in branch:
                    try:
                        self.repo.delete_branch(branch)
                        deleted.append(branch)
                        self._logger.info(f"Deleted stale branch: {branch}")
                    except Exception as e:
                        self._logger.warning(f"Failed to delete branch {branch}: {e}")

        return deleted

    def delete_branch(self, branch_name: str) -> None:
        """Delete a branch."""
        if branch_name == "main":
            raise ValueError("Cannot delete 'main' branch")

        self.repo.delete_branch(branch_name)
        self._logger.info(f"Deleted branch '{branch_name}'")

    def get_snapshot_info(self, snapshot_id: str) -> dict:
        """
        Get detailed information about a specific snapshot.

        Parameters
        ----------
        snapshot_id : str
            Snapshot ID to inspect

        Returns
        -------
        dict
            Snapshot metadata and statistics
        """
        try:
            snap = self.repo.lookup_snapshot(snapshot_id)
        except Exception as e:
            raise ValueError(f"Snapshot {snapshot_id} not found") from e

        info = {
            "snapshot_id": snap.id,
            "message": snap.message,
            "written_at": snap.written_at,
            "parent_id": snap.parent_id,
        }

        try:
            session = self.repo.readonly_session(snapshot_id=snap.id)
            root = zarr.open(session.store, mode="r")
            info["groups"] = [
                name for name in root.group_keys() if name != RESERVED_GROUP
            ]
            info["arrays"] = list(root.array_keys())
        except Exception as e:
            self._logger.warning(f"Could not inspect snapshot contents: {e}")

        return info

    def compare_snapshots(self, snapshot_id_1: str, snapshot_id_2: str) -> dict:
        """
        Compare two snapshots to see what changed.

        Parameters
        ----------
        snapshot_id_1 : str
            First snapshot (older)
        snapshot_id_2 : str
            Second snapshot (newer)

        Returns
        -------
        dict
            Comparison results showing added/removed/modified groups
        """
        info_1 = self.get_snapshot_info(snapshot_id_1)
        info_2 = self.get_snapshot_info(snapshot_id_2)

        groups_1 = set(info_1.get("groups", []))
        groups_2 = set(info_2.get("groups", []))

        return {
            "snapshot_1": snapshot_id_1[:8],
            "snapshot_2": snapshot_id_2[:8],
            "added_groups": list(groups_2 - groups_1),
            "removed_groups": list(groups_1 - groups_2),
            "common_groups": list(groups_1 & groups_2),
            "time_diff": (info_2["written_at"] - info_1["written_at"]).total_seconds(),
        }

    def maintenance(
        self,
        expire_days: int = 90,
        cleanup_branches: bool = True,
        run_gc: bool = True,
        *,
        dry_run_gc: bool = False,
        delete_expired_branches: bool = False,
        delete_expired_tags: bool = False,
    ) -> dict:
        """
        Run full maintenance on the store: expire, then (optionally) GC.

        Must be invoked manually or from a separately scheduled maintenance
        job: never from the pipeline's own run path, and never on an
        automatic schedule until ``garbage_collect(dry_run=True)`` has been
        checked against the real store and, if using keeper tags,
        ``create_tag()`` cost at scale has been confirmed.
        Not safe during active writes — see ``expire_old_snapshots``/
        ``garbage_collect`` docstrings for the concurrency caveats.

        Parameters
        ----------
        expire_days : int
            Days of snapshot history to keep. Default 90 (weeks-to-months
            cadence, not the previous 7-day default — 7 days is far too
            aggressive for a store under sustained daily writes).
        cleanup_branches : bool
            Remove stale temporary branches.
        run_gc : bool
            Run garbage collection after expiration.
        dry_run_gc : bool, default False
            Pass through to ``garbage_collect`` — report without deleting.
        delete_expired_branches : bool, default False
            Pass through to ``expire_old_snapshots``.
        delete_expired_tags : bool, default False
            Pass through to ``expire_old_snapshots``. **Do not set True**
            if using keeper tags — see ``create_keeper_tag``.

        Returns
        -------
        dict
            Summary of maintenance actions.
        """
        self._logger.info(f"Starting maintenance on {self.store_type}")

        results = {"expired_snapshots": 0, "deleted_branches": [], "gc_summary": None}

        # Expire old snapshots (metadata-only; no objects deleted here)
        expired_ids = self.expire_old_snapshots(
            days=expire_days,
            delete_expired_branches=delete_expired_branches,
            delete_expired_tags=delete_expired_tags,
        )
        results["expired_snapshots"] = len(expired_ids)

        # Cleanup stale branches
        if cleanup_branches:
            deleted_branches = self.cleanup_stale_branches()
            results["deleted_branches"] = deleted_branches

        # Garbage collection — runs exactly once here (previously ran once
        # inside expire_old_snapshots() too, a double-GC-per-call bug).
        if run_gc:
            results["gc_summary"] = self.garbage_collect(
                days=expire_days, dry_run=dry_run_gc
            )

        self._logger.info(f"Maintenance complete: {results}")
        return results


# Factory functions for common use cases
def _cadence_info(epochs: np.ndarray) -> dict[str, Any]:
    """A group's cadence for its description.

    ``cadences`` lists the time ranges at one cadence (each day block has
    its own); ``resolution`` is the finest of them, or None when no day
    has two epochs.
    """
    cadences = cadence_ranges(epochs)
    finest = min((c["cadence_s"] for c in cadences), default=None)
    return {
        "resolution": None if finest is None else f"{finest:g} s",
        "cadences": cadences,
    }


def open_gnss_store(store_path: Path) -> MyIcechunkStore:
    """Open the GNSS store at ``store_path``; never create it.

    A run creates a site's stores when it first writes to them.

    Raises
    ------
    FileNotFoundError
        If no store is at ``store_path``.
    """
    return MyIcechunkStore(store_path=store_path, store_type="gnss_store")


def open_vod_store(store_path: Path) -> MyIcechunkStore:
    """Open the VOD store at ``store_path``; never create it.

    A run creates a site's stores when it first writes to them.

    Raises
    ------
    FileNotFoundError
        If no store is at ``store_path``.
    """
    return MyIcechunkStore(store_path=store_path, store_type="vod_store")


@deprecated(
    "create_gnss_store() is left over from development and will be removed "
    "with the next major version. "
    "It opens a store and never creates one; use open_gnss_store() instead."
)
def create_gnss_store(store_path: Path) -> MyIcechunkStore:
    """Deprecated: use :func:`open_gnss_store`, which this calls."""
    return open_gnss_store(store_path)


@deprecated(
    "create_vod_store() is left over from development and will be removed "
    "with the next major version. "
    "It opens a store and never creates one; use open_vod_store() instead."
)
def create_vod_store(store_path: Path) -> MyIcechunkStore:
    """Deprecated: use :func:`open_vod_store`, which this calls."""
    return open_vod_store(store_path)
