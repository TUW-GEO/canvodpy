"""Pydantic models for auxiliary file validation."""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class Sp3Header(BaseModel):
    """Pydantic model for SP3 file header validation.

    Validates the header section of SP3 (Standard Product #3) orbit files
    according to IGS format specifications.
    """

    version: str = Field(..., description="SP3 version (#d or #P)")
    epoch_count: int = Field(..., gt=0, description="Number of epochs")
    data_used: str = Field(..., description="Data used indicator")
    coordinate_system: str = Field(..., description="Coordinate system")
    orbit_type: str = Field(..., description="Orbit type")
    agency: str = Field(
        ...,
        min_length=3,
        max_length=4,
        description="Agency code",
    )
    gps_week: int = Field(..., ge=0, description="GPS week")
    seconds_of_week: float = Field(
        ...,
        ge=0,
        lt=604800,
        description="Seconds of week",
    )
    epoch_interval: float = Field(
        ...,
        gt=0,
        description="Epoch interval in seconds",
    )
    mjd_start: int = Field(..., description="Modified Julian Day start")
    fractional_day: float = Field(..., ge=0, lt=1, description="Fractional day")
    num_satellites: int = Field(
        ...,
        gt=0,
        le=200,
        description="Number of satellites",
    )

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate SP3 version string."""
        if not (v.startswith("#d") or v.startswith("#P")):
            raise ValueError("SP3 version must start with #d or #P")
        return v

    @field_validator("coordinate_system")
    @classmethod
    def validate_coordinate_system(cls, v: str) -> str:
        """Validate coordinate system."""
        valid_systems = ["IGS20", "IGS14", "IGb14", "ITRF2020", "WGS84"]
        if v not in valid_systems:
            raise ValueError(f"Coordinate system must be one of {valid_systems}")
        return v


class ClkHeader(BaseModel):
    """Pydantic model for RINEX CLK file header validation.

    Validates the header section of RINEX clock correction files
    according to RINEX 3.04 specifications.
    """

    version: str = Field(..., pattern=r"^3\.04", description="RINEX version")
    file_type: Literal["C"] = Field(..., description="Clock file type")
    time_system: str = Field(
        ...,
        description="Time system (GPS, GLO, GAL, BDS, QZSS)",
    )
    leap_seconds: int = Field(..., ge=0, description="Leap seconds")
    agency: str = Field(..., description="Analysis center")
    num_solution_stations: int = Field(
        ...,
        ge=0,
        description="Number of solution stations",
    )
    num_solution_satellites: int = Field(
        ...,
        gt=0,
        description="Number of solution satellites",
    )
    analysis_center: str = Field(
        ...,
        description="Analysis center name",
    )
    pcvs_applied: dict[str, str] = Field(
        default_factory=dict,
        description="PCV models applied",
    )
    dcbs_applied: dict[str, str] = Field(
        default_factory=dict,
        description="DCB sources applied",
    )

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, v: str) -> str:
        """Validate file type is clock."""
        if v != "C":
            raise ValueError("Must be clock file (type C)")
        return v

    @field_validator("time_system")
    @classmethod
    def validate_time_system(cls, v: str) -> str:
        """Validate time system."""
        valid_systems = ["GPS", "GLO", "GAL", "BDS", "QZSS", "IRNSS"]
        if v not in valid_systems:
            raise ValueError(f"Time system must be one of {valid_systems}")
        return v


class ProductRequest(BaseModel):
    """Request model for downloading auxiliary products.

    Validates all parameters required to download an auxiliary file,
    including date format, agency/product availability, and file format
    compatibility.
    """

    date: str = Field(
        ...,
        pattern=r"^\d{7}$",
        description="Date in YYYYDOY format",
    )
    agency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Agency code (3 letters)",
    )
    product_type: Literal["final", "rapid"] = Field(..., description="Product type")
    file_format: Literal["SP3", "CLK"] = Field(..., description="File format")
    local_dir: Path = Field(..., description="Local directory for storage")

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        """Validate YYYYDOY format.

        Parameters
        ----------
        v : str
            Date string in YYYYDOY format.

        Returns
        -------
        str
            Validated date string.

        Raises
        ------
        ValueError
            If format is invalid.
        """
        try:
            year = int(v[:4])
            doy = int(v[4:])
            if not (1980 <= year <= 2100):
                raise ValueError(f"Year {year} out of range [1980-2100]")
            if not (1 <= doy <= 366):
                raise ValueError(f"Day of year {doy} out of range [1-366]")
        except ValueError as e:
            raise ValueError(f"Invalid YYYYDOY format: {v}") from e
        return v

    @model_validator(mode="after")
    def validate_product_exists(self) -> Self:
        """Check if product is available in registry.

        Returns
        -------
        ProductRequest
            Validated ProductRequest.

        Raises
        ------
        ValueError
            If product not available in registry or format not supported.
        """
        from canvod.auxiliary.products.registry_config import get_product_spec

        try:
            spec = get_product_spec(self.agency, self.product_type)
        except KeyError as e:
            raise ValueError(f"Product not available: {e}") from e

        if self.file_format not in spec.available_formats:
            raise ValueError(
                f"{self.file_format} not available for {self.agency}/"
                f"{self.product_type}. Available formats: "
                f"{spec.available_formats}"
            )

        return self


class FileValidationResult(BaseModel):
    """Result of file format validation.

    Stores validation results including success status, errors, and warnings.
    """

    is_valid: bool = Field(..., description="Whether file passed validation")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    file_path: Path = Field(..., description="Path to validated file")
    file_type: Literal["SP3", "CLK"] = Field(..., description="File type")

    def add_error(self, error: str) -> None:
        """Add validation error."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add validation warning."""
        self.warnings.append(warning)

    def summary(self) -> str:
        """Get validation summary."""
        status = "✅ VALID" if self.is_valid else "❌ INVALID"
        lines = [
            f"Validation Result: {status}",
            f"File: {self.file_path}",
            f"Type: {self.file_type}",
        ]

        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            lines.extend(f"  - {e}" for e in self.errors)

        if self.warnings:
            lines.append(f"\nWarnings ({len(self.warnings)}):")
            lines.extend(f"  - {w}" for w in self.warnings)

        return "\n".join(lines)
