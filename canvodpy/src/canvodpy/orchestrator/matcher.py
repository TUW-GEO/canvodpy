"""Dataset alignment and interpolation for auxiliary datasets."""

import warnings

import xarray as xr

from canvod.auxiliary.interpolation import create_interpolator_from_attrs
from canvod.utils.tools import deprecated


@deprecated(
    "canvodpy.orchestrator.matcher.DatasetMatcher is left over from development and will be removed with the next major version. "
    "Use canvod.auxiliary.matching.DatasetMatcher instead."
)
class DatasetMatcher:
    """Class responsible for matching multiple datasets to a reference timeline.

    This class handles:
    1. Temporal alignment of datasets
    2. Finding common satellites
    3. Applying appropriate interpolation strategies
    """

    def match_datasets(
        self,
        canopy_data_ds: xr.Dataset,
        **other_ds: xr.Dataset,
    ) -> dict[str, xr.Dataset]:
        """Match multiple named datasets to the canopy dataset while minimizing changes.

        Parameters
        ----------
        canopy_data_ds : xr.Dataset
            The primary dataset that should be preserved
        **other_ds : dict[str, xr.Dataset]
            Named auxiliary datasets to be matched

        Returns
        -------
        dict[str, xr.Dataset]
            All matched datasets with common time points and satellites

        Raises
        ------
        ValueError
            If validation fails or no common satellites are found

        """
        self._validate_inputs(canopy_data_ds, other_ds)

        # Calculate temporal properties
        canopy_interval = self._get_temporal_interval(canopy_data_ds)

        # Match datasets
        return self._match_temporal_resolution(
            canopy_data_ds, canopy_interval, other_ds
        )

    def _validate_inputs(
        self,
        canopy_ds: xr.Dataset,
        other_ds: dict[str, xr.Dataset],
    ) -> None:
        """Validate input datasets.

        Checks:
        1. At least one auxiliary dataset is provided
        2. All datasets have required dimensions
        3. Auxiliary datasets cover the canopy dataset's time period
        4. Interpolation configuration is available when needed
        """
        if not other_ds:
            msg = "At least one auxiliary dataset is required"
            raise ValueError(msg)

        self._validate_dimensions(canopy_ds, "Canopy dataset")
        for name, ds in other_ds.items():
            self._validate_dimensions(ds, f"Dataset '{name}'")
            self._validate_interpolation_config(ds, name)

    def _validate_dimensions(self, ds: xr.Dataset, name: str) -> None:
        """Check if dataset has required dimensions."""
        if "epoch" not in ds.dims or "sid" not in ds.dims:
            msg = f"{name} missing required dimension 'epoch' or 'sid'"
            raise ValueError(msg)

    def _validate_temporal_coverage(
        self,
        ds: xr.Dataset,
        canopy_ds: xr.Dataset,
        name: str,
    ) -> None:
        """Check if dataset covers the required time period."""
        canopy_start = canopy_ds["epoch"][0]
        canopy_end = canopy_ds["epoch"][-1]

        if ds["epoch"][0] > canopy_start:
            msg = f"Dataset '{name}' begins after the canopy dataset"
            raise ValueError(msg)
        if ds["epoch"][-1] < canopy_end:
            msg = f"Dataset '{name}' ends before the canopy dataset"
            raise ValueError(msg)

    def _validate_interpolation_config(
        self,
        ds: xr.Dataset,
        name: str,
    ) -> None:
        """Verify dataset has interpolation configuration if needed."""
        if "interpolator_config" not in ds.attrs:
            warnings.warn(
                (
                    f"Dataset '{name}' missing interpolation configuration. "
                    "Will use nearest-neighbor interpolation."
                ),
                stacklevel=2,
            )

    def _get_temporal_interval(self, ds: xr.Dataset) -> float:
        """Calculate temporal interval of dataset in seconds."""
        return float((ds["epoch"][1] - ds["epoch"][0]).values)

    def _match_temporal_resolution(
        self,
        canopy_ds: xr.Dataset,
        canopy_interval: float,
        other_ds: dict[str, xr.Dataset],
    ) -> dict[str, xr.Dataset]:
        """Match temporal resolution of all datasets.

        Uses appropriate interpolation strategy based on:
        1. Relative temporal resolution
        2. Available interpolation configuration
        """
        matched_datasets = {}

        for name, ds in other_ds.items():
            ds_interval = float((ds["epoch"][1] - ds["epoch"][0]).values)

            if ds_interval < canopy_interval:
                # Higher resolution datasets use nearest neighbor
                matched_datasets[name] = ds.interp(
                    epoch=canopy_ds.epoch, method="nearest"
                )
            else:
                # Lower resolution datasets use their specialized interpolator
                if "interpolator_config" in ds.attrs:
                    interpolator = create_interpolator_from_attrs(ds.attrs)
                    matched_datasets[name] = interpolator.interpolate(
                        ds, canopy_ds.epoch
                    )
                else:
                    # Fallback to nearest neighbor if no interpolator configured
                    matched_datasets[name] = ds.interp(
                        epoch=canopy_ds.epoch, method="nearest"
                    )

                # Track temporal distance for quality assessment
                matched_datasets[name][f"{name.lower()}_temporal_distance"] = abs(
                    matched_datasets[name]["epoch"] - ds["epoch"]
                )

        return matched_datasets
