"""Top-level CanvodConfig; composes processing, sites, and sids sections."""

from __future__ import annotations

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .processing import ProcessingConfig
from .sids import SidsConfig
from .sites import SitesConfig


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

    processing: ProcessingConfig
    sites: SitesConfig
    sids: SidsConfig

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
