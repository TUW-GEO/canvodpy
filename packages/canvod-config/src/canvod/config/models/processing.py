"""Complete processing configuration; composes the sub-sections below."""

from __future__ import annotations

import warnings

from pydantic import Field, model_validator

from canvod.utils.tools import deprecated

from .aux_data import PRECISE_ONLY_SETTINGS, AuxDataConfig
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

    @model_validator(mode="after")
    def _warn_product_with_broadcast(self) -> ProcessingConfig:
        """Agency and product type set together with the broadcast ephemeris warn.

        They apply only to the precise ephemeris; a broadcast store records
        them as empty. Values other than the defaults count as set: the
        package defaults and the settings template both write the defaults.
        """
        if self.params.ephemeris_source != "broadcast":
            return self
        fields = AuxDataConfig.model_fields
        named = [
            name
            for name in PRECISE_ONLY_SETTINGS
            if getattr(self.aux_data, name) != fields[name].default
        ]
        if named:
            warnings.warn(
                f"ephemeris_source 'broadcast' ignores {', '.join(named)} "
                "(processing.aux_data): they apply only to the precise "
                "ephemeris, and the store records them as empty. Remove them "
                "from your settings.",
                UserWarning,
                stacklevel=2,
            )
        return self

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
