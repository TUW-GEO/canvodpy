"""Dataset temporal matching for auxiliary data alignment.

Aligns auxiliary datasets (ephemeris, clock) to reference RINEX datasets
using appropriate interpolation strategies.
"""

import warnings

import numpy as np
import xarray as xr

from canvod.auxiliary.interpolation import create_interpolator_from_attrs


class DatasetMatcher:
    """Match auxiliary datasets to a reference RINEX dataset temporally.

    Handles temporal alignment of datasets with different sampling rates
    using appropriate interpolation strategies. The reference dataset
    (typically RINEX observations) remains unchanged while auxiliary
    datasets are interpolated to match its epochs.

    The matcher:
    1. Validates all datasets have required dimensions (epoch, sid)
    2. Determines relative temporal resolutions
    3. Applies appropriate interpolation:
       - Higher resolution aux → nearest neighbor
       - Lower resolution aux → specialized interpolator from metadata

    Examples
    --------
    >>> from canvod.auxiliary.matching import DatasetMatcher
    >>>
    >>> matcher = DatasetMatcher()
    >>> matched = matcher.match_datasets(
    ...     rinex_ds,
    ...     ephemerides=sp3_data,
    ...     clock=clk_data
    ... )
    >>>
    >>> # Auxiliary datasets now aligned to RINEX epochs
    >>> len(matched['ephemerides'].epoch) == len(rinex_ds.epoch)
    True
    >>> len(matched['clock'].epoch) == len(rinex_ds.epoch)
    True

    Notes
    -----
    - Reference dataset should be the RINEX observations
    - Auxiliary datasets should have 'interpolator_config' in attrs
    - If no interpolator config, falls back to nearest neighbor
    - Temporal distance is tracked for quality assessment
    """

    def match_datasets(
        self, reference_ds: xr.Dataset, **aux_datasets: xr.Dataset
    ) -> dict[str, xr.Dataset]:
        """Match auxiliary datasets to reference dataset epochs.

        Parameters
        ----------
        reference_ds : xr.Dataset
            Primary dataset (usually RINEX observations) that defines
            the target epoch timeline. This dataset remains unchanged.
        **aux_datasets : dict[str, xr.Dataset]
            Named auxiliary datasets to align to reference epochs.
            Keys become the names in the returned dict.
            Example: ephemerides=sp3_data, clock=clk_data

        Returns
        -------
        dict[str, xr.Dataset]
            Dictionary of matched auxiliary datasets, all aligned to
            reference_ds.epoch. Keys match the input **aux_datasets keys.

        Raises
        ------
        ValueError
            - If no auxiliary datasets provided
            - If datasets missing required dimensions
            - If interpolation config missing (warns, doesn't raise)

        Examples
        --------
        >>> matcher = DatasetMatcher()
        >>> matched = matcher.match_datasets(
        ...     rinex_ds,
        ...     ephemerides=sp3_data,
        ...     clock=clk_data
        ... )
        >>> matched.keys()
        dict_keys(['ephemerides', 'clock'])
        """
        self._validate_inputs(reference_ds, aux_datasets)

        ref_interval = self._get_temporal_interval(reference_ds)
        matched = self._match_temporal_resolution(
            reference_ds, ref_interval, aux_datasets
        )

        return matched

    def _validate_inputs(
        self,
        reference_ds: xr.Dataset,
        aux_datasets: dict[str, xr.Dataset],
    ) -> None:
        """Validate input datasets.

        Checks:
        1. At least one auxiliary dataset provided
        2. All datasets have required dimensions (epoch, sid)
        3. Interpolation configuration available (warns if missing)

        Parameters
        ----------
        reference_ds : xr.Dataset
            Reference dataset.
        aux_datasets : dict[str, xr.Dataset]
            Auxiliary datasets.

        Raises
        ------
        ValueError
            If validation fails.
        """
        if not aux_datasets:
            raise ValueError("At least one auxiliary dataset required")

        self._validate_dimensions(reference_ds, "Reference dataset")

        for name, ds in aux_datasets.items():
            self._validate_dimensions(ds, f"Dataset '{name}'")
            self._validate_interpolation_config(ds, name)

    def _validate_dimensions(self, ds: xr.Dataset, name: str) -> None:
        """Check dataset has required dimensions.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to validate.
        name : str
            Dataset name for error messages.

        Raises
        ------
        ValueError
            If missing 'epoch' or 'sid' dimension.
        """
        if "epoch" not in ds.dims or "sid" not in ds.dims:
            raise ValueError(f"{name} missing required dimension 'epoch' or 'sid'")

    def _validate_interpolation_config(
        self,
        ds: xr.Dataset,
        name: str,
    ) -> None:
        """Verify dataset has interpolation configuration.

        Issues warning if missing - interpolation will still work
        via fallback to nearest neighbor.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to check.
        name : str
            Dataset name for warning message.
        """
        if "interpolator_config" not in ds.attrs:
            warnings.warn(
                f"Dataset '{name}' missing interpolation configuration. "
                "Will use nearest-neighbor interpolation.",
                UserWarning,
                stacklevel=2,
            )

    def _get_temporal_interval(self, ds: xr.Dataset) -> float:
        """Calculate temporal interval of dataset in seconds.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with epoch dimension.

        Returns
        -------
        float
            Median step between consecutive epochs in seconds, so a gap
            in the data does not change it.

        Raises
        ------
        ValueError
            If the dataset has fewer than two epochs.
        """
        if ds.sizes["epoch"] < 2:
            raise ValueError(
                f"Need at least two epochs to find the sampling interval, "
                f"got {ds.sizes['epoch']}"
            )
        steps = np.diff(ds["epoch"].values) / np.timedelta64(1, "s")
        return float(np.median(steps))

    def _match_temporal_resolution(
        self,
        reference_ds: xr.Dataset,
        ref_interval: float,
        aux_datasets: dict[str, xr.Dataset],
    ) -> dict[str, xr.Dataset]:
        """Match temporal resolution of auxiliary datasets to reference.

        Strategy depends on relative sampling rates:
        - Higher resolution aux (finer sampling) → nearest neighbor
        - Lower resolution aux (coarser sampling) → specialized interpolator

        Parameters
        ----------
        reference_ds : xr.Dataset
            Reference dataset defining target epochs.
        ref_interval : float
            Reference dataset temporal interval in seconds.
        aux_datasets : dict[str, xr.Dataset]
            Auxiliary datasets to interpolate.

        Returns
        -------
        dict[str, xr.Dataset]
            Matched datasets aligned to reference epochs.
        """
        matched_datasets = {}

        for name, ds in aux_datasets.items():
            ds_interval = self._get_temporal_interval(ds)

            if ds_interval < ref_interval:
                # Higher resolution → simple nearest neighbor
                matched_datasets[name] = ds.interp(
                    epoch=reference_ds.epoch, method="nearest"
                )
            else:
                # Lower resolution → use specialized interpolator
                if "interpolator_config" in ds.attrs:
                    interpolator = create_interpolator_from_attrs(ds.attrs)
                    matched_datasets[name] = interpolator.interpolate(
                        ds, reference_ds.epoch
                    )
                else:
                    # Fallback to nearest neighbor
                    matched_datasets[name] = ds.interp(
                        epoch=reference_ds.epoch, method="nearest"
                    )

                # Track temporal distance for quality assessment
                temporal_distance = abs(matched_datasets[name]["epoch"] - ds["epoch"])
                matched_datasets[name][f"{name.lower()}_temporal_distance"] = (
                    temporal_distance
                )

        return matched_datasets
