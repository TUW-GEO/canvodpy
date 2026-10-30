"""
Auxiliary-data preprocessing pipelines.

Composes the SID-space primitives from :mod:`canvod.readers.preprocessing`
(sv->sid conversion, global SID padding, dtype/encoding normalization) into
the two pipelines specific to auxiliary (SP3/CLK) data: preparing a dataset
for Icechunk storage, and preparing one for interpolation. The shared aux
cache keeps them once per satellite (:func:`sid_to_sv`, :func:`aux_for_sids`).

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


def sid_to_sv(aux_ds: xr.Dataset) -> xr.Dataset:
    """One value per satellite of a dataset on the ``sid`` dimension.

    The inverse of :func:`map_aux_sv_to_sid`: orbits and clocks are values
    of a satellite, which that function copies to each of its signals.
    Interpolating them per satellite instead of per signal saves the
    copies' work (#573).

    Parameters
    ----------
    aux_ds : xr.Dataset
        Dataset with a ``sid`` dimension whose signals of one satellite
        hold the same values.

    Returns
    -------
    xr.Dataset
        Dataset with an ``sv`` dimension instead of ``sid``; the signal
        coordinates (band, code, frequencies) are dropped.

    Raises
    ------
    ValueError
        If two signals of a satellite hold different values.
    """
    svs = np.array([str(sid).split("|", 1)[0] for sid in aux_ds["sid"].values])
    unique_svs, first, inverse = np.unique(svs, return_index=True, return_inverse=True)
    signal_coords = [
        name
        for name, coord in aux_ds.coords.items()
        if name != "sid" and "sid" in coord.dims
    ]
    per_sv = aux_ds.drop_vars(signal_coords).isel(sid=first)
    for name, var in aux_ds.data_vars.items():
        if "sid" in var.dims and not np.array_equal(
            per_sv[name].isel(sid=inverse).values, var.values, equal_nan=True
        ):
            msg = (
                f"The signals of a satellite hold different values of {name!r}, "
                "so it cannot be stored once per satellite."
            )
            raise ValueError(msg)
    return per_sv.rename({"sid": "sv"}).assign_coords(sv=unique_svs)


def aux_for_sids(aux_ds: xr.Dataset, sids: list[str]) -> xr.Dataset:
    """The auxiliary values of the signals ``sids``.

    Parameters
    ----------
    aux_ds : xr.Dataset
        Auxiliary data on the ``sid`` dimension, or once per satellite
        (``sv`` dimension, see :func:`sid_to_sv`) with the signals they
        hold in the coordinate ``sid``.
    sids : list[str]
        Signals to select; each must be in ``aux_ds["sid"]``.

    Returns
    -------
    xr.Dataset
        The values on the ``sid`` dimension, in the order of ``sids``; a
        satellite's values are copied to each of its signals.
    """
    if "sv" not in aux_ds.dims:
        return aux_ds.sel(sid=sids)
    svs = [str(sid).split("|", 1)[0] for sid in sids]
    return (
        aux_ds.drop_vars("sid")
        .sel(sv=svs)
        .rename({"sv": "sid"})
        .assign_coords(sid=np.array(sids, dtype=object))
    )
