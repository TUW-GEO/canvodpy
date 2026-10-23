"""
SID-space preprocessing utilities for GNSS datasets.

Handles conversion of raw per-satellite (sv) data to per-signal (sid)
dimension, global SID padding, and related dataset normalization steps
needed before matching auxiliary data (SP3, CLK) with reader output or
writing to Icechunk.
"""

from collections.abc import Hashable
from typing import Any, overload

import numpy as np
import xarray as xr

from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper

# ---------------------------------------------------------------------------
# Per-process SID issue accumulators
# ---------------------------------------------------------------------------
# Each worker subprocess accumulates SID issues during pad_to_global_sid()
# calls. The main process retrieves them via flush_sid_accumulators() at the
# end of each file's processing, then aggregates across all files.
_accumulated_not_in_global_space: set[str] = set()
_accumulated_dropped_by_filter: set[str] = set()


def flush_sid_accumulators() -> dict[str, list[str]]:
    """Return accumulated SID issues and clear the module-level accumulators.

    Called once per RINEX file at the end of ``preprocess_with_hermite_aux``.
    The returned dict is aggregated by the main process across all files for
    a receiver and logged once per receiver run.

    Returns
    -------
    dict[str, list[str]]
        Keys: ``"not_in_global_space"``, ``"dropped_by_filter"``.
    """
    global _accumulated_not_in_global_space, _accumulated_dropped_by_filter
    result: dict[str, list[str]] = {
        "not_in_global_space": sorted(_accumulated_not_in_global_space),
        "dropped_by_filter": sorted(_accumulated_dropped_by_filter),
    }
    _accumulated_not_in_global_space = set()
    _accumulated_dropped_by_filter = set()
    return result


def reset_sid_accumulators() -> None:
    """Clear the module-level SID-issue accumulators without reading them.

    Call at the start of a file-processing unit (before any
    ``pad_to_global_sid()`` calls it will make), not just at the end via
    ``flush_sid_accumulators()``. The accumulators are only ever drained by
    whichever caller happens to flush next -- a step that itself calls
    ``pad_to_global_sid()`` without a matching flush (e.g. aux/ephemeris
    padding during Phase 1) leaves its entries to bleed into that later,
    unrelated flush. Resetting on entry makes each unit's result depend
    only on its own work, regardless of what an earlier unit left behind.
    """
    global _accumulated_not_in_global_space, _accumulated_dropped_by_filter
    _accumulated_not_in_global_space = set()
    _accumulated_dropped_by_filter = set()


def create_sv_to_sid_mapping(
    svs: list[str], aggregate_glonass_fdma: bool = True
) -> dict[str, list[str]]:
    """Build mapping from each SV to its possible SIDs.

    Builds all SIDs from known band/code combinations.

    Parameters
    ----------
    svs : list[str]
        List of space vehicles (e.g., ["G01", "E02"]).
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA bands.

    Returns
    -------
    dict[str, list[str]]
        Mapping from sv → list of SIDs.
    """
    mapper = SignalIDMapper(aggregate_glonass_fdma=aggregate_glonass_fdma)
    systems = {
        "G": GPS(),
        "E": GALILEO(),
        "R": GLONASS(aggregate_fdma=aggregate_glonass_fdma),
        "C": BEIDOU(),
        "I": IRNSS(),
        "S": SBAS(),
        "J": QZSS(),
    }

    sv_to_sids: dict[str, list[str]] = {}
    for sv in svs:
        sys_letter = sv[0]
        if sys_letter not in systems:
            continue

        system = systems[sys_letter]
        sids = []
        if sys_letter in mapper.SYSTEM_BANDS:
            for _, band in mapper.SYSTEM_BANDS[sys_letter].items():
                codes = system.BAND_CODES.get(band, ["X"])
                sids.extend(f"{sv}|{band}|{code}" for code in codes)

        sv_to_sids[sv] = sorted(sids)

    return sv_to_sids


def map_aux_sv_to_sid(
    aux_ds: xr.Dataset,
    fill_value: float = np.nan,
    aggregate_glonass_fdma: bool = True,
) -> xr.Dataset:
    """Transform auxiliary dataset from sv → sid dimension.

    Each sv in the dataset is expanded to all its possible SIDs.
    Values are replicated across SIDs for the same satellite.

    Parameters
    ----------
    aux_ds : xr.Dataset
        Dataset with 'sv' dimension.
    fill_value : float, default np.nan
        Fill value for missing entries.
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA bands.

    Returns
    -------
    xr.Dataset
        Dataset with 'sid' dimension replacing 'sv'.
    """
    svs = aux_ds["sv"].values.tolist()
    sv_to_sids = create_sv_to_sid_mapping(svs, aggregate_glonass_fdma)
    all_sids = sorted({sid for sv in svs for sid in sv_to_sids.get(sv, [])})

    new_data_vars = {}
    for name, arr in aux_ds.data_vars.items():
        if "sv" in arr.dims:
            sv_dim = arr.dims.index("sv")
            new_shape = list(arr.shape)
            new_shape[sv_dim] = len(all_sids)
            expanded = np.full(new_shape, fill_value, dtype=arr.dtype)

            for sv_idx, sv in enumerate(svs):
                for sid in sv_to_sids.get(sv, []):
                    sid_idx = all_sids.index(sid)
                    if sv_dim == 0:
                        expanded[sid_idx, ...] = arr.values[sv_idx, ...]
                    elif sv_dim == 1:
                        expanded[..., sid_idx] = arr.values[..., sv_idx]
                    else:
                        idx_new = tuple(
                            sid_idx if i == sv_dim else slice(None)
                            for i in range(len(new_shape))
                        )
                        idx_old = tuple(
                            sv_idx if i == sv_dim else slice(None)
                            for i in range(len(arr.shape))
                        )
                        expanded[idx_new] = arr.values[idx_old]

            new_dims = list(arr.dims)
            new_dims[sv_dim] = "sid"
            new_data_vars[name] = (tuple(new_dims), expanded, arr.attrs)
        else:
            new_data_vars[name] = arr

    # Coordinates
    new_coords = {
        **{k: v for k, v in aux_ds.coords.items() if k != "sv"},
        "sid": ("sid", all_sids),
    }

    return xr.Dataset(new_data_vars, coords=new_coords, attrs=aux_ds.attrs.copy())


def pad_to_global_sid(
    ds: xr.Dataset,
    keep_sids: list[str] | None = None,
    aggregate_glonass_fdma: bool = True,
) -> xr.Dataset:
    """Pad dataset so it has all possible SIDs across all constellations.
    Ensures consistent sid dimension for appending to Icechunk.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with 'sid' dimension.
    keep_sids : list[str] | None
        Optional list of specific SIDs to keep. If None, keeps all.
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA bands.

    Returns
    -------
    xr.Dataset
        Dataset padded for missing SIDs: floating-point variables with NaN,
        integer variables with their ``_FillValue`` attribute, so they keep
        their dtype.

    Raises
    ------
    ValueError
        If an integer data variable has no ``_FillValue`` attribute.
    """
    mapper = SignalIDMapper(aggregate_glonass_fdma=aggregate_glonass_fdma)
    systems = {
        "G": GPS(),
        "E": GALILEO(),
        "R": GLONASS(aggregate_fdma=aggregate_glonass_fdma),
        "C": BEIDOU(),
        "I": IRNSS(),
        "S": SBAS(),
        "J": QZSS(),
    }

    # Generate all possible SIDs
    sids = [
        f"{sv}|{band}|{code}"
        for sys_letter, bands in mapper.SYSTEM_BANDS.items()
        for _, band in bands.items()
        for sv in systems[sys_letter].svs
        for code in systems[sys_letter].BAND_CODES.get(band, ["X"])
    ]
    sids = sorted(sids)
    global_sid_set = set(sids)

    # Accumulate SIDs that fall outside the constellation model's universe.
    # These are logged once per receiver run by the pipeline (not per file).
    if "sid" in ds.coords:
        ds_sids = set(ds.sid.values)
        unknown_sids = ds_sids - global_sid_set
        if unknown_sids:
            _accumulated_not_in_global_space.update(unknown_sids)

    # Filter to keep_sids if provided
    if keep_sids is not None and len(keep_sids) > 0:
        keep_set = set(keep_sids)
        sids_before = set(sids)
        sids = sorted(sids_before.intersection(keep_set))

        # Accumulate observed SIDs dropped by keep_sids filter.
        # Logged once per receiver run by the pipeline (not per file).
        if "sid" in ds.coords:
            ds_sids = set(ds.sid.values)
            dropped_by_filter = (ds_sids & sids_before) - keep_set
            if dropped_by_filter:
                _accumulated_dropped_by_filter.update(dropped_by_filter)

    ds_padded = ds.reindex(
        {"sid": np.array(sids, dtype=object)}, fill_value=_pad_fill_values(ds)
    )
    return _fill_sid_coords_from_sid_strings(ds_padded, mapper)


def _pad_fill_values(ds: xr.Dataset) -> dict[Hashable, Any]:
    """Return the fill value of each data variable for ``reindex``.

    A NaN fill would turn integer variables into float64, so they are
    padded with their ``_FillValue`` attribute instead.
    """
    fills: dict[Hashable, Any] = {}
    for name, var in ds.data_vars.items():
        if np.issubdtype(var.dtype, np.integer):
            if "_FillValue" not in var.attrs:
                msg = (
                    f"Integer variable {name!r} has no _FillValue attribute, "
                    "so it cannot be padded without changing its dtype."
                )
                raise ValueError(msg)
            fills[name] = var.attrs["_FillValue"]
        else:
            fills[name] = np.nan
    return fills


def _fill_sid_coords_from_sid_strings(
    ds: xr.Dataset, mapper: SignalIDMapper
) -> xr.Dataset:
    """Fill NaN sid-level coords by parsing SID strings.

    After ``reindex``, newly-added SIDs have NaN for ``sv``, ``band``,
    ``code``, ``system``, and frequency coords.  These are fully
    derivable from the SID string (``"SV|Band|Code"``) plus the signal
    spec lookup tables.

    This ensures SBF and RINEX datasets have identical coord coverage
    after global SID padding.
    """
    sid_vals = ds.sid.values

    # Check if any sid-level coords need filling
    sid_coords = {"sv", "system", "band", "code", "freq_center", "freq_min", "freq_max"}
    coords_to_fill = [c for c in sid_coords if c in ds.coords]
    if not coords_to_fill:
        return ds

    # Check if there are actually NaN values to fill
    has_nans = False
    for coord_name in coords_to_fill:
        arr = ds.coords[coord_name].values
        if arr.dtype.kind in ("U", "O"):  # string
            has_nans = any(
                v is None
                or (isinstance(v, float) and np.isnan(v))
                or (isinstance(v, str) and v == "")
                for v in arr
            )
        else:  # numeric
            has_nans = np.any(np.isnan(arr))
        if has_nans:
            break

    if not has_nans:
        return ds

    # Parse all SIDs and build complete coord arrays
    sv_arr = []
    system_arr = []
    band_arr = []
    code_arr = []
    freq_center_arr = []
    freq_min_arr = []
    freq_max_arr = []

    for sid in sid_vals:
        parts = str(sid).split("|")
        sv = parts[0] if len(parts) > 0 else ""
        bnd = parts[1] if len(parts) > 1 else ""
        cod = parts[2] if len(parts) > 2 else ""

        sv_arr.append(sv)
        system_arr.append(sv[0] if sv else "")
        band_arr.append(bnd)
        code_arr.append(cod)

        props = mapper.BAND_PROPERTIES.get(bnd, {})
        fc = props.get("freq", np.nan)
        bw = props.get("bandwidth", 0.0)
        fc_val = float(fc) if fc is not None else np.nan
        bw_val = float(bw) if bw is not None else 0.0
        freq_center_arr.append(fc_val)
        freq_min_arr.append(fc_val - bw_val / 2 if not np.isnan(fc_val) else np.nan)
        freq_max_arr.append(fc_val + bw_val / 2 if not np.isnan(fc_val) else np.nan)

    # Only update coords that exist in the dataset
    updates: dict[str, Any] = {}
    coord_map = {
        "sv": sv_arr,
        "system": system_arr,
        "band": band_arr,
        "code": code_arr,
        "freq_center": freq_center_arr,
        "freq_min": freq_min_arr,
        "freq_max": freq_max_arr,
    }
    for name, values in coord_map.items():
        if name in ds.coords:
            old = ds.coords[name]
            arr = np.asarray(values)
            # Preserve the original coordinate dtype
            if old.dtype != arr.dtype:
                if old.dtype.kind == "f":
                    arr = arr.astype(old.dtype)
                elif old.dtype.kind == "O" or str(old.dtype).startswith("StringDType"):
                    # Keep string coords as object (stable Zarr V3 variable_length_utf8)
                    arr = arr.astype(object)
            updates[name] = xr.DataArray(
                arr,
                dims=["sid"],
                attrs=old.attrs,
            )

    return ds.assign_coords(updates)


@overload
def normalize_sid_dtype(ds: xr.Dataset) -> xr.Dataset: ...


@overload
def normalize_sid_dtype(ds: None) -> None: ...


def normalize_sid_dtype(ds: xr.Dataset | None) -> xr.Dataset | None:
    """Ensure sid coordinate uses object dtype.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with 'sid' coordinate.

    Returns
    -------
    xr.Dataset
        Dataset with sid as object dtype.
    """
    if ds is None:
        return ds
    if "sid" in ds.coords and ds.sid.dtype.kind == "U":
        ds = ds.assign_coords(
            sid=xr.Variable("sid", ds.sid.values.astype(object), ds.sid.attrs)
        )
    return ds


@overload
def strip_fillvalue(ds: xr.Dataset) -> xr.Dataset: ...


@overload
def strip_fillvalue(ds: None) -> None: ...


def strip_fillvalue(ds: xr.Dataset | None) -> xr.Dataset | None:
    """Remove _FillValue attrs/encodings.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to clean.

    Returns
    -------
    xr.Dataset
        Dataset with _FillValue attributes removed.
    """
    if ds is None:
        return ds
    for v in ds.data_vars:
        ds[v].attrs.pop("_FillValue", None)
        ds[v].encoding.pop("_FillValue", None)
    return ds


def add_future_datavars(
    ds: xr.Dataset, var_config: dict[str, dict[str, Any]]
) -> xr.Dataset:
    """Add placeholder data variables from a configuration dictionary.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to add variables to.
    var_config : dict[str, dict[str, Any]]
        Configuration dict with structure:
        {
            "var_name": {
                "fill_value": value,
                "dtype": numpy dtype,
                "attrs": {attribute dict}
            }
        }

    Returns
    -------
    xr.Dataset
        Dataset with new variables added.
    """
    n_epochs, n_sids = ds.sizes["epoch"], ds.sizes["sid"]
    for name, cfg in var_config.items():
        if name not in ds:
            arr = np.full((n_epochs, n_sids), cfg["fill_value"], dtype=cfg["dtype"])
            ds[name] = (("epoch", "sid"), arr, cfg["attrs"])
    return ds
