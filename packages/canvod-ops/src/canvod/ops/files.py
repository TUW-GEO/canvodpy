"""Apply the configured operations to consecutive files of one receiver."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import structlog
import xarray as xr

from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingConfig,
    preprocessing_record,
)
from canvod.ops.base import software_versions
from canvod.ops.registry import build_default_pipeline
from canvod.ops.temporal import missing_value

logger = structlog.get_logger(__name__)


def preprocess_files[K](
    parts: Sequence[tuple[K, xr.Dataset]],
    config: PreprocessingConfig | None,
) -> list[tuple[K, xr.Dataset]]:
    """Apply ``processing.preprocessing`` to the files of one receiver and day.

    The files are joined along ``epoch`` before the operations run, so a time
    bin that spans two files is aggregated from the observations of both.
    The result is split back into one dataset per file: each bin goes to the
    file that holds its earliest observation. Every dataset keeps its own
    attributes (e.g. the file hash) and carries the preprocessing record of
    the day (see ``canvod.config.models.preprocessing_record``) under
    :data:`~canvod.config.models.PREPROCESSING_ATTR`, also when nothing is
    applied. The record is only carried in memory: the stores move it into
    the ``preprocessing`` column of their log book and never write it into
    the data.

    Parameters
    ----------
    parts : Sequence[tuple[K, xr.Dataset]]
        ``(key, dataset)`` per file, e.g. ``(path, dataset)``; datasets have
        ``(epoch, sid)`` dimensions.
    config : PreprocessingConfig | None
        The ``processing.preprocessing`` section; ``None`` applies nothing.

    Returns
    -------
    list[tuple[K, xr.Dataset]]
        ``(key, dataset)`` per file, in time order. A file whose observations
        all fall into bins of an earlier file is left out.
    """
    pipeline = build_default_pipeline(config) if config is not None else None
    if pipeline is None or len(pipeline) == 0:
        record = preprocessing_record([], software_versions(["canvod-ops"]))
        return [
            (key, ds.assign_attrs({PREPROCESSING_ATTR: record})) for key, ds in parts
        ]

    ordered = sorted(
        (p for p in parts if p[1].sizes.get("epoch", 0) > 0),
        key=lambda p: p[1]["epoch"].values.min(),
    )
    if not ordered:
        return []

    datasets = [ds for _, ds in ordered]
    joined = _join_along_epoch(datasets)
    source = np.repeat(np.arange(len(datasets)), [ds.sizes["epoch"] for ds in datasets])
    epochs = joined["epoch"].values

    out, result = pipeline(joined)
    record = result.record()

    # Owner of each output epoch (a bin start): the file with the earliest
    # observation at or after that bin start, i.e. the bin's first observation.
    order = np.argsort(epochs, kind="stable")
    first = np.searchsorted(epochs[order], out["epoch"].values, side="left")
    owner = source[order][first]

    split: list[tuple[K, xr.Dataset]] = []
    for i, (key, ds) in enumerate(ordered):
        part = out.isel(epoch=np.flatnonzero(owner == i))
        if part.sizes["epoch"] == 0:
            logger.warning(
                "preprocessing_file_absorbed",
                file=str(key),
                hint="all observations fall into time bins of an earlier file",
            )
            continue
        attrs = {**ds.attrs, PREPROCESSING_ATTR: record}
        split.append((key, part.assign_attrs(attrs)))
    return split


def _join_along_epoch(datasets: Sequence[xr.Dataset]) -> xr.Dataset:
    """Join the files of one receiver along ``epoch`` into one dataset.

    Files may observe different signals: the result holds the union of their
    ``sid`` values (in the files' order if all files have the same), and a
    signal a file lacks is missing (NaN, -1 for integers) in that file's
    epochs. ``sid``-only coordinates come from the first file that has the
    signal. Variables keep the dimensions, data type, attributes and encoding
    of the first file that has them. Built in preallocated arrays, without
    ``xr.concat``.

    Raises
    ------
    ValueError
        If a variable has a dimension other than ``epoch`` and ``sid``.
    """
    sid_arrays = [np.asarray(ds["sid"].values) for ds in datasets]
    columns: list[slice | np.ndarray]
    if all(np.array_equal(s, sid_arrays[0]) for s in sid_arrays[1:]):
        sids = sid_arrays[0]
        columns = [slice(None)] * len(datasets)
    else:
        sids = np.array(sorted(set().union(*sid_arrays)), dtype=sid_arrays[0].dtype)
        lookup = {sid: i for i, sid in enumerate(sids)}
        columns = [np.array([lookup[sid] for sid in arr]) for arr in sid_arrays]
    sizes = [ds.sizes["epoch"] for ds in datasets]
    offsets = np.concatenate([[0], np.cumsum(sizes)])
    length = {"epoch": int(offsets[-1]), "sid": len(sids)}

    variables: dict[str, xr.Variable] = {}
    data_vars: list[str] = []
    coords: list[str] = []
    for ds in datasets:
        data_vars += [str(n) for n in ds.data_vars if str(n) not in data_vars]
        coords += [str(n) for n in ds.coords if str(n) not in coords]

    for name in coords + data_vars:
        holders = [
            (i, ds.variables[name])
            for i, ds in enumerate(datasets)
            if name in ds.variables
        ]
        template = holders[0][1]
        dims = template.dims
        if name == "epoch":
            data = np.concatenate([np.asarray(v.values) for _, v in holders])
        elif name == "sid":
            data = sids
        elif not dims:
            data = template.values
        else:
            if not set(dims) <= {"epoch", "sid"}:
                msg = (
                    f"Variable {name!r} has dimensions {dims}; only 'epoch' "
                    "and 'sid' can be joined"
                )
                raise ValueError(msg)
            dtype = np.result_type(*(v.dtype for _, v in holders))
            data = np.full(
                tuple(length[str(d)] for d in dims),
                missing_value(name, template),
                dtype=dtype,
            )
            # Reversed: the first file that has a value wins.
            for i, var in reversed(holders):
                index = tuple(
                    slice(offsets[i], offsets[i + 1]) if d == "epoch" else columns[i]
                    for d in dims
                )
                data[index] = var.values
        variables[name] = xr.Variable(dims, data, template.attrs, template.encoding)

    return xr.Dataset(
        {n: variables[n] for n in data_vars},
        coords={n: variables[n] for n in coords},
    )
