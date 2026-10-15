"""Complete processing configuration; composes the sub-sections below."""

from __future__ import annotations

from pydantic import Field

from canvod.utils.tools import deprecated

from .aux_data import AuxDataConfig
from .base import _StrictModel
from .compression import IcechunkConfig, NetcdfCompressionConfig
from .logging import LoggingConfig
from .metadata import CredentialsConfig, MetadataConfig
from .preprocessing import PreprocessingConfig
from .processing_params import ProcessingParams
from .references import ReferencesConfig
from .storage import StorageConfig


class ProcessingConfig(_StrictModel):
    """Complete processing configuration."""

    metadata: MetadataConfig = Field(
        ...,
        description="Who made the stores, and under which license",
    )
    credentials: CredentialsConfig = Field(
        default_factory=CredentialsConfig,
        description="Credentials for external data services",
    )
    aux_data: AuxDataConfig = Field(
        default_factory=AuxDataConfig,
        description="The orbit and clock products to download",
    )
    params: ProcessingParams = Field(
        default_factory=ProcessingParams,
        description="What a run reads and computes, and how many workers it uses",
    )
    netcdf_compression: NetcdfCompressionConfig = Field(
        default_factory=NetcdfCompressionConfig,
        description="Compression settings for NetCDF output from RINEX readers",
    )
    icechunk: IcechunkConfig = Field(
        default_factory=IcechunkConfig,
        description="How the stores are written on disk: compression and chunks",
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Where the stores are, and what a run does with stored files",
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Where the log files go",
    )
    preprocessing: PreprocessingConfig | None = Field(
        None,
        description=(
            "Operations applied to each receiver's data before it is written "
            "to the GNSS store; none unless set"
        ),
    )
    references: ReferencesConfig = Field(
        default_factory=ReferencesConfig,
        description="Publication and funding references",
    )

    @property
    @deprecated(
        "ProcessingConfig.processing is left over from development and will be removed with the next major version. "
        "Use ProcessingConfig.params instead."
    )
    def processing(self) -> ProcessingParams:
        """Deprecated: use .params instead."""
        return self.params

    @property
    @deprecated(
        "ProcessingConfig.compression is left over from development and will be removed with the next major version. "
        "Use ProcessingConfig.netcdf_compression instead."
    )
    def compression(self) -> NetcdfCompressionConfig:
        """Deprecated: use .netcdf_compression instead."""
        return self.netcdf_compression
