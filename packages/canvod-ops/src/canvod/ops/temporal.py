"""Temporal aggregation operation."""

import time
from typing import Any

import numpy as np
import pandas as pd
import structlog
import xarray as xr

from canvod.ops.base import Op, OpResult

logger = structlog.get_logger(__name__)

#: canvodpy readers mark a missing integer value (e.g. no LLI recorded) with -1.
INTEGER_MISSING = -1

#: Elements of the (bin, epoch in bin, signal) block aggregated at once; bounds
#: the memory of one step independently of the size of the day.
_BLOCK_ELEMENTS = 2**23


def _bin_starts(epochs: np.ndarray, freq_ns: int) -> np.ndarray:
    """Start of the bin of each epoch; bins are aligned to 1970-01-01 00:00."""
    ns = np.asarray(epochs, dtype="datetime64[ns]").astype(np.int64)
    return (ns - ns % freq_ns).astype("datetime64[ns]")


def _sampling_seconds(epochs: np.ndarray) -> float | None:
    """Most common spacing of the distinct epochs in seconds (None below two)."""
    steps = np.diff(np.unique(epochs)).astype(np.int64)
    if steps.size == 0:
        return None
    values, counts = np.unique(steps, return_counts=True)
    return int(values[np.argmax(counts)]) / 1e9


def missing_value(name: str, var: xr.Variable) -> Any:
    """Value that marks a missing observation in ``var``.

    NaN for floating-point variables, the ``_FillValue`` attribute (else -1,
    the readers' convention) for integer variables, None for strings.

    Raises
    ------
    TypeError
        For any other data type, which has no defined missing value.
    """
    kind = var.dtype.kind
    if kind == "f":
        return np.nan
    if kind == "i":
        return var.attrs.get("_FillValue", INTEGER_MISSING)
    if kind in "OUT":
        return None
    msg = f"Variable {name!r} has dtype {var.dtype}, which has no missing value"
    raise TypeError(msg)


def _reduce(cube: np.ndarray, method: str) -> np.ndarray:
    """Mean or median over axis 1 of a ``(bin, slot, signal)`` block, NaN skipped.

    A bin without any value gives NaN.
    """
    valid = ~np.isnan(cube)
    count = valid.sum(axis=1)
    if method == "mean":
        total = np.where(valid, cube, 0.0).sum(axis=1)
        with np.errstate(invalid="ignore"):
            return total / count
    # NaN sorts last, so the valid values of a bin come first.
    ordered = np.sort(cube, axis=1)
    lower = np.take_along_axis(ordered, np.maximum(count - 1, 0)[:, None] // 2, 1)
    upper = np.take_along_axis(ordered, (count // 2)[:, None], 1)
    return (lower[:, 0] + upper[:, 0]) / 2


#: Which value of a bin an integer variable takes.
INTEGER_METHODS = ("first", "last", "middle")


def _pick(cube: np.ndarray, method: str) -> np.ndarray:
    """First, last or middle value over axis 1 of a ``(bin, slot, signal)`` block.

    Integer variables are flags and codes (LLI, SSI, receiver status), which
    have no mean: each bin takes one of its values, in time order. Missing
    values (NaN) are skipped; of an even number of values, ``"middle"`` takes
    the earlier of the two middle ones. A bin without any value gives NaN.
    """
    valid = ~np.isnan(cube)
    count = valid.sum(axis=1)
    if method == "first":
        rank = np.ones_like(count)
    elif method == "last":
        rank = count
    else:
        rank = (count - 1) // 2 + 1
    position = np.argmax(valid & (np.cumsum(valid, axis=1) == rank[:, None]), axis=1)
    picked = np.take_along_axis(cube, position[:, None], 1)[:, 0]
    return np.where(count > 0, picked, np.nan)


def _reduce_angle(cube: np.ndarray, method: str) -> np.ndarray:
    """Like :func:`_reduce` for an angle in radians, relative to the bin's first value."""
    first = np.argmax(~np.isnan(cube), axis=1)
    ref = np.take_along_axis(cube, first[:, None], 1)
    relative = (cube - ref + np.pi) % (2 * np.pi) - np.pi
    return (_reduce(relative, method) + ref[:, 0]) % (2 * np.pi)


class TemporalAggregate(Op):
    """Aggregate an ``(epoch, sid)`` dataset to regular time bins.

    Each bin starts at a multiple of ``freq`` counted from 00:00 of the day
    and is labeled with its start. Every variable along ``epoch`` is
    aggregated per signal; the others pass unchanged. Missing values (NaN,
    -1 for integers) are ignored; a bin without any value stays missing.
    Floating-point variables take the ``method`` of their values in the bin.
    Integer variables (flags and codes such as LLI and SSI) cannot be
    combined: they take one of their values in the bin, the first, last or
    middle one in time order (``integer_method``). The azimuth
    ``phi`` (radians) is aggregated as an angle, so a satellite crossing
    north (0 rad) does not average to south: each value is taken relative
    to the first value of its bin.

    The result has the variables, dimensions, data types, attributes and
    encodings of the input. The input sampling and the bin length (in
    seconds) are reported in the ``result`` of the returned
    :class:`~canvod.ops.base.OpResult`, which the stores keep in their log
    book.

    Parameters
    ----------
    freq : str
        Bin length as a pandas offset alias (e.g. ``"1min"``, ``"30s"``).
    method : str
        Aggregation method of floating-point variables: ``"mean"`` or
        ``"median"``.
    integer_method : str
        Value of the bin integer variables take: ``"first"``, ``"last"`` or
        ``"middle"``.
    """

    def __init__(
        self, freq: str = "1min", method: str = "mean", *, integer_method: str
    ) -> None:
        if method not in ("mean", "median"):
            msg = f"Unsupported aggregation method: {method!r}"
            raise ValueError(msg)
        if integer_method not in INTEGER_METHODS:
            msg = (
                f"Unsupported integer method: {integer_method!r}; integer "
                f"variables take one value of the bin, one of {INTEGER_METHODS}"
            )
            raise ValueError(msg)
        self._freq = freq
        self._method = method
        self._integer_method = integer_method

    @property
    def name(self) -> str:
        return "temporal_aggregate"

    @property
    def settings(self) -> dict[str, Any]:
        return {
            "freq": self._freq,
            "method": self._method,
            "integer_method": self._integer_method,
        }

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]:
        t0 = time.perf_counter()
        params = self.settings
        input_shape = {str(k): int(v) for k, v in dict(ds.sizes).items()}

        freq_ns = int(pd.tseries.frequencies.to_offset(self._freq).nanos)
        epochs = np.asarray(ds["epoch"].values, dtype="datetime64[ns]")
        bins = _bin_starts(epochs, freq_ns)
        sampling = {
            "input_sampling_s": _sampling_seconds(epochs),
            "output_sampling_s": freq_ns / 1e9,
        }

        # --- Nothing to do if every epoch already is the start of its own bin ---
        if np.array_equal(bins, epochs) and len(np.unique(bins)) == len(bins):
            logger.info("temporal_aggregation_skipped", requested=self._freq)
            result = OpResult(
                op_name=self.name,
                parameters=params,
                input_shape=input_shape,
                output_shape=input_shape,
                duration_seconds=time.perf_counter() - t0,
                notes=f"no-op: every epoch is already the start of a {self._freq} bin",
                result={**sampling, "aggregated": False},
            )
            return ds, result

        # --- Bin and slot (position within the bin, in time order) per epoch ---
        order = np.argsort(epochs, kind="stable")
        if np.array_equal(order, np.arange(len(order))):
            order = None
        sorted_bins = bins if order is None else bins[order]
        new_epochs, first, counts = np.unique(
            sorted_bins, return_index=True, return_counts=True
        )
        bin_of = np.repeat(np.arange(len(new_epochs)), counts)
        slot = np.arange(len(sorted_bins)) - first[bin_of]
        bounds = np.append(first, len(sorted_bins))

        variables: dict[str, xr.Variable] = {}
        for name, var in ds.variables.items():
            name = str(name)
            if name == "epoch":
                variables[name] = xr.Variable(
                    var.dims, new_epochs, var.attrs, var.encoding
                )
            elif "epoch" in var.dims:
                variables[name] = self._aggregate(
                    name, var, order, bin_of, slot, bounds, int(counts.max())
                )
            else:
                variables[name] = var

        out = xr.Dataset(
            {name: variables[str(name)] for name in ds.data_vars},
            coords={name: variables[str(name)] for name in ds.coords},
            attrs=dict(ds.attrs),
        )
        out.encoding = dict(ds.encoding)

        duration = time.perf_counter() - t0
        output_shape = {str(k): int(v) for k, v in dict(out.sizes).items()}

        logger.info(
            "temporal_aggregation_complete",
            input_shape=input_shape,
            output_shape=output_shape,
            duration_s=round(duration, 2),
        )
        result = OpResult(
            op_name=self.name,
            parameters=params,
            input_shape=input_shape,
            output_shape=output_shape,
            duration_seconds=duration,
            result={**sampling, "aggregated": True},
        )
        return out, result

    def _aggregate(
        self,
        name: str,
        var: xr.Variable,
        order: np.ndarray | None,
        bin_of: np.ndarray,
        slot: np.ndarray,
        bounds: np.ndarray,
        width: int,
    ) -> xr.Variable:
        """Aggregate one variable along ``epoch``, block of bins by block."""
        missing = missing_value(name, var)
        if missing is None:
            msg = f"Variable {name!r} holds strings and cannot be aggregated"
            raise TypeError(msg)
        is_int = var.dtype.kind == "i"
        if is_int:
            reduce, method = _pick, self._integer_method
        else:
            reduce = _reduce_angle if name == "phi" else _reduce
            method = self._method

        axis = var.dims.index("epoch")
        values = np.moveaxis(np.asarray(var.values), axis, 0)
        rest = values.shape[1:]
        values = values.reshape(values.shape[0], -1)
        if order is not None:
            values = values[order]

        n_bins, n_cols = len(bounds) - 1, values.shape[1]
        reduced = np.empty((n_bins, n_cols), dtype=np.float64)
        step = max(1, _BLOCK_ELEMENTS // max(1, width * n_cols))
        for b0 in range(0, n_bins, step):
            b1 = min(b0 + step, n_bins)
            e0, e1 = bounds[b0], bounds[b1]
            block = values[e0:e1].astype(np.float64)
            if is_int:
                block[values[e0:e1] == missing] = np.nan
            cube = np.full((b1 - b0, width, n_cols), np.nan)
            cube[bin_of[e0:e1] - b0, slot[e0:e1]] = block
            reduced[b0:b1] = reduce(cube, method)

        if is_int:
            reduced = np.where(np.isnan(reduced), missing, reduced)
        data = np.moveaxis(reduced.astype(var.dtype).reshape(n_bins, *rest), 0, axis)
        return xr.Variable(var.dims, data, var.attrs, var.encoding)


def temporal_aggregate(
    ds: xr.Dataset,
    freq: str = "1min",
    method: str = "mean",
    *,
    integer_method: str,
) -> xr.Dataset:
    """Convenience function: temporally aggregate a dataset.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset with ``(epoch, sid)`` dimensions.
    freq : str
        Target frequency.
    method : str
        ``"mean"`` or ``"median"``, for floating-point variables.
    integer_method : str
        ``"first"``, ``"last"`` or ``"middle"``, for integer variables.

    Returns
    -------
    xr.Dataset
        Aggregated dataset.
    """
    op = TemporalAggregate(freq=freq, method=method, integer_method=integer_method)
    out, _ = op(ds)
    return out
