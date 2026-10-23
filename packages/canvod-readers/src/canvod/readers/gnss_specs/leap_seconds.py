"""GPS - UTC: the leap seconds between UTC and GPS time.

GPS time started at 1980-01-06 00:00:00 UTC and has no leap seconds; UTC
has had one inserted at the end of each date below (IERS Bulletin C). Every
stored epoch is GPS time, so readers of UTC times (NMEA) add GPS - UTC of
the date.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

GPS_EPOCH_UTC: Final = datetime(1980, 1, 6, tzinfo=UTC)

# (first UTC day with this offset, GPS - UTC in seconds)
LEAP_SECONDS: Final[tuple[tuple[datetime, int], ...]] = tuple(
    (datetime(y, m, 1, tzinfo=UTC), n)
    for (y, m), n in (
        ((1981, 7), 1),
        ((1982, 7), 2),
        ((1983, 7), 3),
        ((1985, 7), 4),
        ((1988, 1), 5),
        ((1990, 1), 6),
        ((1991, 1), 7),
        ((1992, 7), 8),
        ((1993, 7), 9),
        ((1994, 7), 10),
        ((1996, 1), 11),
        ((1997, 7), 12),
        ((1999, 1), 13),
        ((2006, 1), 14),
        ((2009, 1), 15),
        ((2012, 7), 16),
        ((2015, 7), 17),
        ((2017, 1), 18),
    )
)

# IERS Bulletin C 71 (January 2026): no leap second at the end of June 2026.
# The next possible one is at the end of December 2026, so the table is
# known to hold up to here. Extend it (and this date) with each Bulletin C.
LEAP_SECONDS_KNOWN_UNTIL: Final = datetime(2027, 1, 1, tzinfo=UTC)


def gps_minus_utc(utc: datetime) -> int:
    """GPS - UTC in seconds at the UTC time ``utc``.

    Parameters
    ----------
    utc : datetime
        A UTC time; a naive datetime is taken as UTC.

    Raises
    ------
    ValueError
        If ``utc`` is before GPS time started or after the leap seconds
        known to canVODpy (``LEAP_SECONDS_KNOWN_UNTIL``).

    """
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=UTC)
    if utc < GPS_EPOCH_UTC:
        msg = f"{utc.isoformat()} is before GPS time started (1980-01-06)."
        raise ValueError(msg)
    if utc >= LEAP_SECONDS_KNOWN_UNTIL:
        msg = (
            f"{utc.isoformat()} is after {LEAP_SECONDS_KNOWN_UNTIL.date()}, up to "
            "which canVODpy knows the leap seconds (GPS - UTC), so it cannot "
            "convert this UTC time to GPS time. Update canVODpy; the table is "
            "canvod.readers.gnss_specs.leap_seconds, from IERS Bulletin C."
        )
        raise ValueError(msg)
    offset = 0
    for start, n in LEAP_SECONDS:
        if utc < start:
            break
        offset = n
    return offset


def utc_to_gps(utc: datetime) -> datetime:
    """The GPS time of the UTC time ``utc`` (same ``tzinfo`` as given)."""
    return utc + timedelta(seconds=gps_minus_utc(utc))
