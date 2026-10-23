"""
Auxiliary-data preprocessing pipelines.

Composes the SID-space primitives from :mod:`canvod.readers.preprocessing`
(sv->sid conversion, global SID padding, dtype/encoding normalization) into
the two pipelines specific to auxiliary (SP3/CLK) data: preparing a dataset
for Icechunk storage, and preparing one for interpolation.

The primitives themselves live in ``canvod-readers`` because they only
depend on GNSS signal/constellation definitions (``canvod.readers.gnss_specs``),
not on anything ephemeris- or interpolation-specific -- keeping them here
made ``canvod-readers`` (which calls them from every reader's ``to_ds()``)
depend on ``canvod-auxiliary``, which already depends on ``canvod-readers``,
a genuine import cycle that broke standalone ``canvod-readers`` installs.
"""

import numpy as np
import xarray as xr
from canvod.readers.preprocessing import (
    map_aux_sv_to_sid,
    normalize_sid_dtype,
    pad_to_global_sid,
    strip_fillvalue,
)


def prep_aux_ds(
    aux_ds: xr.Dataset,
    fill_value: float = np.nan,
    aggregate_glonass_fdma: bool = True,
    keep_sids: list[str] | None = None,
) -> xr.Dataset:
    """Preprocess auxiliary dataset before writing to Icechunk.

    Performs complete 4-step preprocessing:
    1. Convert sv → sid dimension
    2. Pad to global sid list (all constellations) or filter to keep_sids
    3. Normalize sid dtype to object
    4. Strip _FillValue attributes

    Parameters
    ----------
    aux_ds : xr.Dataset
        Dataset with 'sv' dimension.
    fill_value : float, default np.nan
        Fill value for missing entries.
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA bands.
    keep_sids : list[str] | None, default None
        List of specific SIDs to keep. If None, keeps all possible SIDs.

    Returns
    -------
    xr.Dataset
        Fully preprocessed dataset ready for Icechunk or interpolation.
    """
    ds = map_aux_sv_to_sid(aux_ds, fill_value, aggregate_glonass_fdma)
    ds = pad_to_global_sid(
        ds, keep_sids=keep_sids, aggregate_glonass_fdma=aggregate_glonass_fdma
    )
    ds = normalize_sid_dtype(ds)
    ds = strip_fillvalue(ds)
    return ds


def preprocess_aux_for_interpolation(
    aux_ds: xr.Dataset,
    fill_value: float = np.nan,
    full_preprocessing: bool = False,
    aggregate_glonass_fdma: bool = True,
) -> xr.Dataset:
    """Preprocess auxiliary dataset before interpolation.

    Converts satellite vehicle (sv) dimension to Signal ID (sid) dimension,
    which is required for matching with RINEX observations after interpolation.

    Parameters
    ----------
    aux_ds : xr.Dataset
        Raw auxiliary dataset with 'sv' dimension.
    fill_value : float, default np.nan
        Fill value for missing entries.
    full_preprocessing : bool, default False
        If True, applies full 4-step preprocessing (pad_to_global_sid,
        normalize_sid_dtype, strip_fillvalue). If False, only converts
        sv → sid (sufficient for interpolation).
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA bands.

    Returns
    -------
    xr.Dataset
        Preprocessed dataset with 'sid' dimension.

    Notes
    -----
    This must be called BEFORE interpolation. The workflow is:
    1. Load raw SP3/CLK data (sv dimension)
    2. Convert sv → sid (this function)
    3. Interpolate to target epochs
    4. Match with RINEX data (sid dimension)

    For most interpolation use cases, `full_preprocessing=False` is sufficient.
    Use `full_preprocessing=True` when preparing data for Icechunk storage.

    Examples
    --------
    >>> # Load raw SP3 data
    >>> sp3_data = Sp3File(...).to_dataset()
    >>> sp3_data.dims
    {'epoch': 96, 'sv': 32}
    >>>
    >>> # Preprocess before interpolation (minimal)
    >>> sp3_preprocessed = preprocess_aux_for_interpolation(sp3_data)
    >>> sp3_preprocessed.dims
    {'epoch': 96, 'sid': 384}
    >>>
    >>> # Preprocess before Icechunk (full)
    >>> sp3_preprocessed = preprocess_aux_for_interpolation(
    ...     sp3_data,
    ...     full_preprocessing=True,
    ... )
    >>> sp3_preprocessed.dims
    {'epoch': 96, 'sid': ~2000}  # Padded to all possible sids
    >>>
    >>> # Now interpolate
    >>> sp3_interp = interpolator.interpolate(sp3_preprocessed, target_epochs)
    """
    if full_preprocessing:
        return prep_aux_ds(aux_ds, fill_value, aggregate_glonass_fdma)
    else:
        return map_aux_sv_to_sid(aux_ds, fill_value, aggregate_glonass_fdma)
