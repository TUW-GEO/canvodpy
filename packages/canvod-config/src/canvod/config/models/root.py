"""Top-level CanvodConfig; composes processing, sites, and sids sections."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .processing import ProcessingConfig
from .sids import SidsConfig
from .sites import RINEX_READER_FORMATS, SitesConfig


class CanvodConfig(BaseSettings):
    """
    Complete canvodpy configuration.

    Loaded from YAML files by ConfigLoader; individual fields can be
    overridden via environment variables using the ``CANVOD__`` prefix
    and ``__`` as the nested delimiter.  Environment variables take
    priority over YAML-file values.

    Examples
    --------
    Override a single nested field without touching the YAML. ``VAR=value``
    must appear on the *same command line* as ``canvodpy`` — it only sets a
    variable for the current shell otherwise, and canvodpy (a separate
    process) never sees it::

        CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7 canvodpy run ...
        CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=me@x.com canvodpy run ...

    To reuse an override across several commands, ``export`` it once instead::

        export CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7
        canvodpy config show   # confirms the override took effect
        canvodpy run ...
    """

    model_config = SettingsConfigDict(
        env_prefix="CANVOD__",
        env_nested_delimiter="__",
        extra="forbid",
        env_file=["config/.env", ".env"],
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    processing: ProcessingConfig = Field(
        ..., description="How canVODpy processes the data, and where the results go"
    )
    sites: SitesConfig = Field(
        ..., description="The research sites, their receivers, and VOD analyses"
    )
    sids: SidsConfig = Field(..., description="Which signals are kept")

    @model_validator(mode="after")
    def _broadcast_rinex_needs_nav_directory(self) -> CanvodConfig:
        """With the broadcast ephemeris, receivers with RINEX files need nav files.

        NMEA receivers are refused: their angles come only from the precise
        ephemeris. In shared-position mode a reference receiver takes the
        angles from its canopy's navigation files and needs none of its own.
        A receiver whose ``reader_format`` is ``auto`` or a plugin format is
        checked by the run, once its files show the format.
        """
        if self.processing.params.ephemeris_source != "broadcast":
            return self
        nmea = [
            f"{site_name}.{name}"
            for site_name, site in self.sites.sites.items()
            for name, receiver in site.receivers.items()
            if receiver.reader_format == "nmea"
        ]
        if nmea:
            msg = (
                "ephemeris_source 'broadcast' supports SBF and RINEX files; "
                f"{', '.join(nmea)} read nmea: use ephemeris_source 'precise'."
            )
            raise ValueError(msg)
        shared = self.processing.params.receiver_position_mode == "shared"
        missing = [
            f"{site_name}.{name}"
            for site_name, site in self.sites.sites.items()
            for name, receiver in site.receivers.items()
            if receiver.reader_format in RINEX_READER_FORMATS
            and receiver.nav_directory is None
            and not (shared and receiver.type == "reference")
        ]
        if missing:
            msg = (
                "ephemeris_source 'broadcast' takes the satellite positions for "
                "RINEX files from navigation files: set nav_directory "
                f"for {', '.join(missing)} (sites.<site>.receivers.<receiver>)."
            )
            raise ValueError(msg)
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Env vars beat YAML-loaded init kwargs; dotenv/secrets not used.
        return (env_settings, init_settings)

    @property
    def nasa_earthdata_acc_mail(self) -> str | None:
        """Return the configured NASA Earthdata email for CDDIS authentication.

        Returns
        -------
        str | None
            NASA Earthdata email address.
        """
        return self.processing.credentials.nasa_earthdata_acc_mail
