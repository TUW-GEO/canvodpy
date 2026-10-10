"""
canvod-aux: Auxiliary data augmentation for GNSS VOD analysis

Handles downloading, parsing, and interpolating SP3 ephemerides and
clock corrections for GNSS satellite data processing.
"""

from importlib.metadata import version as _version

# Aux cache fingerprinting
from canvod.readers.preprocessing import (
    add_future_datavars,
    create_sv_to_sid_mapping,
    map_aux_sv_to_sid,
    normalize_sid_dtype,
    pad_to_global_sid,
    strip_fillvalue,
)

from canvod.auxiliary.augmentation import (
    AugmentationContext,
    AugmentationStep,
    AuxDataAugmenter,
    ClockCorrectionAugmentation,
    SphericalCoordinateAugmentation,
)
from canvod.auxiliary.cache_fingerprint import (
    CANONICAL_AUX_GRID_SECONDS,
    compute_aux_cache_fingerprint,
)

# Core abstractions
from canvod.auxiliary.clock import ClkFile

# Container classes
from canvod.auxiliary.container import GnssData
from canvod.auxiliary.core.base import AuxFile
from canvod.auxiliary.core.downloader import FileDownloader, FtpDownloader

# File handlers by auxiliary data type
from canvod.auxiliary.ephemeris import Sp3File

# Interpolation
from canvod.auxiliary.interpolation import (
    ClockConfig,
    ClockInterpolationStrategy,
    Interpolator,
    InterpolatorConfig,
    Sp3Config,
    Sp3InterpolationStrategy,
    create_interpolator_from_attrs,
)

# Dataset matching
from canvod.auxiliary.matching import DatasetMatcher

# Pipeline
from canvod.auxiliary.pipeline import AuxDataPipeline

# Position and coordinates
from canvod.auxiliary.position import (
    ECEFPosition,
    GeodeticPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)

# Preprocessing
from canvod.auxiliary.preprocessing import (
    prep_aux_ds,
    preprocess_aux_for_interpolation,
)

# Product registry
from canvod.auxiliary.products import (
    FtpServerConfig,
    ProductRegistry,
    ProductSpec,
    UnknownProductError,
    check_product,
    get_product_spec,
    get_products_for_agency,
    get_registry,
    list_agencies,
    list_products,
)

__version__ = _version("canvod-auxiliary")

__all__ = [
    "AugmentationContext",
    "AugmentationStep",
    "AuxDataAugmenter",
    "AuxDataPipeline",
    "AuxFile",
    "CANONICAL_AUX_GRID_SECONDS",
    "ClkFile",
    "ClockConfig",
    "ClockCorrectionAugmentation",
    "ClockInterpolationStrategy",
    # Dataset matching
    "DatasetMatcher",
    # Position and coordinates
    "ECEFPosition",
    # Utilities
    "FileDownloader",
    "FtpDownloader",
    # Product registry
    "FtpServerConfig",
    "GeodeticPosition",
    "GnssData",
    # Interpolation
    "Interpolator",
    "InterpolatorConfig",
    "ProductRegistry",
    "ProductSpec",
    "UnknownProductError",
    "SphericalCoordinateAugmentation",
    "Sp3Config",
    # File handlers
    "Sp3File",
    "Sp3InterpolationStrategy",
    "add_future_datavars",
    "add_spherical_coords_to_dataset",
    "compute_aux_cache_fingerprint",
    "compute_spherical_coordinates",
    "create_interpolator_from_attrs",
    "create_sv_to_sid_mapping",
    "check_product",
    "get_product_spec",
    "get_products_for_agency",
    "get_registry",
    "list_agencies",
    "list_products",
    "map_aux_sv_to_sid",
    "normalize_sid_dtype",
    "pad_to_global_sid",
    "prep_aux_ds",
    # Preprocessing
    "preprocess_aux_for_interpolation",
    "strip_fillvalue",
]
