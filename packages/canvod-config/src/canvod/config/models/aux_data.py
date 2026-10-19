"""Auxiliary data source configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .base import _StrictModel


class AuxDataConfig(_StrictModel):
    """Auxiliary data source configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    agency: str = Field("COD", description="Analysis center code")
    product_type: Literal["final", "rapid"] = Field(
        "final",
        description=(
            "Product type. The agency must publish it: see the product "
            "registry of canvod-auxiliary (products.toml)."
        ),
    )
    ftp_timeout_s: int = Field(
        30, ge=1, description="FTP connection timeout in seconds"
    )
    fetch_clock: bool = Field(
        False,
        description=(
            "Download and interpolate the CLK clock files with the SP3 orbit "
            "files. VOD doesn't use clock corrections, so they are off; set "
            "true to add each satellite's clock correction to the GNSS store "
            "as the variable clock."
        ),
    )
    zarr_async_concurrency: int | None = Field(
        None,
        ge=1,
        description=(
            "Limit on Zarr's concurrent chunk reads and writes in the orbit and "
            "clock cache; null keeps Zarr's default of 10. Set it when "
            "shared_aux_cache_dir is on a network mount (CIFS or NFS) that "
            "drops connections during writes."
        ),
    )

    @field_validator("product_type", mode="before")
    @classmethod
    def _reject_ultra_rapid(cls, v: object) -> object:
        if isinstance(v, str) and v.replace("-", "").lower() == "ultrarapid":
            msg = (
                "Ultra-rapid products are not supported: they are issued "
                "several times a day, are half predicted, and their files "
                "span two days and carry the issue hour. Use 'rapid' or "
                "'final'."
            )
            raise ValueError(msg)
        return v

    def get_ftp_servers(
        self,
        cddis_mail: str | None,
    ) -> list[tuple[str, str | None]]:
        """Get FTP servers in priority order.

        If cddis_mail is set: NASA first (with auth), ESA fallback (no auth).
        If cddis_mail is None: ESA only (no auth).

        Parameters
        ----------
        cddis_mail : str | None
            Optional CDDIS email for NASA authentication.

        Returns
        -------
        list[tuple[str, str | None]]
            Server URL and optional auth email pairs in priority order.
        """
        if cddis_mail:
            # NASA first (requires auth), ESA fallback (no auth)
            return [
                ("ftp://gdc.cddis.eosdis.nasa.gov", cddis_mail),
                ("ftp://gssc.esa.int", None),
            ]
        # ESA only (no auth required)
        return [("ftp://gssc.esa.int", None)]
