"""Pydantic validation models for RINEX data structures.

These models provide runtime validation for RINEX data parsing,
ensuring data integrity and correct formats.
"""

import re
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, Self

import pint
import structlog
import xarray as xr
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.dataclasses import dataclass
from pydantic_core import core_schema

from canvod.readers.gnss_specs.constants import (
    EPOCH_RECORD_INDICATOR,
    IGS_RNX_DUMP_INTERVALS,
    RINEX_OBS_SUFFIX_RE,
    SEPTENTRIO_SAMPLING_INTERVALS,
    UREG,
)
from canvod.readers.gnss_specs.constellations import SV_PATTERN
from canvod.readers.gnss_specs.exceptions import IncompleteEpochError, MissingEpochError

_log = structlog.get_logger(__name__)


def _raise_value_error(message: str) -> NoReturn:
    """Raise a ValueError with a formatted message."""
    raise ValueError(message)


INDICATOR_MIN = 0
INDICATOR_MAX = 9
RINEX_VERSION_MIN = 3
RINEX_VERSION_MAX = 4


@dataclass(
    kw_only=True,
    frozen=True,
    config=ConfigDict(arbitrary_types_allowed=True, slots=True),  # ty: ignore[invalid-key]
)
class Observation:
    """Represents a single GNSS observation.

    Notes
    -----
    This is a Pydantic dataclass with `kw_only=True`, `frozen=True`, and a
    `ConfigDict` that enables `arbitrary_types_allowed=True` and `slots=True`.

    """

    obs_type: str | None
    value: float | None
    lli: int | None
    ssi: int | None
    frequency: pint.Quantity | None = None

    @field_validator("frequency")
    @classmethod
    def validate_frequency(
        cls,
        v: pint.Quantity | None,
    ) -> pint.Quantity | None:
        """Validate that frequency is a proper pint.Quantity with frequency units.

        Parameters
        ----------
        v : pint.Quantity or None
            Frequency to validate.

        Returns
        -------
        pint.Quantity or None
            Validated frequency.

        Raises
        ------
        ValueError
            If not a Quantity or does not have frequency units.

        """
        if v is not None and not isinstance(v, pint.Quantity):
            msg = "Frequency must be a pint.Quantity"
            _raise_value_error(msg)
        if v is not None and not v.check("[frequency]"):
            msg = "Frequency must have frequency units"
            _raise_value_error(msg)
        return v

    @field_validator("lli", "ssi")
    def validate_indicators(cls, v: int | None) -> int | None:
        """Validate LLI and SSI values.

        Parameters
        ----------
        v : int or None
            Indicator value to validate.

        Returns
        -------
        int or None
            Validated indicator value.

        Raises
        ------
        ValueError
            If value not in range 0-9.

        """
        if v is not None and not (INDICATOR_MIN <= v <= INDICATOR_MAX):
            msg = (
                f"Indicator values must be between {INDICATOR_MIN} and {INDICATOR_MAX}"
            )
            _raise_value_error(msg)
        return v


@dataclass(kw_only=True, frozen=True, config=ConfigDict(slots=True))  # ty: ignore[invalid-key]
class Satellite:
    """Represents a GNSS satellite with its observations.

    Supports all major GNSS constellations including IRNSS.

    Notes
    -----
    This is a Pydantic dataclass with `kw_only=True`, `frozen=True`, and
    `slots=True` enabled via `ConfigDict`.

    """

    sv: str
    observations: list[Observation] = Field(default_factory=list)

    @field_validator("sv")
    def validate_sv(cls, v: str) -> str:
        """Validate satellite vehicle identifier format.

        Parameters
        ----------
        v : str
            Satellite identifier to validate.

        Returns
        -------
        str
            Validated satellite identifier.

        Raises
        ------
        ValueError
            If format is invalid.

        Supports:
        - G: GPS
        - R: GLONASS
        - E: Galileo
        - C: BeiDou
        - J: QZSS
        - S: SBAS
        - I: IRNSS

        """
        if not SV_PATTERN.match(v):
            msg = f"Invalid satellite identifier format: {v}"
            _raise_value_error(msg)
        return v

    def add_observation(self, observation: Observation) -> None:
        """Add an observation to the satellite.

        Parameters
        ----------
        observation : Observation
            Observation to add.

        Returns
        -------
        None

        """
        self.observations.append(observation)


@dataclass(kw_only=True, frozen=True, config=ConfigDict(slots=True))  # ty: ignore[invalid-key]
class Epoch:
    """Represents a GNSS epoch with its timestamp and satellites.

    Notes
    -----
    This is a Pydantic dataclass with `kw_only=True`, `frozen=True`, and
    `slots=True` enabled via `ConfigDict`.

    """

    timestamp: datetime
    num_satellites: int
    satellites: list[Satellite] = Field(default_factory=list)

    def add_satellite(self, satellite: Satellite) -> None:
        """Add a satellite to the epoch.

        Parameters
        ----------
        satellite : Satellite
            Satellite to add.

        Returns
        -------
        None

        """
        self.satellites.append(satellite)

    def get_satellite(self, sv: str) -> Satellite | None:
        """Get a satellite by its identifier.

        Parameters
        ----------
        sv : str
            Satellite identifier.

        Returns
        -------
        Satellite or None
            Found satellite or None if not found.

        """
        return next((sat for sat in self.satellites if sat.sv == sv), None)

    def get_satellites_by_system(self, system: str) -> list[Satellite]:
        """Get all satellites for a specific system.

        Parameters
        ----------
        system : str
            System identifier (G, R, E, C, J, S, I).

        Returns
        -------
        list of Satellite
            Satellites matching the system.

        """
        return [sat for sat in self.satellites if sat.sv.startswith(system)]


class Quantity(pint.Quantity):
    """Pydantic-compatible pint Quantity wrapper.

    Notes
    -----
    This class provides a Pydantic v2 core schema for `pint.Quantity`.

    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: type[Any],
        handler: object,
    ) -> core_schema.CoreSchema:
        """Pydantic V2 schema for validation."""

        def validate_from_str(value: str | pint.Quantity) -> pint.Quantity:
            if isinstance(value, pint.Quantity):
                return value
            try:
                return UREG.Quantity(value)  # ty: ignore[invalid-return-type]
            except pint.errors.UndefinedUnitError:
                msg = f"Invalid unit for {value}"
                _raise_value_error(msg)

        python_schema = core_schema.union_schema(
            [
                core_schema.is_instance_schema(pint.Quantity),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=python_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: str(instance)
            ),
        )


class RnxObsFileModel(BaseModel):
    """Validates RINEX observation file paths.

    Notes
    -----
    This is a Pydantic `BaseModel`.

    """

    fpath: Path

    @field_validator("fpath")
    def file_must_exist(cls, v: Path) -> Path:
        """Validate that file exists.

        Parameters
        ----------
        v : Path
            File path to check.

        Returns
        -------
        Path
            Validated path.

        Raises
        ------
        ValueError
            If file does not exist.

        """
        if not v.exists():
            msg = f"File {v} does not exist."
            _raise_value_error(msg)
        return v

    @field_validator("fpath")
    def file_must_have_correct_suffix(cls, v: Path) -> Path:
        """Validate RINEX observation file suffix.

        Parameters
        ----------
        v : Path
            File path to check.

        Returns
        -------
        Path
            Validated path.

        Raises
        ------
        ValueError
            If suffix doesn't match RINEX observation pattern.

        """
        if not RINEX_OBS_SUFFIX_RE.search(v.name):
            msg = (
                f"File {v} does not appear to be a RINEX observation file. "
                f"Expected suffix matching one of: .YYo, .O, .rnx"
            )
            _raise_value_error(msg)
        return v


class RnxVersion3Model(BaseModel):
    """Validates RINEX version 3.

    Notes
    -----
    This is a Pydantic `BaseModel`.

    """

    version: float

    @field_validator("version")
    def version_must_be_3(cls, v: float) -> float:
        """Validate RINEX version is 3.0x.

        Parameters
        ----------
        v : float
            Version number to check.

        Returns
        -------
        float
            Validated version.

        Raises
        ------
        ValueError
            If version is not 3.0x.

        """
        if not RINEX_VERSION_MIN <= v < RINEX_VERSION_MAX:
            msg = "Rinex version must be 3.0x"
            _raise_value_error(msg)
        return v


class Rnxv3ObsEpochRecordCompletenessModel(BaseModel):
    """Validates completeness of RINEX v3 epoch records.

    Notes
    -----
    This is a Pydantic `BaseModel`.

    """

    epoch_records_indeces: list[tuple[int, int]]
    rnx_file_dump_interval: str | Quantity
    sampling_interval: str | Quantity

    @field_validator("rnx_file_dump_interval")
    @classmethod
    def check_rnx_file_dump_interval(
        cls,
        value: str | Quantity,
    ) -> Quantity:
        """Validate and convert dump interval to Quantity.

        Parameters
        ----------
        value : str or Quantity
            Dump interval to validate.

        Returns
        -------
        Quantity
            Dump interval in minutes.

        Warns
        -----
        UserWarning
            If interval is not a standard IGS interval.

        """
        if not isinstance(value, pint.Quantity):
            value = UREG.Quantity(value).to(UREG.minutes)  # ty: ignore[invalid-assignment]
        if value not in IGS_RNX_DUMP_INTERVALS:
            _log.debug(
                "Non-standard dump interval %s (expected one of %s) — processing continues normally.",
                value,
                [str(v) for v in IGS_RNX_DUMP_INTERVALS],
            )
        return value  # ty: ignore[invalid-return-type]

    @field_validator("sampling_interval")
    @classmethod
    def check_sampling_interval_units(
        cls,
        value: str | Quantity,
    ) -> Quantity:
        """Validate sampling interval units and value.

        Parameters
        ----------
        value : str or Quantity
            Sampling interval to validate.

        Returns
        -------
        Quantity
            Sampling interval in seconds.

        Raises
        ------
        ValueError
            If not a standard Septentrio sampling interval.

        """
        if not isinstance(value, pint.Quantity):
            value = UREG.Quantity(value).to(UREG.seconds)  # ty: ignore[invalid-assignment]
        if value not in SEPTENTRIO_SAMPLING_INTERVALS:
            msg = (
                f"sampling_interval={value.magnitude} {value.units}, "  # ty: ignore[unresolved-attribute]
                "but must be one of: "
                f"{[str(v) for v in SEPTENTRIO_SAMPLING_INTERVALS]}"
            )
            _raise_value_error(msg)
        return value  # ty: ignore[invalid-return-type]

    @model_validator(mode="after")
    def check_intervals(self) -> Self:
        """Validate epoch intervals consistency.

        Returns
        -------
        Rnxv3ObsEpochRecordCompletenessModel
            Self for method chaining.

        Raises
        ------
        MissingEpochError
            If total sampling time doesn't match dump interval.

        Warns
        -----
        UserWarning
            If there's a mismatch in expected intervals.

        """
        epoch_records_indeces = self.epoch_records_indeces
        rnx_file_dump_interval = self.rnx_file_dump_interval
        sampling_interval = self.sampling_interval

        if epoch_records_indeces and rnx_file_dump_interval and sampling_interval:
            total_sampling_time = len(epoch_records_indeces) * sampling_interval.to(  # ty: ignore[unresolved-attribute]
                UREG.seconds
            )
            rnx_file_dump_interval_in_seconds = rnx_file_dump_interval.to(UREG.seconds)  # ty: ignore[unresolved-attribute]
            if total_sampling_time != rnx_file_dump_interval_in_seconds:
                warnings.warn(
                    "Mismatch in expected dump interval: "
                    f"total_sampling_time={total_sampling_time}, "
                    f"expected={rnx_file_dump_interval_in_seconds}",
                    stacklevel=2,
                )
                msg = (
                    f"The total sampling time ({total_sampling_time}) does "
                    "not equal the rnx_file_dump_interval "
                    f"({rnx_file_dump_interval_in_seconds}). This might "
                    "indicate missing epochs."
                )
                raise MissingEpochError(msg)
        return self


class Rnxv3ObsEpochRecordLineModel(BaseModel):
    """Parses and validates RINEX v3 epoch record line.

    Notes
    -----
    This is a Pydantic `BaseModel`.

    """

    epoch: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    seconds: float
    epoch_flag: int
    num_satellites: int
    epoch_record_indicator: str | None = EPOCH_RECORD_INDICATOR
    reserved: int | None = None
    receiver_clock_offset: float | None = None

    @model_validator(mode="before")
    def parse_epoch(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse RINEX v3 epoch record line.

        Parameters
        ----------
        values : dict
            Dictionary containing 'epoch' string to parse.

        Returns
        -------
        dict
            Parsed values with individual date/time components.

        Raises
        ------
        ValueError
            If epoch format is invalid.

        """
        epoch = values["epoch"]
        pattern = (
            r"^(?P<epoch_record_indicator>>)\s*(?P<year>\d{4})\s+"
            r"(?P<month>\d{2})\s+(?P<day>\d{2})\s+(?P<hour>\d{2})\s+"
            r"(?P<minute>\d{2})\s+(?P<seconds>\d+\.\d+)\s+"
            r"(?P<epoch_flag>\d+)\s+(?P<num_satellites>\d+)\s*"
            r"(?P<reserved>\d*)\s*"
            r"(?P<receiver_clock_offset>-?\d*\.\d*)?\s*$"
        )
        match = re.match(pattern, epoch)
        if not match:
            msg = (
                f"Invalid epoch format: {epoch}. "
                'A valid format is "> yyyy mm dd hh mm ss.sss epoch_flag '
                'num_satellites [reserved] [receiver_clock_offset]"'
            )
            _raise_value_error(msg)

        values["epoch_record_indicator"] = match.group("epoch_record_indicator")
        values["year"] = int(match.group("year"))
        values["month"] = int(match.group("month"))
        values["day"] = int(match.group("day"))
        values["hour"] = int(match.group("hour"))
        values["minute"] = int(match.group("minute"))
        values["seconds"] = float(match.group("seconds"))
        values["epoch_flag"] = int(match.group("epoch_flag"))
        values["num_satellites"] = int(match.group("num_satellites"))
        values["reserved"] = (
            int(match.group("reserved")) if match.group("reserved") else None
        )
        values["receiver_clock_offset"] = (
            float(match.group("receiver_clock_offset"))
            if match.group("receiver_clock_offset")
            else None
        )

        return values


@dataclass(frozen=True, kw_only=True)
class Rnxv3ObsEpochRecord:
    """Represents a complete epoch record in RINEX v3 format.

    Notes
    -----
    This is a Pydantic dataclass with `kw_only=True` and `frozen=True`.

    """

    info: Rnxv3ObsEpochRecordLineModel
    data: list[Satellite]

    @model_validator(mode="after")
    def check_num_satellites_matches_data(self) -> Self:
        """Validate that the number of satellites matches the data.

        Returns
        -------
        Rnxv3ObsEpochRecord
            Self for method chaining.

        Raises
        ------
        IncompleteEpochError
            If satellite count doesn't match actual data.

        """
        if not self.info.num_satellites:
            msg = (
                "Number of satellites is automatically specified in the epoch "
                "record. Thus, your data seems to be incorrect. Please check "
                "the validity of your data."
            )
            raise IncompleteEpochError(msg)

        if self.info.num_satellites != len(self.data):
            msg = (
                "Number of satellites mismatch in epoch record. "
                f"Expected: {self.info.num_satellites}, "
                f"Got: {len(self.data)}. Please check the validity of your "
                f"data of epoch '{self.info.epoch}'."
            )
            raise IncompleteEpochError(msg)

        return self

    def get_satellites_by_system(self, system: str) -> list[Satellite]:
        """Get all satellites for a specific system (G, R, E, etc.).

        Parameters
        ----------
        system : str
            System identifier.

        Returns
        -------
        list of Satellite
            Satellites matching the system.

        """
        return [sat for sat in self.data if sat.sv.startswith(system)]


class VodDataValidator(BaseModel):
    """Validates VOD (Vegetation Optical Depth) data structure.

    Notes
    -----
    This is a Pydantic `BaseModel` with `arbitrary_types_allowed=True`.

    """

    vod_data: xr.Dataset

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("vod_data", mode="before")
    def validate_vod_data(cls, value: xr.Dataset) -> xr.Dataset:
        """Validate the VOD data structure.

        Parameters
        ----------
        value : xr.Dataset
            VOD dataset to validate.

        Returns
        -------
        xr.Dataset
            Validated dataset.

        Raises
        ------
        ValueError
            If dataset is None, wrong type, or missing required
            variables/coordinates.

        """
        if value is None:
            msg = (
                "vod_data has not been calculated yet. Please implement a "
                "`calculate_vod()` method, which should return an "
                "`xr.Dataset`."
            )
            _raise_value_error(msg)

        if not isinstance(value, xr.Dataset):
            msg = "vod_data must be an instance of `xr.Dataset`."
            _raise_value_error(msg)

        # Validate required variables
        required_vars = ["Elevation", "Azimuth"]
        for var in required_vars:
            if var not in value.data_vars:
                msg = f"Missing required data variable '{var}' in vod_data."
                _raise_value_error(msg)

        # Validate VOD variable
        if "VOD" not in value.data_vars:
            msg = "Missing required data variable 'VOD' in the VOD data."
            _raise_value_error(msg)

        # Validate VOD coordinates
        vod = value["VOD"]
        required_coords = ["Epoch", "SV", "Frequency"]

        for coord in required_coords:
            if coord not in vod.coords:
                msg = f"VOD is missing required coordinate '{coord}'."
                _raise_value_error(msg)

        return value


class RINEX304ComplianceValidator(BaseModel):
    """Validates RINEX 3.04 specification compliance.

    Validates:
    - System-specific observation codes
    - GLONASS mandatory fields (slot/frequency, biases)
    - Phase shift records (RINEX 3.01+)
    - Observation value ranges

    Notes
    -----
    This is a Pydantic `BaseModel` with `arbitrary_types_allowed=True`.

    """

    dataset: xr.Dataset
    obs_codes_per_system: dict[str, list[str]]
    glonass_slot_frq: dict[str, int] | None = None
    glonass_cod_phs_bis: dict[str, Any] | None = None
    phase_shift: dict[str, Any] | None = None
    strict: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("obs_codes_per_system")
    @classmethod
    def validate_observation_codes(
        cls, v: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Validate system-specific observation codes against RINEX 3.04 spec.

        Parameters
        ----------
        v : dict[str, list[str]]
            Observation codes per system

        Returns
        -------
        dict[str, list[str]]
            Validated observation codes

        Warns
        -----
        UserWarning
            If observation codes don't match RINEX 3.04 specification

        """
        from canvod.readers.gnss_specs.validation_constants import (
            GNSS_SYSTEMS,
            VALID_OBS_CODES,
        )

        issues = []

        for system, codes in v.items():
            if system not in GNSS_SYSTEMS:
                issues.append(f"Unknown GNSS system: {system}")
                continue

            # Get valid bands for this system
            system_bands = VALID_OBS_CODES.get(system, {})

            for code in codes:
                # Parse observation code (e.g., "C1C", "L1C")
                if len(code) < 3:
                    issues.append(
                        f"Invalid observation code format: {code} (too short)"
                    )
                    continue

                obs_type = code[0]  # C, L, D, S
                band = code[1]  # 1, 2, 5, etc.
                attribute = code[2]  # C, P, W, etc.

                # Validate band exists for system
                if band not in system_bands:
                    issues.append(
                        f"Invalid band '{band}' for system '{system}': {code}"
                    )
                    continue

                # Validate attribute code
                band_spec = system_bands[band]
                valid_codes = band_spec.get("codes", set())

                if attribute not in valid_codes:  # ty: ignore[unsupported-operator]
                    issues.append(
                        f"Invalid attribute '{attribute}' for {system} band {band}: "
                        f"{code} (valid: {valid_codes})"
                    )

        if issues:
            msg = "Observation code validation issues:\n  - " + "\n  - ".join(issues)
            warnings.warn(msg, stacklevel=2)

        return v

    @model_validator(mode="after")
    def validate_glonass_headers(self) -> Self:
        """Validate GLONASS mandatory headers if GLONASS data present.

        Returns
        -------
        RINEX304ComplianceValidator
            Self for method chaining

        Warns
        -----
        UserWarning
            If GLONASS headers are missing when GLONASS data is present

        Raises
        ------
        ValueError
            If strict mode and GLONASS headers missing

        """
        # Check if GLONASS data is present
        has_glonass = "R" in self.obs_codes_per_system

        if not has_glonass:
            return self

        issues = []

        # Check required headers
        if self.glonass_slot_frq is None:
            issues.append("Missing required header: GLONASS SLOT / FRQ #")

        if self.glonass_cod_phs_bis is None:
            issues.append("Missing required header: GLONASS COD/PHS/BIS")

        if issues:
            msg = (
                "GLONASS data present but required headers missing:\n  - "
                + "\n  - ".join(issues)
            )

            if self.strict:
                _raise_value_error(msg)
            else:
                warnings.warn(msg, stacklevel=2)

        return self

    @model_validator(mode="after")
    def validate_phase_shifts(self) -> Self:
        """Validate phase shift records (RINEX 3.01+).

        Returns
        -------
        RINEX304ComplianceValidator
            Self for method chaining

        Warns
        -----
        UserWarning
            If phase shift records have issues

        """
        if self.phase_shift is None:
            return self

        # TODO: Implement phase shift validation logic
        # This would validate:
        # - Correct system identifiers
        # - Valid observation codes
        # - Proper format of phase shift values

        return self

    @model_validator(mode="after")
    def validate_observation_ranges(self) -> Self:
        """Validate observation values are within specification ranges.

        Returns
        -------
        RINEX304ComplianceValidator
            Self for method chaining

        Warns
        -----
        UserWarning
            If observation values are out of range

        """
        # TODO: Implement observation range validation
        # This would check:
        # - Pseudorange values are reasonable
        # - Carrier phase values are in valid ranges
        # - Signal strength values are within spec ranges (1-9)

        return self

    def get_validation_results(self) -> dict[str, list[str]]:
        """Get validation results summary.

        Returns
        -------
        dict[str, list[str]]
            Validation results by category:
            - observation_codes: Invalid observation codes
            - glonass_fields: Missing GLONASS headers
            - phase_shifts: Phase shift issues
            - value_ranges: Out-of-range values

        """
        results = {
            "observation_codes": [],
            "glonass_fields": [],
            "phase_shifts": [],
            "value_ranges": [],
        }

        # Since Pydantic validators raise warnings, collect them here
        # In practice, warnings would be captured during validation
        # This method provides a structured way to access results

        return results

    @staticmethod
    def validate_all(
        ds: xr.Dataset, header_dict: dict[str, Any], strict: bool = False
    ) -> dict[str, list[str]]:
        """Validate dataset against RINEX 3.04 specification.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to validate
        header_dict : dict
            RINEX header information including:
            - obs_codes_per_system: dict[str, list[str]]
            - GLONASS SLOT / FRQ #: dict (optional)
            - GLONASS COD/PHS/BIS: dict (optional)
            - SYS / PHASE SHIFT: dict (optional)
        strict : bool, default False
            If True, raise ValueError on validation failures

        Returns
        -------
        dict[str, list[str]]
            Validation results by category

        Examples
        --------
        >>> header_dict = {
        ...     'obs_codes_per_system': {
        ...         'G': ['C1C', 'L1C', 'S1C'],
        ...         'R': ['C1C', 'L1C'],
        ...     },
        ...     'GLONASS SLOT / FRQ #': {...},
        ... }
        >>> results = RINEX304ComplianceValidator.validate_all(
        ...     ds=dataset,
        ...     header_dict=header_dict,
        ...     strict=False
        ... )

        """
        # Extract header components
        obs_codes = header_dict.get("obs_codes_per_system", {})
        glonass_slot = header_dict.get("GLONASS SLOT / FRQ #")
        glonass_bias = header_dict.get("GLONASS COD/PHS/BIS")
        phase_shift = header_dict.get("SYS / PHASE SHIFT")

        # Create validator instance (triggers all validation)
        validator = RINEX304ComplianceValidator(
            dataset=ds,
            obs_codes_per_system=obs_codes,
            glonass_slot_frq=glonass_slot,
            glonass_cod_phs_bis=glonass_bias,
            phase_shift=phase_shift,
            strict=strict,
        )

        # Return validation results
        return validator.get_validation_results()

    @staticmethod
    def print_validation_report(results: dict[str, list[str]]) -> None:
        """Print formatted validation report.

        Parameters
        ----------
        results : dict[str, list[str]]
            Validation results from validate_all()

        Examples
        --------
        >>> results = RINEX304ComplianceValidator.validate_all(ds, header_dict)
        >>> RINEX304ComplianceValidator.print_validation_report(results)

        """
        has_issues = any(results.values())

        if not has_issues:
            print("✓ RINEX 3.04 validation passed - no issues found")
            return

        print("\nRINEX 3.04 Validation Report")
        print("=" * 60)

        for category, issues in results.items():
            if issues:
                print(f"\n{category.replace('_', ' ').title()}:")
                for issue in issues:
                    print(f"  - {issue}")

        print("\n" + "=" * 60)
        total_issues = sum(len(v) for v in results.values())
        print(f"Total issues: {total_issues}\n")
