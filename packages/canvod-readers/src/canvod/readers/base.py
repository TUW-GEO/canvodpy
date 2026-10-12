"""Abstract base class for GNSS data readers.

Defines interface that all readers (RINEX v3, RINEX v2, SBF, future formats)
must implement to ensure compatibility with downstream pipeline:
- VOD calculation (canvod-vod)
- Storage (canvod-store / MyIcechunkStore)
- Grid operations (canvod-grids)

Contract constants (``REQUIRED_DIMS``, ``REQUIRED_COORDS``, etc.) are the
single source of truth for the output Dataset structure.  Use
:func:`validate_dataset` to check any Dataset against them.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Final

import xarray as xr
from pydantic import BaseModel, ConfigDict, field_validator

from canvod.readers.gnss_specs.constellations import SV_PATTERN

# ---------------------------------------------------------------------------
# Contract constants — single source of truth
# ---------------------------------------------------------------------------

REQUIRED_DIMS: Final = ("epoch", "sid")

REQUIRED_COORDS: Final = {
    "epoch": "datetime64[ns]",
    "sid": "object",
    "sv": "object",
    "system": "object",
    "band": "object",
    "code": "object",
    "freq_center": "float32",
    "freq_min": "float32",
    "freq_max": "float32",
}

REQUIRED_ATTRS: Final = {"Created", "Software", "Institution", "File Hash"}

DEFAULT_REQUIRED_VARS: Final = ["SNR"]

#: Data variables of a VOD dataset (VOD calculator output, VOD store input).
VOD_REQUIRED_VARS: Final = ("VOD", "phi", "theta")


# ---------------------------------------------------------------------------
# Standalone validation function
# ---------------------------------------------------------------------------


def _structure_errors(ds: xr.Dataset, required_vars: list[str]) -> list[str]:
    """Violations of the ``(epoch, sid)`` dimensions, coordinates and variables."""
    errors: list[str] = []

    # -- dimensions --
    missing_dims = set(REQUIRED_DIMS) - set(ds.dims)
    if missing_dims:
        errors.append(f"Missing required dimensions: {missing_dims}")

    # -- coordinates --
    for coord, expected_dtype in REQUIRED_COORDS.items():
        if coord not in ds.coords:
            errors.append(f"Missing required coordinate: {coord}")
            continue

        actual_dtype = str(ds[coord].dtype)
        if expected_dtype == "object":
            # Accept object (VariableLengthUTF8, stable Zarr V3) and numpy 2.0
            # StringDType (same stable type, different numpy representation).
            # Reject <U* (FixedLengthUTF32) — no stable Zarr V3 spec.
            is_valid_string = actual_dtype == "object" or actual_dtype.startswith(
                "StringDType"
            )
            if not is_valid_string:
                errors.append(
                    f"Coordinate {coord} has wrong dtype: "
                    f"expected string (object/StringDType), got {actual_dtype}"
                )
        elif expected_dtype not in actual_dtype:
            errors.append(
                f"Coordinate {coord} has wrong dtype: "
                f"expected {expected_dtype}, got {actual_dtype}"
            )

    # -- data variables --
    missing_vars = set(required_vars) - set(ds.data_vars)
    if missing_vars:
        errors.append(f"Missing required data variables: {missing_vars}")

    expected_var_dims = ("epoch", "sid")
    for var in ds.data_vars:
        if ds[var].dims != expected_var_dims:
            errors.append(
                f"Data variable {var} has wrong dimensions: "
                f"expected {expected_var_dims}, got {ds[var].dims}"
            )
    return errors


def _raise_if(errors: list[str], what: str) -> None:
    if errors:
        raise ValueError(
            f"{what} validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def validate_dataset(ds: xr.Dataset, required_vars: list[str] | None = None) -> None:
    """Validate *ds* meets the GNSSDataReader output contract.

    Collects **all** violations and raises a single ``ValueError`` listing
    every problem, rather than stopping at the first failure.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to validate.
    required_vars : list of str, optional
        Data variables that must be present.  Defaults to
        :data:`DEFAULT_REQUIRED_VARS` (``["SNR"]``).

    Raises
    ------
    ValueError
        If any contract violation is found.
    """
    if required_vars is None:
        required_vars = list(DEFAULT_REQUIRED_VARS)

    errors = _structure_errors(ds, required_vars)

    # -- attributes --
    missing_attrs = REQUIRED_ATTRS - set(ds.attrs.keys())
    if missing_attrs:
        errors.append(f"Missing required attributes: {missing_attrs}")

    _raise_if(errors, "Dataset")


def validate_vod_dataset(ds: xr.Dataset) -> None:
    """Validate *ds* meets the VOD dataset contract.

    The contract of VOD calculator output and of what the VOD store
    accepts: the dimensions and coordinates of :func:`validate_dataset`,
    the variables :data:`VOD_REQUIRED_VARS` (``theta`` and ``phi`` in
    radians), every variable on ``(epoch, sid)``. Collects **all**
    violations and raises a single ``ValueError``.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to validate.

    Raises
    ------
    ValueError
        If any contract violation is found.
    """
    _raise_if(_structure_errors(ds, list(VOD_REQUIRED_VARS)), "VOD dataset")


# ---------------------------------------------------------------------------
# Pydantic validator — runtime contract enforcement
# ---------------------------------------------------------------------------


def require_aggregated_glonass(reader: str, aggregate_glonass_fdma: bool) -> bool:
    """Refuse ``aggregate_glonass_fdma=False`` for a reader that cannot honor it.

    Parameters
    ----------
    reader : str
        Reader name for the message (e.g. ``"SBF"``).
    aggregate_glonass_fdma : bool
        The requested setting.

    Returns
    -------
    bool
        ``True``.

    Raises
    ------
    ValueError
        If ``aggregate_glonass_fdma`` is ``False``.
    """
    if not aggregate_glonass_fdma:
        msg = (
            f"The reader {reader} gives GLONASS FDMA signals as aggregated G1/G2 "
            f"bands only. Set processing.params.aggregate_glonass_fdma to true "
            f"for its data."
        )
        raise ValueError(msg)
    return aggregate_glonass_fdma


class DatasetStructureValidator(BaseModel):
    """Validates that an xarray.Dataset meets the GNSSDataReader contract.

    Wraps a Dataset and checks it against the contract constants above.
    Use this in tests and reader implementations to catch structural errors
    early with clear messages.

    Examples
    --------
    >>> validator = DatasetStructureValidator(dataset=ds)
    >>> validator.validate_all()          # raises ValueError on any violation
    >>> validator.validate_dimensions()   # check just one aspect
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset: xr.Dataset

    def validate_all(self, required_vars: list[str] | None = None) -> None:
        """Run all validations, collecting **all** errors.

        Delegates to :func:`validate_dataset` so the logic lives in one place.
        """
        validate_dataset(self.dataset, required_vars=required_vars)

    def validate_dimensions(self) -> None:
        """Check that required dimensions (epoch, sid) exist."""
        missing = set(REQUIRED_DIMS) - set(self.dataset.dims)
        if missing:
            raise ValueError(f"Missing required dimensions: {missing}")

    def validate_coordinates(self) -> None:
        """Check that required coordinates exist with correct dtypes."""
        for coord, expected_dtype in REQUIRED_COORDS.items():
            if coord not in self.dataset.coords:
                raise ValueError(f"Missing required coordinate: {coord}")
            actual = str(self.dataset[coord].dtype)
            if expected_dtype == "object":
                is_valid_string = actual == "object" or actual.startswith("StringDType")
                if not is_valid_string:
                    raise ValueError(
                        f"Coordinate {coord}: expected string (object/StringDType), got {actual}"
                    )
            elif expected_dtype not in actual:
                raise ValueError(
                    f"Coordinate {coord}: expected {expected_dtype}, got {actual}"
                )

    def validate_data_variables(self, required_vars: list[str] | None = None) -> None:
        """Check that required data variables exist with correct dims."""
        if required_vars is None:
            required_vars = list(DEFAULT_REQUIRED_VARS)
        missing = set(required_vars) - set(self.dataset.data_vars)
        if missing:
            raise ValueError(f"Missing required data variables: {missing}")
        for var in self.dataset.data_vars:
            if self.dataset[var].dims != REQUIRED_DIMS:
                raise ValueError(
                    f"Variable {var}: expected dims {REQUIRED_DIMS}, "
                    f"got {self.dataset[var].dims}"
                )

    def validate_attributes(self) -> None:
        """Check that required global attributes are present."""
        missing = REQUIRED_ATTRS - set(self.dataset.attrs.keys())
        if missing:
            raise ValueError(f"Missing required attributes: {missing}")


# ---------------------------------------------------------------------------
# Signal ID model
# ---------------------------------------------------------------------------


class SignalID(BaseModel):
    """Validated signal identifier (SV + band + code).

    >>> sid = SignalID(sv="G01", band="L1", code="C")
    >>> str(sid)
    'G01|L1|C'
    >>> sid.system
    'G'
    """

    model_config = ConfigDict(frozen=True)

    sv: str
    band: str
    code: str

    @field_validator("sv")
    @classmethod
    def _validate_sv(cls, v: str) -> str:
        if not SV_PATTERN.match(v):
            raise ValueError(
                f"Invalid SV: {v!r}; expected system letter + 2-digit PRN "
                f"(e.g. 'G01'). Valid systems: G, R, E, C, J, S, I"
            )
        return v

    @property
    def system(self) -> str:
        """GNSS system letter (e.g. 'G' for GPS)."""
        return self.sv[0]

    @property
    def sid(self) -> str:
        """Full signal ID string ('SV|band|code')."""
        return f"{self.sv}|{self.band}|{self.code}"

    def __str__(self) -> str:
        return self.sid

    def __hash__(self) -> int:
        return hash(self.sid)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SignalID):
            return self.sid == other.sid
        return NotImplemented

    @classmethod
    def from_string(cls, sid_str: str) -> SignalID:
        """Parse a signal ID string ('SV|band|code') into a SignalID.

        Parameters
        ----------
        sid_str : str
            Signal ID in 'SV|band|code' format (e.g. 'G01|L1|C').

        Returns
        -------
        SignalID
            Validated signal identifier.

        Raises
        ------
        ValueError
            If the string does not have exactly three pipe-separated parts.
        """
        parts = sid_str.split("|")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid SID format: {sid_str!r}; expected 'SV|band|code'"
            )
        return cls(sv=parts[0], band=parts[1], code=parts[2])


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class GNSSDataReader(BaseModel, ABC):
    """Abstract base class for all GNSS data format readers.

    All readers must:
    1. Inherit from this class
    2. Implement all abstract methods
    3. Return xarray.Dataset that passes :func:`validate_dataset`
    4. Provide file hash for deduplication

    This ensures compatibility with:
    - canvod-vod: VOD calculation
    - canvod-store: MyIcechunkStore storage
    - canvod-grids: Grid projection operations

    Subclasses may override ``model_config`` to set ``frozen``, ``extra``,
    etc.  The base class provides ``arbitrary_types_allowed=True`` which is
    needed by readers that use ``pint.Quantity`` or similar third-party types.

    Examples
    --------
    >>> class Rnxv3Obs(GNSSDataReader):
    ...     def to_ds(self, **kwargs) -> xr.Dataset:
    ...         # Implementation
    ...         return dataset
    ...
    >>> reader = Rnxv3Obs(fpath="station.24o")
    >>> ds = reader.to_ds()
    >>> validate_dataset(ds)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    #: Canonical file type of the files the reader reads: the TYPE field of
    #: a canVOD file name (``"rnx"``, ``"sbf"``, ``"nmea"``, or a new type
    #: of a plugin reader). Every reader sets it.
    file_type: ClassVar[str]

    #: Whether the reader can give GLONASS FDMA signals per frequency
    #: channel. Readers that cannot refuse ``aggregate_glonass_fdma=False``.
    per_channel_glonass: ClassVar[bool] = False

    fpath: Path
    aggregate_glonass_fdma: bool = True

    @field_validator("aggregate_glonass_fdma")
    @classmethod
    def _glonass_channels_supported(cls, v: bool) -> bool:
        """Refuse ``False`` unless the reader gives per-channel GLONASS."""
        if cls.per_channel_glonass:
            return v
        return require_aggregated_glonass(cls.__name__, v)

    @field_validator("fpath")
    @classmethod
    def _validate_fpath(cls, v: Path) -> Path:
        """Validate that the file path points to an existing file."""
        v = Path(v)
        if not v.is_file():
            raise FileNotFoundError(f"File not found: {v}")
        return v

    @property
    @abstractmethod
    def source_format(self) -> str:
        """Return the format identifier for this reader (e.g. ``"rinex3"``, ``"sbf"``).

        The orchestrator writes it to the GNSS store as the ``source_format``
        root attribute.
        """

    @property
    @abstractmethod
    def file_hash(self) -> str:
        """Return SHA256 hash of file for deduplication.

        Used by MyIcechunkStore to avoid duplicate ingestion.
        Must be deterministic and reproducible.

        Returns
        -------
        str
            Short hash (16 chars) or full hash of file content
        """

    @abstractmethod
    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert data to xarray.Dataset.

        Must return Dataset with structure:
        - Dims: (epoch, sid)
        - Coords: epoch, sid, sv, system, band, code, freq_*
        - Data vars: At minimum SNR
        - Attrs: Must include "File Hash"

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to include. If None, includes all available.
        **kwargs
            Implementation-specific parameters

        Returns
        -------
        xr.Dataset
            Dataset that passes :func:`validate_dataset`.
        """

    @abstractmethod
    def iter_epochs(self) -> Iterator[object]:
        """Iterate over epochs in the file.

        Yields
        ------
        Epoch
            Parsed epoch with satellites and observations.
        """

    def to_ds_and_auxiliary(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
        """Produce the obs dataset and any auxiliary datasets in a single call.

        Default: calls ``to_ds(**kwargs)`` and returns an empty auxiliary dict.
        Readers that produce metadata (e.g. SBF) override this to collect both
        in a single file scan.

        Returns
        -------
        tuple[xr.Dataset, dict[str, xr.Dataset]]
            ``(obs_ds, {"name": aux_ds, ...})``.  Auxiliary dict is empty for
            readers with no extra data (RINEX v2/v3).
        """
        return self.to_ds(keep_data_vars=keep_data_vars, **kwargs), {}

    def _build_attrs(self) -> dict[str, str]:
        """Build standard global attributes for the output Dataset.

        Reads institution/author from config, adds timestamp, version,
        and the file hash.

        Returns
        -------
        dict[str, str]
            Ready-to-use attrs dict.
        """
        from canvod.readers.gnss_specs.metadata import get_global_attrs
        from canvod.readers.gnss_specs.utils import get_version_from_pyproject

        attrs = get_global_attrs()
        attrs["Created"] = datetime.now(UTC).isoformat()
        attrs["Software"] = (
            f"{attrs['Software']}, Version: {get_version_from_pyproject()}"
        )
        attrs["File Hash"] = self.file_hash
        return attrs

    @property
    @abstractmethod
    def start_time(self) -> datetime:
        """Return start time of observations.

        Returns
        -------
        datetime
            First observation timestamp in the file.
        """

    @property
    @abstractmethod
    def end_time(self) -> datetime:
        """Return end time of observations.

        Returns
        -------
        datetime
            Last observation timestamp in the file.
        """

    @property
    @abstractmethod
    def systems(self) -> list[str]:
        """Return list of GNSS systems in file.

        Returns
        -------
        list of str
            System identifiers: 'G', 'R', 'E', 'C', 'J', 'S', 'I'
        """

    @property
    def num_epochs(self) -> int:
        """Return number of epochs in file.

        Default implementation iterates epochs.  Subclasses may override
        with a faster approach.

        Returns
        -------
        int
            Total number of observation epochs.
        """
        return sum(1 for _ in self.iter_epochs())

    @property
    @abstractmethod
    def num_satellites(self) -> int:
        """Return total number of unique satellites observed.

        Returns
        -------
        int
            Count of unique satellite vehicles across all systems.
        """

    def __repr__(self) -> str:
        """Return the string representation."""
        return f"{self.__class__.__name__}(file='{self.fpath.name}')"


__all__ = [
    "DEFAULT_REQUIRED_VARS",
    "REQUIRED_ATTRS",
    "REQUIRED_COORDS",
    "REQUIRED_DIMS",
    "VOD_REQUIRED_VARS",
    "DatasetStructureValidator",
    "GNSSDataReader",
    "SignalID",
    "validate_dataset",
    "validate_vod_dataset",
]
