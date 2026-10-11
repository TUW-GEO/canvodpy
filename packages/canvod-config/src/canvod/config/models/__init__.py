"""
Pydantic models for canvodpy configuration.

These models provide:
- Type validation for all configuration values
- Serialization support (YAML/JSON/dict)
- API-ready data transfer objects
- IDE autocomplete and type hints

Split across focused submodules by config section —
this ``__init__.py`` re-exports everything, so ``from canvod.config.models
import X`` keeps working exactly as it did when this was a single file.
"""

from .aux_data import AuxDataConfig
from .base import _StrictModel
from .compression import (
    ChunkStrategies,
    ChunkStrategy,
    CompressionConfig,
    IcechunkConfig,
    NetcdfCompressionConfig,
)
from .logging import LogDirNotSetError, LoggingConfig
from .metadata import CredentialsConfig, MetadataConfig
from .preprocessing import (
    PREPROCESSING_ATTR,
    PREPROCESSING_RECORD_VERSION,
    GridAssignmentConfig,
    HistogramBinsConfig,
    PreprocessingConfig,
    PreprocessingMismatchError,
    StatisticsConfig,
    TemporalAggregationConfig,
    describe_preprocessing,
    describe_settings,
    preprocessing_record,
    preprocessing_settings,
    preprocessing_steps,
    split_preprocessing,
    vod_preprocessing_record,
    vod_preprocessing_settings,
)
from .processing import ProcessingConfig
from .processing_params import ProcessingParams
from .references import FundingRef, PublicationRef, ReferencesConfig
from .root import CanvodConfig
from .sids import SidsConfig
from .sites import (
    AntennaConfig,
    ReceiverConfig,
    ReceiverHardwareConfig,
    SiteConfig,
    SitesConfig,
    VodAnalysisConfig,
    mixed_format_error,
    reference_store_group,
)
from .storage import MaintenanceConfig, StorageConfig

__all__ = [
    "PREPROCESSING_ATTR",
    "PREPROCESSING_RECORD_VERSION",
    "AntennaConfig",
    "AuxDataConfig",
    "CanvodConfig",
    "ChunkStrategies",
    "ChunkStrategy",
    "CompressionConfig",
    "CredentialsConfig",
    "FundingRef",
    "GridAssignmentConfig",
    "HistogramBinsConfig",
    "IcechunkConfig",
    "LogDirNotSetError",
    "LoggingConfig",
    "MaintenanceConfig",
    "MetadataConfig",
    "NetcdfCompressionConfig",
    "PreprocessingConfig",
    "PreprocessingMismatchError",
    "ProcessingConfig",
    "ProcessingParams",
    "PublicationRef",
    "ReceiverConfig",
    "ReceiverHardwareConfig",
    "ReferencesConfig",
    "SidsConfig",
    "SiteConfig",
    "SitesConfig",
    "StatisticsConfig",
    "StorageConfig",
    "TemporalAggregationConfig",
    "VodAnalysisConfig",
    "_StrictModel",
    "describe_preprocessing",
    "describe_settings",
    "mixed_format_error",
    "preprocessing_record",
    "preprocessing_settings",
    "preprocessing_steps",
    "reference_store_group",
    "split_preprocessing",
    "vod_preprocessing_record",
    "vod_preprocessing_settings",
]
