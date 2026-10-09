"""Configuration-based product registry with Pydantic validation."""

import difflib
import re
import tomllib
import warnings
from pathlib import Path
from typing import Literal

from canvod.utils.tools import deprecated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Every registry product file covers one day.
FILE_DURATION = "01D"


class FtpServerConfig(BaseModel):
    """FTP server configuration with validation.

    Notes
    -----
    This is a Pydantic `BaseModel`.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(pattern=r"^ftps?://")
    priority: int = Field(ge=1, le=100)
    description: str = ""
    requires_auth: bool = False

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Validate URL scheme is ftp or ftps."""
        if not (v.startswith("ftp://") or v.startswith("ftps://")):
            raise ValueError("URL must start with ftp:// or ftps://")
        return v


#: Product types the registry supports. Ultra-rapid products are issued
#: several times a day and are half predicted; their file names carry the
#: issue hour, which the readers do not handle.
PRODUCT_TYPES = ("final", "rapid")


class UnknownProductError(KeyError):
    """No registry product for the requested agency and product type."""

    def __str__(self) -> str:
        """Return the message without the quotes ``KeyError`` adds."""
        return str(self.args[0]) if self.args else ""


class ProductSpec(BaseModel):
    """
    Product specification with structural validation.

    A product is published as one SP3 and, if it has clocks, one CLK file
    per day. Agencies have changed the sampling of their files over the
    years, so ``sp3_samplings`` and ``clk_samplings`` list every sampling
    the product has been published with, in the order they are tried.

    Validates data structure only (fast). FTP availability is checked
    during download, and for the whole registry by
    ``python -m canvod.auxiliary.products.check`` (``just check-products``).

    Notes
    -----
    This is a Pydantic `BaseModel`.
    """

    model_config = ConfigDict(extra="forbid")

    agency_code: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    agency_name: str
    product_type: Literal["final", "rapid"]
    prefix: str = Field(
        min_length=9,
        max_length=10,
        pattern=r"^[A-Z0-9]+$",
    )
    sp3_samplings: list[str] = Field(min_length=1)
    clk_samplings: list[str] = Field(
        default_factory=list,
        description="Empty if the product publishes no clock files",
    )
    systems: str = Field(
        "",
        pattern=r"^[GRECJIS]*$",
        description="GNSS covered by the orbits (G, R, E, C, J, I, S)",
    )
    ftp_servers: list[FtpServerConfig]
    ftp_path_pattern: str
    description: str = ""

    @field_validator("sp3_samplings", "clk_samplings")
    @classmethod
    def validate_samplings(cls, v: list[str]) -> list[str]:
        """Validate sampling codes such as ``05M`` or ``30S``."""
        for sampling in v:
            if not re.fullmatch(r"\d{2}[SMHD]", sampling):
                raise ValueError(f"Sampling must look like 05M or 30S: {sampling!r}")
        return v

    @model_validator(mode="before")
    @classmethod
    def _migrate_single_sampling(cls, data: object) -> object:
        if not isinstance(data, dict) or not (
            {"sampling_rate", "duration", "available_formats"} & data.keys()
        ):
            return data
        warnings.warn(
            "The ProductSpec fields 'sampling_rate', 'duration' and "
            "'available_formats' are left over from development and will be "
            "removed with the next major version. Use 'sp3_samplings' and "
            "'clk_samplings' (empty: no clock files) instead.",
            FutureWarning,
            stacklevel=2,
        )
        data = dict(data)
        sampling = data.pop("sampling_rate", None)
        data.pop("duration", None)
        formats = data.pop("available_formats", ["SP3", "CLK"])
        if sampling is not None:
            data.setdefault("sp3_samplings", [sampling])
        if "CLK" in formats:
            data.setdefault("clk_samplings", ["30S"])
        return data

    @field_validator("prefix")
    @classmethod
    def validate_prefix_matches_agency(cls, v: str, info) -> str:
        """Validate prefix starts with agency code."""
        if "agency_code" in info.data:
            agency = info.data["agency_code"]
            if not v.startswith(agency):
                raise ValueError(f"Prefix must start with agency code {agency}")
        return v

    @property
    def has_clock(self) -> bool:
        """Whether the product publishes CLK files."""
        return bool(self.clk_samplings)

    @property
    def available_formats(self) -> list[str]:
        """File formats the product publishes."""
        return ["SP3", "CLK"] if self.has_clock else ["SP3"]

    @property
    @deprecated(
        "ProductSpec.sampling_rate is left over from development and will "
        "be removed with the next major version. Use "
        "ProductSpec.sp3_samplings instead."
    )
    def sampling_rate(self) -> str:
        """First SP3 sampling."""
        return self.sp3_samplings[0]

    @property
    @deprecated(
        "ProductSpec.duration is left over from development and will be "
        "removed with the next major version. Every registry product "
        "file covers one day ('01D')."
    )
    def duration(self) -> str:
        """File duration, always one day."""
        return FILE_DURATION

    def sp3_filenames(self, yyyydoy: str) -> list[str]:
        """SP3 file names for one day, in the order they are tried.

        Parameters
        ----------
        yyyydoy : str
            Day as ``YYYYDOY``.

        Returns
        -------
        list[str]
            One name per sampling, without the ``.gz`` of the server copy.
        """
        return [
            f"{self.prefix}_{yyyydoy}0000_{FILE_DURATION}_{s}_ORB.SP3"
            for s in self.sp3_samplings
        ]

    def clk_filenames(self, yyyydoy: str) -> list[str]:
        """CLK file names for one day, in the order they are tried.

        Parameters
        ----------
        yyyydoy : str
            Day as ``YYYYDOY``.

        Returns
        -------
        list[str]
            One name per sampling; empty if the product has no clocks.
        """
        return [
            f"{self.prefix}_{yyyydoy}0000_{FILE_DURATION}_{s}_CLK.CLK"
            for s in self.clk_samplings
        ]


class ProductRegistry:
    """Product registry loaded from TOML configuration.

    Allows users to:
    - Add custom products without editing code
    - Configure custom FTP servers
    - Override default products
    - Version control their configurations

    Parameters
    ----------
    config_path : Path, optional
        Path to products.toml (defaults to package location).
    """

    def __init__(self, config_path: Path | None = None):
        """Initialize registry from config file."""
        if config_path is None:
            # Default: package-provided config
            config_path = Path(__file__).parent / "products.toml"

        self.config_path = Path(config_path)
        self._products: dict[tuple[str, str], ProductSpec] = {}
        self._agencies: dict[str, str] = {}

        # Load configuration
        self._load_config()

    def _load_config(self) -> None:
        """Load products from TOML file with Pydantic validation."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Config not found: {self.config_path}\n"
                f"Expected location: {Path(__file__).parent / 'products.toml'}"
            )

        with open(self.config_path, "rb") as f:
            config = tomllib.load(f)

        # Load agency metadata
        self._agencies = config.get("agencies", {})

        # Load products with Pydantic validation
        for product_data in config.get("products", []):
            # Build ProductSpec with Pydantic validation
            spec = ProductSpec(
                agency_code=product_data["agency"],
                agency_name=self._agencies.get(
                    product_data["agency"], f"{product_data['agency']} Analysis Center"
                ),
                product_type=product_data["type"],
                prefix=product_data["prefix"],
                sp3_samplings=product_data["sp3_sampling"],
                clk_samplings=product_data["clk_sampling"],
                systems=product_data["systems"],
                ftp_servers=[
                    FtpServerConfig(**server)
                    for server in product_data.get("ftp_servers", [])
                ],
                ftp_path_pattern=product_data["ftp_path"],
                description=product_data.get("description", ""),
            )

            # Store by (agency, type) key
            key = (spec.agency_code, spec.product_type)
            self._products[key] = spec

    def get_product_spec(self, agency: str, product_type: str) -> ProductSpec:
        """Get product specification.

        Parameters
        ----------
        agency : str
            Agency code (e.g., "COD", "GFZ").
        product_type : str
            Product type ("final" or "rapid").

        Returns
        -------
        ProductSpec
            Product specification.

        Raises
        ------
        UnknownProductError
            If product not found (a ``KeyError``); the message names the
            closest products.
        """
        key = (agency.upper(), product_type.lower())

        if key not in self._products:
            raise UnknownProductError(self._unknown_product_message(*key))

        return self._products[key]

    def _unknown_product_message(self, agency: str, product_type: str) -> str:
        """Name the products closest to an unknown agency/product type."""
        lines = [f"Product not found: {agency}/{product_type}"]
        agencies = self.list_agencies()
        if agency in agencies:
            types = self.get_products_for_agency(agency)
            lines.append(f"{agency} publishes: {', '.join(types)}")
        else:
            match = difflib.get_close_matches(agency, agencies, n=1)
            if match:
                lines.append(f"Did you mean agency '{match[0]}'?")
        if product_type not in PRODUCT_TYPES:
            lines.append(
                f"Product types: {', '.join(PRODUCT_TYPES)} (ultra-rapid, "
                "real-time and near-real-time products are not supported)"
            )
        lines.append(
            "Available products: "
            + ", ".join(f"{ag}/{pt}" for ag, pt in self.list_products())
        )
        lines.append(f"To add a product, edit: {self.config_path}")
        return "\n".join(lines)

    def list_agencies(self) -> list[str]:
        """List all registered agencies."""
        return sorted(set(agency for agency, _ in self._products.keys()))

    def list_products(self) -> list[tuple[str, str]]:
        """List all registered (agency, product_type) combinations."""
        return sorted(self._products.keys())

    def get_products_for_agency(self, agency: str) -> list[str]:
        """Get all product types for an agency."""
        agency_upper = agency.upper()
        return sorted(
            product_type
            for (ag, product_type) in self._products.keys()
            if ag == agency_upper
        )

    def get_agency_name(self, agency: str) -> str:
        """Get full agency name."""
        return self._agencies.get(agency.upper(), f"{agency.upper()} Analysis Center")


# Global registry instance (lazy-loaded)
_registry: ProductRegistry | None = None


def get_registry(config_path: Path | None = None) -> ProductRegistry:
    """Get global registry instance.

    Parameters
    ----------
    config_path : Path, optional
        Optional custom config path.

    Returns
    -------
    ProductRegistry
        Global registry instance.
    """
    global _registry

    if _registry is None or config_path is not None:
        _registry = ProductRegistry(config_path)

    return _registry


# Convenience functions
def get_product_spec(agency: str, product_type: str) -> ProductSpec:
    """Get product spec from global registry."""
    return get_registry().get_product_spec(agency, product_type)


def check_product(agency: str, product_type: str, fetch_clock: bool) -> ProductSpec:
    """Check the configured product before any file is downloaded.

    Parameters
    ----------
    agency : str
        Agency code, ``processing.aux_data.agency``.
    product_type : str
        ``processing.aux_data.product_type``.
    fetch_clock : bool
        ``processing.aux_data.fetch_clock``.

    Returns
    -------
    ProductSpec
        The product.

    Raises
    ------
    UnknownProductError
        If the registry has no such product; the message names the closest.
    ValueError
        If clocks are to be fetched but the product publishes none.
    """
    spec = get_product_spec(agency, product_type)
    if fetch_clock and not spec.has_clock:
        msg = (
            f"{spec.agency_code}/{spec.product_type} publishes no clock files, "
            "but processing.aux_data.fetch_clock is true. Set it to false, or "
            "choose a product with clocks."
        )
        raise ValueError(msg)
    return spec


def list_agencies() -> list[str]:
    """List agencies from global registry."""
    return get_registry().list_agencies()


def list_products() -> list[tuple[str, str]]:
    """List all products from global registry."""
    return get_registry().list_products()


def get_products_for_agency(agency: str) -> list[str]:
    """Get products for agency from global registry."""
    return get_registry().get_products_for_agency(agency)


def get_agency_name(agency: str) -> str:
    """Get full agency name from global registry."""
    return get_registry().get_agency_name(agency)
