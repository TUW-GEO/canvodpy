"""
Preprocessing wrapper for Icechunk storage.

This module provides the IcechunkPreprocessor class which wraps
preprocessing functions from canvod.readers.preprocessing and
canvod.auxiliary.preprocessing.
"""

from typing import Any

import xarray as xr
from canvod.auxiliary.preprocessing import prep_aux_ds
from canvod.readers.preprocessing import (
    add_future_datavars,
    map_aux_sv_to_sid,
    normalize_sid_dtype,
    pad_to_global_sid,
    strip_fillvalue,
)


class IcechunkPreprocessor:
    """
    Handles preprocessing of RINEX-converted datasets before writing to Icechunk.

    This class wraps functions from canvod.readers.preprocessing and
    canvod.auxiliary.preprocessing.

    Note:
        All methods now delegate to canvod.readers.preprocessing /
        canvod.auxiliary.preprocessing functions.
        The aggregate_glonass_fdma parameter should be passed from configuration.
    """

    @staticmethod
    def map_aux_sv_to_sid(
        aux_ds: xr.Dataset,
        fill_value: float | None = None,
        aggregate_glonass_fdma: bool = True,
    ) -> xr.Dataset:
        """
        Transform auxiliary dataset from sv → sid dimension.

        Delegates to canvod.readers.preprocessing.map_aux_sv_to_sid()

        Parameters
        ----------
        aux_ds : xr.Dataset
            Dataset with 'sv' dimension
        fill_value : float, optional
            Fill value for missing entries (default: np.nan)
        aggregate_glonass_fdma : bool, default True
            Whether to aggregate GLONASS FDMA bands

        Returns
        -------
        xr.Dataset
            Dataset with 'sid' dimension replacing 'sv'
        """
        import numpy as np

        if fill_value is None:
            fill_value = np.nan
        return map_aux_sv_to_sid(aux_ds, fill_value, aggregate_glonass_fdma)

    @staticmethod
    def pad_to_global_sid(
        ds: xr.Dataset,
        keep_sids: list[str] | None = None,
        aggregate_glonass_fdma: bool = True,
    ) -> xr.Dataset:
        """
        Pad dataset so it has all possible SIDs across all constellations.

        Delegates to canvod.readers.preprocessing.pad_to_global_sid()

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with 'sid' dimension
        keep_sids : list[str] | None
            Optional list of specific SIDs to keep
        aggregate_glonass_fdma : bool, default True
            Whether to aggregate GLONASS FDMA bands

        Returns
        -------
        xr.Dataset
            Dataset padded with NaN for missing SIDs
        """
        return pad_to_global_sid(ds, keep_sids, aggregate_glonass_fdma)

    @staticmethod
    def normalize_sid_dtype(ds: xr.Dataset) -> xr.Dataset:
        """
        Ensure sid coordinate uses object dtype.

        Delegates to canvod.readers.preprocessing.normalize_sid_dtype()

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with 'sid' coordinate

        Returns
        -------
        xr.Dataset
            Dataset with sid as object dtype
        """
        return normalize_sid_dtype(ds)

    @staticmethod
    def strip_fillvalue(ds: xr.Dataset) -> xr.Dataset:
        """
        Remove _FillValue attrs/encodings.

        Delegates to canvod.readers.preprocessing.strip_fillvalue()

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to clean

        Returns
        -------
        xr.Dataset
            Dataset with _FillValue attributes removed
        """
        return strip_fillvalue(ds)

    @staticmethod
    def add_future_datavars(
        ds: xr.Dataset,
        var_config: dict[str, dict[str, Any]],
    ) -> xr.Dataset:
        """
        Add placeholder data variables from configuration.

        Delegates to canvod.readers.preprocessing.add_future_datavars()

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to add variables to
        var_config : dict[str, dict[str, Any]]
            Variable configuration dictionary

        Returns
        -------
        xr.Dataset
            Dataset with new variables added
        """
        return add_future_datavars(ds, var_config)

    @staticmethod
    def prep_aux_ds(
        aux_ds: xr.Dataset,
        fill_value: float | None = None,
        aggregate_glonass_fdma: bool = True,
        keep_sids: list[str] | None = None,
    ) -> xr.Dataset:
        """
        Preprocess auxiliary dataset before writing to Icechunk.

        Delegates to canvod.auxiliary.preprocessing.prep_aux_ds()

        Performs complete 4-step preprocessing:
        1. Convert sv → sid dimension
        2. Pad to global sid list or filter to keep_sids
        3. Normalize sid dtype to object
        4. Strip _FillValue attributes

        Parameters
        ----------
        aux_ds : xr.Dataset
            Dataset with 'sv' dimension
        fill_value : float, optional
            Fill value for missing entries (default: np.nan)
        aggregate_glonass_fdma : bool, default True
            Whether to aggregate GLONASS FDMA bands
        keep_sids : list[str] | None, default None
            List of specific SIDs to keep. If None, keeps all possible SIDs.

        Returns
        -------
        xr.Dataset
            Fully preprocessed dataset ready for Icechunk
        """
        import numpy as np

        if fill_value is None:
            fill_value = np.nan
        return prep_aux_ds(aux_ds, fill_value, aggregate_glonass_fdma, keep_sids)
