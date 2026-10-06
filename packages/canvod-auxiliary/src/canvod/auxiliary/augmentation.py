"""
Augmentation Framework for RINEX Data

Provides a pluggable system for augmenting RINEX datasets with computed values
from auxiliary data (ephemerides, clock, atmospheric corrections, etc.).

Architecture:
    AugmentationStep (ABC) - Base class for augmentation operations
    ├── SphericalCoordinateAugmentation - Computes φ, θ, r from ephemerides
    ├── ClockCorrectionAugmentation - Applies SV velocities from clock data
    └── [Future] AtmosphericCorrectionAugmentation - Applies ionosphere/troposphere

    AuxDataAugmenter - Orchestrates multiple augmentation steps
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog
import xarray as xr
from canvod.utils.tools import deprecated

from canvod.auxiliary.matching import DatasetMatcher
from canvod.auxiliary.position import (
    ECEFPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)

if TYPE_CHECKING:
    from canvod.auxiliary.pipeline import AuxDataPipeline

_USE_OPS = "Write a `canvod.ops.Op` and run it in a `canvod.ops.Pipeline` instead."
_USE_POSITION = (
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)


def _left_over(name: str, replacement: str) -> str:
    return (
        f"`{name}` is left over from development and will be removed with "
        f"the next major version. {replacement}"
    )


@deprecated(_left_over("AugmentationContext", _USE_OPS))
class AugmentationContext:
    """Context object passed to augmentation steps.

    Contains shared state and computed values that augmentation steps
    might need (e.g., receiver position, matched datasets).

    Parameters
    ----------
    receiver_position : ECEFPosition, optional
        ECEF position of the receiver.
    receiver_type : str, optional
        Type of receiver ("canopy" or "reference").
    matched_datasets : dict[str, xr.Dataset], optional
        Dictionary of matched auxiliary datasets.
    metadata : dict[str, Any], optional
        Additional metadata for augmentation steps.
    """

    def __init__(
        self,
        receiver_position: ECEFPosition | None = None,
        receiver_type: str | None = None,
        matched_datasets: dict[str, xr.Dataset] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.receiver_position = receiver_position
        self.receiver_type = receiver_type
        self.matched_datasets = matched_datasets or {}
        self.metadata = metadata or {}
        self._logger = structlog.get_logger(__name__)

    def get_matched_dataset(self, name: str) -> xr.Dataset:
        """Get a matched auxiliary dataset by name.

        Parameters
        ----------
        name : str
            Dataset key in the matched dataset mapping.

        Returns
        -------
        xr.Dataset
            Matched dataset.

        Raises
        ------
        KeyError
            If the dataset is not present in the context.
        """
        if name not in self.matched_datasets:
            raise KeyError(
                f"Dataset '{name}' not in matched datasets. "
                f"Available: {list(self.matched_datasets.keys())}"
            )
        return self.matched_datasets[name]

    def set_receiver_position(self, position: ECEFPosition) -> None:
        """Set or update the receiver position.

        Parameters
        ----------
        position : ECEFPosition
            Receiver ECEF position.
        """
        self.receiver_position = position
        self._logger.info(f"Updated receiver position: {position}")

    def __repr__(self) -> str:
        return (
            f"AugmentationContext("
            f"receiver_type={self.receiver_type}, "
            f"has_position={self.receiver_position is not None}, "
            f"matched_datasets={list(self.matched_datasets.keys())})"
        )


@deprecated(_left_over("AugmentationStep", _USE_OPS))
class AugmentationStep(ABC):
    """Abstract base class for augmentation steps.

    Each augmentation step takes a RINEX dataset and auxiliary data,
    performs calculations, and returns an augmented dataset with
    new data variables added.

    Notes
    -----
    This class uses ``ABC`` to define required augmentation hooks.

    Parameters
    ----------
    name : str
        Human-readable name for this augmentation step.
    """

    def __init__(self, name: str):
        """Initialize augmentation step."""
        self.name = name
        self._logger = structlog.get_logger(__name__)

    @abstractmethod
    def augment(
        self,
        ds: xr.Dataset,
        aux_pipeline: AuxDataPipeline,
        context: AugmentationContext,
    ) -> xr.Dataset:
        """Augment the dataset with computed values.

        Parameters
        ----------
        ds : xr.Dataset
            RINEX observation dataset to augment.
        aux_pipeline : AuxDataPipeline
            Pipeline providing access to auxiliary data.
        context : AugmentationContext
            Shared context with receiver position and matched datasets.

        Returns
        -------
        xr.Dataset
            Augmented dataset with new data variables.
        """
        pass

    @abstractmethod
    def get_required_aux_files(self) -> list[str]:
        """Return list of required auxiliary file names.

        Returns
        -------
        list[str]
            Names of aux files needed (e.g., ["ephemerides", "clock"]).
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"


@deprecated(_left_over("SphericalCoordinateAugmentation", _USE_POSITION))
class SphericalCoordinateAugmentation(AugmentationStep):
    """Compute spherical coordinates (phi, theta, r) in navigation convention.

    Computes:
    - φ (phi): Azimuthal angle from North, clockwise [0, 2π) radians
    - θ (theta): Polar angle from zenith [0, π] radians
    - r: Distance from receiver to satellite in meters

    Uses local ENU (East-North-Up) topocentric frame with navigation convention
    (0 = North, π/2 = East).
    """

    def __init__(self):
        super().__init__(name="SphericalCoordinates")

    def get_required_aux_files(self) -> list[str]:
        """Return required auxiliary file names."""
        return ["ephemerides"]

    def augment(
        self,
        ds: xr.Dataset,
        aux_pipeline: AuxDataPipeline,
        context: AugmentationContext,
    ) -> xr.Dataset:
        """Compute and add spherical coordinates using shared utility."""

        self._logger.info(f"Applying {self.name} augmentation")

        # Validate
        if context.receiver_position is None:
            raise ValueError(f"{self.name} requires receiver position in context.")
        if "ephemerides" not in context.matched_datasets:
            raise ValueError(f"{self.name} requires 'ephemerides' in matched_datasets.")

        ephem_ds = context.matched_datasets["ephemerides"]
        rx_pos = context.receiver_position

        # Get satellite positions
        sat_x = ephem_ds["X"].values
        sat_y = ephem_ds["Y"].values
        sat_z = ephem_ds["Z"].values

        # Compute using shared function
        r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, rx_pos)

        # Add to dataset using shared function
        ds = add_spherical_coords_to_dataset(ds, r, theta, phi)

        self._logger.info(
            f"Added phi, theta, r to dataset. "
            f"Shape: {dict(ds[['phi', 'theta', 'r']].sizes)}"
        )
        return ds


@deprecated(
    _left_over("ClockCorrectionAugmentation", "It leaves the data unchanged; drop it.")
)
class ClockCorrectionAugmentation(AugmentationStep):
    """Apply satellite clock corrections (placeholder implementation).

    This step doesn't add new variables but could be extended to:
    - Add SV velocity data variables (Vx, Vy, Vz)
    - Store clock offset information
    - Apply corrections to pseudorange/carrier phase

    Currently acts as a placeholder for future clock-related augmentations.
    """

    def __init__(self):
        super().__init__(name="ClockCorrection")

    def get_required_aux_files(self) -> list[str]:
        """Return required auxiliary file names.

        Empty on purpose: clock is optional (``AuxDataConfig.fetch_clock``
        may disable it), and ``augment()`` below already handles its
        absence gracefully — declaring it here would make
        ``AuxDataAugmenter.augment_dataset()`` hard-fail whenever clock
        fetching is disabled.
        """
        return []

    def augment(
        self,
        ds: xr.Dataset,
        aux_pipeline: AuxDataPipeline,
        context: AugmentationContext,
    ) -> xr.Dataset:
        """Apply clock corrections (placeholder implementation).

        Currently returns dataset unchanged. Future implementations could:
        - Add clock_offset as a data variable
        - Apply corrections to measurements
        - Add SV velocities if available

        Parameters
        ----------
        ds : xr.Dataset
            RINEX dataset.
        aux_pipeline : AuxDataPipeline
            Pipeline with clock data loaded.
        context : AugmentationContext
            Augmentation context.

        Returns
        -------
        xr.Dataset
            Dataset (currently unchanged).
        """
        self._logger.info(f"Applying {self.name} augmentation (placeholder)")

        # Placeholder: In the future, this could add clock_offset as a variable
        # or apply corrections to pseudorange/carrier phase measurements

        # For now, just validate that clock data is available
        if "clock" not in context.matched_datasets:
            self._logger.warning(
                f"{self.name} expected 'clock' in matched_datasets but not found. "
                f"Skipping clock augmentation."
            )
        else:
            clk_ds = context.matched_datasets["clock"]
            self._logger.debug(
                f"Clock data available: {dict(clk_ds.sizes)}, "
                f"variables: {list(clk_ds.data_vars)}"
            )

        return ds


@deprecated(_left_over("AuxDataAugmenter", _USE_POSITION))
class AuxDataAugmenter:
    """Orchestrate multiple augmentation steps on RINEX datasets.

    This class manages:
    1. Matching auxiliary datasets to RINEX epochs/satellites
    2. Computing receiver position (once per day)
    3. Running augmentation steps in sequence
    4. Building augmentation context

    Parameters
    ----------
    aux_pipeline : AuxDataPipeline
        Pipeline with auxiliary data loaded.
    steps : list[AugmentationStep], optional
        List of augmentation steps to apply. If None, uses default steps.

    Examples
    --------
    >>> pipeline = AuxDataPipeline.create_standard(matched_dirs)
    >>> pipeline.load_all()
    >>> augmenter = AuxDataAugmenter(pipeline)
    >>> augmented_ds = augmenter.augment_dataset(rinex_ds, receiver_type='canopy')
    """

    def __init__(
        self,
        aux_pipeline: AuxDataPipeline,
        steps: list[AugmentationStep] | None = None,
    ) -> None:
        self.aux_pipeline = aux_pipeline
        self.steps = steps or self._get_default_steps()
        self._logger = structlog.get_logger(__name__)
        self._receiver_position_cache: ECEFPosition | None = None

        self._logger.info(
            f"Initialized AuxDataAugmenter with {len(self.steps)} steps: "
            f"{[s.name for s in self.steps]}"
        )

    def _get_default_steps(self) -> list[AugmentationStep]:
        """Get default augmentation steps."""
        return [
            SphericalCoordinateAugmentation(),
            ClockCorrectionAugmentation(),
        ]

    def add_step(self, step: AugmentationStep) -> None:
        """Add an augmentation step to the pipeline.

        Parameters
        ----------
        step : AugmentationStep
            Step to add.
        """
        self.steps.append(step)
        self._logger.info(f"Added augmentation step: {step.name}")

    def augment_dataset(
        self,
        ds: xr.Dataset,
        receiver_type: str = "canopy",
        compute_receiver_position: bool = True,
    ) -> xr.Dataset:
        """Augment a RINEX dataset with all configured steps.

        Parameters
        ----------
        ds : xr.Dataset
            RINEX observation dataset to augment.
        receiver_type : str, default "canopy"
            Type of receiver ("canopy" or "reference").
        compute_receiver_position : bool, default True
            Whether to compute receiver position from dataset metadata.
            Set to False if position already cached from previous dataset.

        Returns
        -------
        xr.Dataset
            Augmented dataset with computed values added.

        Raises
        ------
        ValueError
            If required auxiliary files not loaded in pipeline.
        """
        self._logger.info(
            f"Starting augmentation for {receiver_type} dataset: {dict(ds.sizes)}"
        )

        # Step 1: Compute or retrieve receiver position
        if compute_receiver_position or self._receiver_position_cache is None:
            self._receiver_position_cache = ECEFPosition.from_ds_metadata(ds)
            self._logger.info(
                f"Computed receiver position: {self._receiver_position_cache}"
            )

        # Step 2: Match auxiliary datasets to RINEX epochs/satellites
        matched_datasets = self._match_datasets(ds)

        # Step 3: Build augmentation context
        context = AugmentationContext(
            receiver_position=self._receiver_position_cache,
            receiver_type=receiver_type,
            matched_datasets=matched_datasets,
        )

        # Step 4: Apply augmentation steps sequentially
        augmented_ds = ds
        for step in self.steps:
            try:
                # Validate required aux files are available
                for aux_file in step.get_required_aux_files():
                    if not self.aux_pipeline.is_loaded(aux_file):
                        raise ValueError(
                            f"Augmentation step '{step.name}' requires '{aux_file}' "
                            f"but it is not loaded in aux_pipeline"
                        )

                # Apply the augmentation
                augmented_ds = step.augment(augmented_ds, self.aux_pipeline, context)

            except Exception as e:
                self._logger.error(
                    f"Augmentation step '{step.name}' failed: {e}", exc_info=True
                )
                raise

        self._logger.info(
            f"Augmentation complete. Final dataset: {dict(augmented_ds.sizes)}, "
            f"variables: {list(augmented_ds.data_vars)}"
        )

        return augmented_ds

    def _match_datasets(self, rinex_ds: xr.Dataset) -> dict[str, xr.Dataset]:
        """Match auxiliary datasets to RINEX dataset epochs/satellites.

        Parameters
        ----------
        rinex_ds : xr.Dataset
            RINEX observation dataset.

        Returns
        -------
        dict[str, xr.Dataset]
            Dictionary of matched auxiliary datasets.
        """
        self._logger.info("Matching auxiliary datasets to RINEX epochs/satellites")

        matcher = DatasetMatcher()
        aux_datasets = {}

        # Get all loaded aux datasets
        for name in ["ephemerides", "clock"]:
            if self.aux_pipeline.is_loaded(name):
                aux_datasets[name] = self.aux_pipeline.get(name)

        # Match all datasets at once
        matched = matcher.match_datasets(rinex_ds, **aux_datasets)

        # Remove the 'canopy' key (which is the RINEX dataset itself)
        matched.pop("canopy", None)

        self._logger.info(
            f"Matched datasets: {[f'{k} {dict(v.sizes)}' for k, v in matched.items()]}"
        )

        return matched

    def __repr__(self) -> str:
        return (
            f"AuxDataAugmenter("
            f"steps={len(self.steps)}, "
            f"has_cached_position={self._receiver_position_cache is not None})"
        )


"""
Example usage of the Augmentation Framework

Demonstrates:
1. Creating an augmentation pipeline
2. Augmenting RINEX datasets with spherical coordinates
3. Using default and custom augmentation steps
4. Caching receiver position across multiple files

"""


@deprecated(
    "`example_basic_augmentation` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)
def example_basic_augmentation():
    """Basic example: Augment a single RINEX dataset."""
    print("=" * 60)
    print("EXAMPLE 1: Basic Augmentation")
    print("=" * 60)

    # Setup
    md = MatchedDirs(
        canopy_data_dir=Path("/path/to/canopy/24302"),
        reference_data_dir=Path("/path/to/sky/24302"),
        yyyydoy=YYYYDOY.from_str("2024302"),
    )

    # Create and load auxiliary data pipeline
    aux_pipeline = AuxDataPipeline.create_standard(md, Path("/path/to/site/root"))
    aux_pipeline.load_all()

    # Create augmenter with default steps
    augmenter = AuxDataAugmenter(aux_pipeline)
    print(f"\nAugmenter: {augmenter}")
    print(f"Steps: {[step.name for step in augmenter.steps]}")

    # Load a RINEX dataset (example - replace with actual dataset)
    # rinex_ds = xr.open_dataset('/path/to/rinex.nc')

    # Augment the dataset
    # augmented_ds = augmenter.augment_dataset(
    #     rinex_ds,
    #     receiver_type='canopy',
    #     compute_receiver_position=True
    # )

    # print(f"\nOriginal variables: {list(rinex_ds.data_vars)}")
    # print(f"Augmented variables: {list(augmented_ds.data_vars)}")
    # print(f"\nNew variables added: phi, theta, r")
    # print(f"  phi (azimuth): {augmented_ds.phi.attrs}")
    # print(f"  theta (polar angle): {augmented_ds.theta.attrs}")
    # print(f"  r (distance): {augmented_ds.r.attrs}")


@deprecated(
    "`example_custom_augmentation_step` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)
def example_custom_augmentation_step():
    """Example: Create a custom augmentation step."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Custom Augmentation Step")
    print("=" * 60)

    # Define a custom augmentation step
    class ElevationAugmentation(AugmentationStep):
        """
        Convert polar angle (theta) to elevation angle.

        Elevation = 90° - theta (in degrees)
        """

        def __init__(self):
            super().__init__(name="Elevation")

        def get_required_aux_files(self):
            return []  # Uses already computed theta

        def augment(self, ds, aux_pipeline, context):
            # Check if theta exists
            if "theta" not in ds.data_vars:
                raise ValueError("Elevation calculation requires 'theta' variable")

            # Convert theta (polar angle) to elevation
            # Elevation = π/2 - theta, then convert to degrees
            elevation_rad = np.pi / 2 - ds["theta"].values
            elevation_deg = np.rad2deg(elevation_rad)

            # Add to dataset
            ds = ds.assign(
                {
                    "elevation": (
                        ["epoch", "sid"],
                        elevation_deg,
                        {
                            "long_name": "Elevation angle",
                            "units": "degrees",
                            "description": "Elevation angle above horizon",
                            "valid_range": [-90.0, 90.0],
                        },
                    )
                }
            )

            self._logger.info(
                f"Added elevation variable: {dict(ds['elevation'].sizes)}"
            )
            return ds

    print("\nCustom step defined: ElevationAugmentation")
    print("  - Converts theta (polar angle) to elevation angle")
    print("  - Requires: theta (computed by SphericalCoordinateAugmentation)")
    print("  - Adds: elevation (in degrees)")


@deprecated(
    "`example_augmentation_pipeline` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)
def example_augmentation_pipeline():
    """Example: Complete augmentation pipeline for multiple files."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Augmentation Pipeline for Multiple Files")
    print("=" * 60)

    md = MatchedDirs(
        canopy_data_dir=Path("/path/to/canopy/24302"),
        reference_data_dir=Path("/path/to/sky/24302"),
        yyyydoy=YYYYDOY.from_str("2024302"),
    )

    # Setup auxiliary data
    aux_pipeline = AuxDataPipeline.create_standard(md, Path("/path/to/site/root"))
    aux_pipeline.load_all()

    # Create augmenter
    _ = AuxDataAugmenter(aux_pipeline)

    print("\nProcessing multiple RINEX files...")

    # Simulate processing multiple RINEX files
    rinex_files = [
        "/path/to/file1.nc",
        "/path/to/file2.nc",
        "/path/to/file3.nc",
    ]

    for i, rinex_file in enumerate(rinex_files):
        print(
            f"\n  Processing file {i + 1}/{len(rinex_files)}: {Path(rinex_file).name}"
        )

        # Load RINEX dataset
        # rinex_ds = xr.open_dataset(rinex_file)

        # Augment dataset
        # For the first file, compute receiver position
        # For subsequent files, reuse cached position
        compute_position = i == 0

        # augmented_ds = augmenter.augment_dataset(
        #     rinex_ds,
        #     receiver_type='canopy',
        #     compute_receiver_position=compute_position
        # )

        print(
            f"    - Receiver position: {'computed' if compute_position else 'cached'}"
        )
        print("    - Augmentation complete")

        # Save augmented dataset
        # augmented_ds.to_netcdf(rinex_file.replace('.nc', '_augmented.nc'))


@deprecated(
    "`example_integration_with_icechunk` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)
def example_integration_with_icechunk():
    """Example: Integration with parallel RINEX processing."""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Integration with Parallel Processing")
    print("=" * 60)

    print("""
In your parallel RINEX processing workflow:

    def preprocess_and_augment_rinex(rinex_file, aux_pipeline, augmenter):
        '''Process a single RINEX file with augmentation.'''

        # 1. Read RINEX file
        rnx = Rnxv3Obs(fpath=rinex_file)
        ds = rnx.to_ds()

        # 2. Augment with spherical coordinates
        ds_augmented = augmenter.augment_dataset(
            ds,
            receiver_type='canopy',
            compute_receiver_position=False  # Use cached position
        )

        # 3. Return augmented dataset
        return rinex_file, ds_augmented


    # In IcechunkDataReader.parsed_rinex_data_gen_v2():

    # Initialize once per day
    aux_pipeline = AuxDataPipeline.create_standard(matched_dirs)
    aux_pipeline.load_all()

    augmenter = AuxDataAugmenter(aux_pipeline)

    # Compute receiver position from first dataset
    first_ds = ...  # First RINEX dataset
    augmenter.augment_dataset(first_ds, compute_receiver_position=True)

    # Parallel processing
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(preprocess_and_augment_rinex, f, aux_pipeline, augmenter): f
            for f in rinex_files
        }

        for future in as_completed(futures):
            fname, ds_augmented = future.result()

            # Append to Icechunk
            store.append_to_group(ds_augmented, group_name='canopy')

    # The augmenter is thread-safe because:
    # - aux_pipeline uses threading.Lock for cache access
    # - augmenter caches receiver position (read-only after first compute)
    # - Each thread works on independent dataset
    """)


@deprecated(
    "`example_adding_custom_steps` is left over from development and will be "
    "removed with the next major version. "
    "Use `canvod.auxiliary.position.add_spherical_coords_to_dataset` instead."
)
def example_adding_custom_steps():
    """Example: Adding custom augmentation steps dynamically."""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: Adding Custom Steps")
    print("=" * 60)

    md = MatchedDirs(
        canopy_data_dir=Path("/path/to/canopy/24302"),
        reference_data_dir=Path("/path/to/sky/24302"),
        yyyydoy=YYYYDOY.from_str("2024302"),
    )

    aux_pipeline = AuxDataPipeline.create_standard(md, Path("/path/to/site/root"))
    aux_pipeline.load_all()

    # Start with default steps
    augmenter = AuxDataAugmenter(aux_pipeline)
    print(f"\nDefault steps: {[s.name for s in augmenter.steps]}")

    # Add custom step (example from EXAMPLE 2)
    class ElevationAugmentation(AugmentationStep):
        def __init__(self):
            super().__init__(name="Elevation")

        def get_required_aux_files(self):
            return []

        def augment(self, ds, aux_pipeline, context):
            elevation_rad = np.pi / 2 - ds["theta"].values
            elevation_deg = np.rad2deg(elevation_rad)
            ds = ds.assign(
                {
                    "elevation": (
                        ["epoch", "sid"],
                        elevation_deg,
                        {"long_name": "Elevation angle", "units": "degrees"},
                    )
                }
            )
            return ds

    augmenter.add_step(ElevationAugmentation())
    print(f"After adding custom step: {[s.name for s in augmenter.steps]}")

    print("\nAugmentation order:")
    print("  1. SphericalCoordinates → adds phi, theta, r")
    print("  2. ClockCorrection → (placeholder)")
    print("  3. Elevation → adds elevation (computed from theta)")


if __name__ == "__main__":
    from pathlib import Path

    import xarray as xr
    from canvod.readers import MatchedDirs
    from canvod.utils.tools import YYYYDOY

    from canvod.auxiliary.pipeline import AuxDataPipeline

    print("\n" + "=" * 60)
    print("AUGMENTATION FRAMEWORK EXAMPLES")
    print("=" * 60)

    example_basic_augmentation()
    example_custom_augmentation_step()
    example_augmentation_pipeline()
    example_integration_with_icechunk()
    example_adding_custom_steps()

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)
