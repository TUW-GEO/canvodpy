"""Custom exceptions for GNSS readers.

Exception Hierarchy
-------------------
RinexError
    ├── AttributeOverrideError
    ├── MissingEpochError
    ├── CorruptedFileError
    ├── IncompleteEpochError
    ├── InvalidEpochError
    ├── FileNotExistError
    ├── RinexNavError (also a ValueError)
    └── StrippedRinexError (also a ValueError; canvod.readers.rinex)

NmeaError
    ├── NmeaChecksumError
    ├── NmeaMissingSentenceError
    └── NmeaInvalidSentenceError

All exceptions inherit from RinexError or NmeaError, allowing for broad
exception handling when needed while preserving specific error types.
"""


class RinexError(Exception):
    """Base exception for RINEX reader errors.

    All RINEX-specific exceptions inherit from this class, allowing
    applications to catch all reader errors with a single except clause.

    Examples
    --------
    >>> try:
    ...     reader = Rnxv3Obs("nonexistent.24o")
    ... except RinexError as e:
    ...     print(f"RINEX error: {e}")

    """


class AttributeOverrideError(RinexError):
    """Raised when attempting to override protected attribute.

    Used in Pydantic models to prevent modification of immutable
    attributes after initialization.

    Parameters
    ----------
    attribute : str
        Name of the attribute that was attempted to be overridden.

    Examples
    --------
    >>> raise AttributeOverrideError("fpath")
    AttributeOverrideError: Overriding attribute 'fpath' is not allowed...

    """

    def __init__(self, attribute: str) -> None:
        """Initialize with the protected attribute name."""
        super().__init__(
            f"Overriding attribute '{attribute}' is not allowed after initialization."
        )


class MissingEpochError(RinexError):
    """Raised when missing epochs detected in RINEX data.

    Occurs when expected epochs are not present in the file, indicating
    data gaps or incomplete observations.

    Parameters
    ----------
    message : str
        Description of which epochs are missing.

    Examples
    --------
    >>> raise MissingEpochError("Epochs 5-10 missing from file")

    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive message."""
        super().__init__(message)


class CorruptedFileError(RinexError):
    """Raised when corrupted RINEX file is detected.

    Indicates that the file structure is malformed or contains invalid
    data that prevents parsing.

    Parameters
    ----------
    message : str
        Description of the corruption.

    Examples
    --------
    >>> raise CorruptedFileError("Invalid header format at line 10")

    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive message."""
        super().__init__(message)


class IncompleteEpochError(RinexError):
    """Raised when an incomplete epoch is detected.

    Occurs when an epoch record is missing expected satellite data or
    has truncated observation records.

    Parameters
    ----------
    message : str
        Description of what data is incomplete.

    Examples
    --------
    >>> raise IncompleteEpochError("Epoch at 2024-01-01 12:00:00 missing G01 data")

    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive message."""
        super().__init__(message)


class InvalidEpochError(RinexError):
    """Raised when an invalid epoch is detected.

    Occurs when epoch timing or format violates RINEX specifications.

    Parameters
    ----------
    message : str
        Description of the validation error.

    Examples
    --------
    >>> raise InvalidEpochError("Epoch flag 9 is invalid (must be 0-6)")

    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive message."""
        super().__init__(message)


class FileNotExistError(RinexError):
    """Raised when a RINEX file does not exist.

    Parameters
    ----------
    message : str
        Description including the file path that was not found.

    Examples
    --------
    >>> raise FileNotExistError("File not found: /path/to/station.24o")

    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive message."""
        super().__init__(message)


class RinexNavError(RinexError, ValueError):
    """Raised when a RINEX navigation file can't be read.

    The message names the file, and the line for a record that can't be
    read. It is also a ``ValueError``, which the navigation reader raised
    before this class existed.

    Examples
    --------
    >>> raise RinexNavError("nav.rnx, line 12: the epoch can't be read")

    """


class NmeaError(Exception):
    """Base exception for NMEA reader errors.

    All NMEA-specific exceptions inherit from this class, allowing
    applications to catch all NMEA reader errors with a single except clause.
    """
