"""Pydantic v2 model for the canVOD file naming convention.

Convention::

    {SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]

    SIT         3-char site ID, uppercase            (e.g. ROS, HAI, FON, LBS)
    T           Receiver type, single uppercase char  (R=reference, A=active/below-canopy)
    NN          Receiver number, zero-padded 01-99
    AGC         3-char data provider ID, uppercase    (e.g. GFZ, TUD, TUW, MPI)
    _R          Literal - 'R' for Receiver
    YYYY        4-digit year
    DOY         3-digit day of year (001-366)
    HHMM        Start time, hours + minutes
    PERIOD      Batch size: 2-digit value + unit      (e.g. 01D, 15M, 01H)
    SAMPLING    Data frequency: 2-digit value + unit  (e.g. 01S, 05S, 05M)
    CONTENT     2-char user field, default 'AA'
    TYPE        File type, lowercase                  (rnx, sbf, ubx, nmea, or
                the type of an installed reader plugin)
    COMPRESSION Optional compression extension        (zip, gz, bz2, zst, ...)

Examples::

    HAIA01GFZ_R_20250010000_01D_01S_AA.rnx.zip
    ROSR01TUW_R_20250010000_01D_05S_AA.rnx
    ROSR35TUW_R_20232221530_15M_05S_AA.sbf
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator
from pydantic.dataclasses import dataclass

# -- Constrained string types ------------------------------------------------

SiteId = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
]

AgencyId = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
]

Duration = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^\d{2}[SMHD]$"),
]

ContentCode = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z0-9]{2}$"),
]

# -- Enums --------------------------------------------------------------------


class ReceiverType(StrEnum):
    """Char 4: receiver role at the site."""

    REFERENCE = "R"
    ACTIVE = "A"


class FileType(StrEnum):
    """Built-in file types; reader plugins can add more (:func:`known_file_types`)."""

    RNX = "rnx"
    SBF = "sbf"
    UBX = "ubx"
    NMEA = "nmea"


_FILE_TYPE_RE = re.compile(r"^[a-z][a-z0-9]{1,7}$")


def known_file_types() -> frozenset[str]:
    """File types a canVOD file name may have.

    The built-in types plus the ``file_type`` of every installed reader
    plugin (entry point group ``canvodpy.readers``).

    Raises
    ------
    canvod.utils.plugins.PluginError
        If a reader plugin cannot be imported or sets no valid
        ``file_type`` (2 to 8 lowercase letters and digits).
    """
    from canvod.utils.plugins import (
        READER_GROUP,
        PluginError,
        load_plugins,
        plugin_package,
    )

    types = {t.value for t in FileType}
    for name, cls in load_plugins(READER_GROUP).items():
        file_type = getattr(cls, "file_type", None)
        if not isinstance(file_type, str) or not _FILE_TYPE_RE.match(file_type):
            raise PluginError(
                f"The reader plugin '{name}' of the package "
                f"{plugin_package(READER_GROUP, name)} sets no valid file_type "
                f"(got {file_type!r}); it must be 2 to 8 lowercase letters and "
                "digits, the TYPE field of its files' canVOD names."
            )
        types.add(file_type)
    return frozenset(types)


# -- Helpers ------------------------------------------------------------------

_DURATION_UNIT_SECONDS = {"S": 1, "M": 60, "H": 3600, "D": 86400}

_FILENAME_RE = re.compile(
    r"^(?P<site>[A-Z]{3})"
    r"(?P<receiver_type>[RA])"
    r"(?P<receiver_number>\d{2})"
    r"(?P<agency>[A-Z]{3})"
    r"_R"
    r"_(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})(?P<minute>\d{2})"
    r"_(?P<period>\d{2}[SMHD])"
    r"_(?P<sampling>\d{2}[SMHD])"
    r"_(?P<content>[A-Z0-9]{2})"
    r"\.(?P<file_type>[a-z][a-z0-9]{1,7})"
    r"(?:\.(?P<compression>[a-z0-9]+))?$"
)


def _duration_to_timedelta(code: str) -> timedelta:
    """Convert a duration code like '05S' or '01D' to a timedelta."""
    value = int(code[:2])
    unit = code[2]
    return timedelta(seconds=value * _DURATION_UNIT_SECONDS[unit])


# -- Model --------------------------------------------------------------------


@dataclass(config=ConfigDict(frozen=True, str_strip_whitespace=True))
class CanVODFilename:
    """Structured representation of a canVOD-compliant filename.

    Construct directly with keyword arguments, or parse from a filename string
    with :meth:`from_filename`.  Render back to a string with :attr:`name`.
    """

    site: SiteId
    receiver_type: ReceiverType
    receiver_number: Annotated[int, Field(ge=1, le=99)]
    agency: AgencyId
    year: Annotated[int, Field(ge=2000, le=2099)]
    doy: Annotated[int, Field(ge=1, le=366)]
    hour: Annotated[int, Field(ge=0, le=23)] = 0
    minute: Annotated[int, Field(ge=0, le=59)] = 0
    period: Duration = "01D"
    sampling: Duration = "05S"
    content: ContentCode = "AA"
    file_type: str = FileType.RNX.value
    compression: str | None = None

    # -- Validators -----------------------------------------------------------

    @field_validator("file_type", mode="before")
    @classmethod
    def _validate_file_type(cls, v: object) -> str:
        value = v.value if isinstance(v, FileType) else v
        known = known_file_types()
        if value not in known:
            raise ValueError(
                f"Unknown file type {value!r}; known: {', '.join(sorted(known))}"
            )
        return str(value)

    @field_validator("compression")
    @classmethod
    def _validate_compression(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.lower().strip()
            if not v:
                return None
        return v

    # -- Computed properties --------------------------------------------------

    @property
    def sampling_interval(self) -> timedelta:
        """Sampling frequency as a timedelta."""
        return _duration_to_timedelta(self.sampling)

    @property
    def batch_duration(self) -> timedelta:
        """Batch / file period as a timedelta."""
        return _duration_to_timedelta(self.period)

    @property
    def start(self) -> datetime:
        """Start of the time span the file covers, from its name."""
        return datetime(self.year, 1, 1) + timedelta(
            days=self.doy - 1, hours=self.hour, minutes=self.minute
        )

    @property
    def end(self) -> datetime:
        """End of the time span the file covers (exclusive), from its name."""
        return self.start + self.batch_duration

    @property
    def name(self) -> str:
        """Full filename including optional compression extension."""
        stem = (
            f"{self.site}{self.receiver_type.value}"
            f"{self.receiver_number:02d}"
            f"{self.agency}"
            f"_R"
            f"_{self.year:04d}{self.doy:03d}{self.hour:02d}{self.minute:02d}"
            f"_{self.period}"
            f"_{self.sampling}"
            f"_{self.content}"
            f".{self.file_type}"
        )
        if self.compression:
            return f"{stem}.{self.compression}"
        return stem

    @property
    def stem(self) -> str:
        """Filename without the compression extension (if any)."""
        parts = self.name.rsplit(".", 1) if self.compression else [self.name]
        return parts[0]

    # -- Constructors ---------------------------------------------------------

    @classmethod
    def from_filename(cls, filename: str) -> Self:
        """Parse a canVOD-compliant filename string into a model instance.

        Accepts a bare filename (no directory components).  Leading path
        segments are stripped automatically.

        Raises
        ------
        ValueError
            If the filename does not match the convention.
        """
        basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

        m = _FILENAME_RE.match(basename)
        if m is None:
            raise ValueError(
                f"Filename does not match the canVOD convention: {basename!r}"
            )

        return cls(
            site=m.group("site"),
            receiver_type=ReceiverType(m.group("receiver_type")),
            receiver_number=int(m.group("receiver_number")),
            agency=m.group("agency"),
            year=int(m.group("year")),
            doy=int(m.group("doy")),
            hour=int(m.group("hour")),
            minute=int(m.group("minute")),
            period=m.group("period"),
            sampling=m.group("sampling"),
            content=m.group("content"),
            file_type=m.group("file_type"),
            compression=m.group("compression"),
        )

    def __str__(self) -> str:
        return self.name


# -- Overlaps -----------------------------------------------------------------


def find_overlaps[T](
    items: Sequence[T],
    key: Callable[[T], CanVODFilename] | None = None,
) -> list[tuple[T, T]]:
    """Find pairs of files whose named time spans overlap.

    Each file covers ``[start, start + period)`` according to its canonical
    name, so a daily file next to sub-daily files of the same day overlaps
    each of them, and adjacent files (00:00-01:00, 01:00-02:00) do not.
    Spans are compared as absolute times, so a file running past midnight
    overlaps files of the next day. Only files of the same receiver identity
    and file type are compared; an SBF file and the RINEX file converted
    from it do not overlap.

    Parameters
    ----------
    items : Sequence
        Files to check.
    key : Callable | None
        Returns the :class:`CanVODFilename` of an item. ``None``: the items
        are :class:`CanVODFilename` instances.

    Returns
    -------
    list[tuple]
        Overlapping pairs, earlier-starting file first, sorted by start.
    """
    groups: dict[tuple[str, str], list[tuple[CanVODFilename, int, T]]] = {}
    for i, item in enumerate(items):
        cn = key(item) if key is not None else item
        assert isinstance(cn, CanVODFilename)
        identity = (
            f"{cn.site}{cn.receiver_type.value}{cn.receiver_number:02d}{cn.agency}"
        )
        groups.setdefault((identity, cn.file_type), []).append((cn, i, item))

    overlaps: list[tuple[datetime, int, int, T, T]] = []
    for group in groups.values():
        group.sort(key=lambda entry: (entry[0].start, entry[0].end, entry[1]))
        active: list[tuple[CanVODFilename, int, T]] = []
        for cn, i, item in group:
            active = [a for a in active if a[0].end > cn.start]
            overlaps.extend((a[0].start, a[1], i, a[2], item) for a in active)
            active.append((cn, i, item))
    overlaps.sort(key=lambda o: o[:3])
    return [(a, b) for _, _, _, a, b in overlaps]
