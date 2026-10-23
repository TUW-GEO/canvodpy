"""Source filename pattern definitions and built-in registry.

Each ``SourcePattern`` describes how to discover and parse a particular
naming scheme (RINEX v2, RINEX v3, Septentrio SBF, etc.) so the mapping
engine can extract date/time metadata from any filename.

.. deprecated::
    Left over from development and removed with the next major version,
    together with ``FilenameMapper``. Naming recipes (``canvod-filemap``)
    describe non-canonical filenames instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from canvod.utils.tools import deprecated


@dataclass(frozen=True)
class SourcePattern:
    """A named regex pattern for matching and parsing source filenames.

    Parameters
    ----------
    name
        Human-readable pattern identifier (e.g. ``"rinex_v3_long"``).
    file_globs
        Glob patterns used to discover matching files on disk.
    regex
        Compiled regex with named groups for metadata extraction.
        Expected groups: ``year`` (or ``yy``), ``doy``,
        ``hour`` (optional), ``minute`` (optional),
        ``sampling`` (optional), ``period`` (optional).
    """

    name: str
    file_globs: tuple[str, ...]
    regex: re.Pattern[str]


def _build_canvod_pattern() -> SourcePattern:
    """Already canVOD-compliant filenames."""
    return SourcePattern(
        name="canvod",
        file_globs=(
            "*_R_*_*_*_*.rnx*",
            "*_R_*_*_*_*.sbf*",
            "*_R_*_*_*_*.ubx*",
            "*_R_*_*_*_*.nmea*",
        ),
        regex=re.compile(
            r"^[A-Z]{3}[RA]\d{2}[A-Z]{3}"
            r"_R"
            r"_(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})(?P<minute>\d{2})"
            r"_(?P<period>\d{2}[SMHD])"
            r"_(?P<sampling>\d{2}[SMHD])"
            r"_[A-Z0-9]{2}"
            r"\.(?P<ext>rnx|sbf|ubx|nmea)"
            r"(?:\.[a-z0-9]+)?$"
        ),
    )


def _build_rinex_v3_long_pattern() -> SourcePattern:
    """RINEX v3.04 long-name convention.

    Example: ``ROSA00TUW_R_20250010000_01D_05S_MO.rnx``
    Format:  ``{SITE}{M}{CC}{CTRY}_R_{YYYY}{DOY}{HHMM}_{PER}_{SAMP}_{CONTENT}.rnx[.gz]``
    """
    return SourcePattern(
        name="rinex_v3_long",
        file_globs=("*_R_*_*_*_*.rnx*", "*_R_*_*_*_*.crx*"),
        regex=re.compile(
            r"^(?P<station>[A-Z0-9]{4})\d{2}[A-Z]{3}"
            r"_R"
            r"_(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})(?P<minute>\d{2})"
            r"_(?P<period>\d{2}[SMHD])"
            r"_(?P<sampling>\d{2}[SMHD])"
            r"_[A-Z0-9]{2}"
            r"\.(?P<ext>rnx|crx)"
            r"(?:\.[a-z0-9]+)?$"
        ),
    )


def _build_rinex_v2_short_pattern() -> SourcePattern:
    """RINEX v2 short-name convention (observation files only).

    Example: ``rosl001a.25o``
    Format:  ``{ssss}{ddd}{h}.{yy}{t}``
    where ssss=4-char station, ddd=DOY, h=hour letter (a-x or 0),
    yy=2-digit year, t=file type (o/O=obs, d/D=Hatanaka compressed obs)
    """
    return SourcePattern(
        name="rinex_v2_short",
        file_globs=(
            "*.[0-9][0-9][oOdD]",
            "*.[0-9][0-9][oOdD].gz",
            "*.[0-9][0-9][oOdD].zip",
            "*.[0-9][0-9][oOdD].Z",
        ),
        regex=re.compile(
            r"^(?P<station>[a-zA-Z0-9]{4})"
            r"(?P<doy>\d{3})"
            r"(?P<hour_letter>[a-x0])"
            r"\.(?P<yy>\d{2})"
            r"(?P<type_char>[oOdD])"
            r"(?:\.[a-zA-Z0-9]+)?$"
        ),
    )


def _build_septentrio_rinex_v2_pattern() -> SourcePattern:
    """Septentrio RINEX v2 with minute field (observation files only).

    Example: ``ract001a15.25o``
    Format:  ``{ssss}{ddd}{h}{mm}.{yy}{t}``
    where ssss=4-char station, ddd=DOY, h=hour letter (a-x),
    mm=minute, yy=2-digit year, t=file type (o/O/d/D)

    Septentrio receivers add a 2-digit minute to the standard RINEX v2
    short name when logging sub-hourly files.
    """
    return SourcePattern(
        name="septentrio_rinex_v2",
        file_globs=(
            "*.[0-9][0-9][oOdD]",
            "*.[0-9][0-9][oOdD].gz",
            "*.[0-9][0-9][oOdD].zip",
            "*.[0-9][0-9][oOdD].Z",
        ),
        regex=re.compile(
            r"^(?P<station>[a-zA-Z0-9]{4})"
            r"(?P<doy>\d{3})"
            r"(?P<hour_letter>[a-x])"
            r"(?P<minute>\d{2})"
            r"\.(?P<yy>\d{2})"
            r"(?P<type_char>[oOdD])"
            r"(?:\.[a-zA-Z0-9]+)?$"
        ),
    )


def _build_septentrio_sbf_pattern() -> SourcePattern:
    """Septentrio SBF binary file convention.

    Example: ``rref001a00.25_``
    Format:  ``{ssss}{ddd}{h}{mm}.{yy}_``
    where ssss=4-char station, ddd=DOY, h=hour letter,
    mm=minute (00 for daily), yy=2-digit year, _=SBF marker
    """
    return SourcePattern(
        name="septentrio_sbf",
        file_globs=("*.[0-9][0-9]_", "*.[0-9][0-9]_.*"),
        regex=re.compile(
            r"^(?P<station>[a-zA-Z0-9]{4})"
            r"(?P<doy>\d{3})"
            r"(?P<hour_letter>[a-x0])"
            r"(?P<minute>\d{2})"
            r"\.(?P<yy>\d{2})_"
            r"(?:\.[a-zA-Z0-9]+)?$"
        ),
    )


# -- Built-in registry -------------------------------------------------------

BUILTIN_PATTERNS: dict[str, SourcePattern] = {
    "canvod": _build_canvod_pattern(),
    "rinex_v3_long": _build_rinex_v3_long_pattern(),
    "septentrio_rinex_v2": _build_septentrio_rinex_v2_pattern(),
    "rinex_v2_short": _build_rinex_v2_short_pattern(),
    "septentrio_sbf": _build_septentrio_sbf_pattern(),
}

# Order for "auto" mode: most specific first.
# septentrio_rinex_v2 must come before rinex_v2_short because both share
# the same globs but the Septentrio variant has a minute field (10 chars
# before the dot vs 8).
AUTO_PATTERN_ORDER: tuple[str, ...] = (
    "canvod",
    "rinex_v3_long",
    "septentrio_sbf",
    "septentrio_rinex_v2",
    "rinex_v2_short",
)


# -- Hour letter helpers ------------------------------------------------------

_HOUR_LETTER_MAP: dict[str, int] = {chr(ord("a") + h): h for h in range(24)}
_HOUR_LETTER_MAP["0"] = 0  # '0' also means hour 0


def hour_letter_to_int(letter: str) -> int:
    """Convert a RINEX hour letter (a-x or '0') to an integer 0-23.

    Raises
    ------
    ValueError
        If the letter is not a valid RINEX hour code.
    """
    try:
        return _HOUR_LETTER_MAP[letter.lower()]
    except KeyError:
        raise ValueError(f"Invalid hour letter: {letter!r}") from None


def resolve_year_from_yy(yy: int) -> int:
    """Expand a 2-digit year to 4 digits (80-99 → 1980-1999, 00-79 → 2000-2079)."""
    if yy >= 80:
        return 1900 + yy
    return 2000 + yy


def auto_match_order() -> tuple[str, ...]:
    """Return the pattern names in auto-detection order."""
    return AUTO_PATTERN_ORDER


@deprecated(
    "match_pattern is left over from development and will be removed with the next major version. "
    "Use a naming recipe (the receiver setting 'recipe', see canvod-filemap) instead; canvodpy run finds the files in any folder layout."
)
def match_pattern(
    filename: str, pattern_name: str = "auto"
) -> tuple[SourcePattern, re.Match[str]] | None:
    """Try to match a filename against a named pattern or all patterns.

    Parameters
    ----------
    filename
        Bare filename (no directory components).
    pattern_name
        A built-in pattern name, or ``"auto"`` to try all in order.

    Returns
    -------
    tuple[SourcePattern, re.Match] or None
        The matching pattern and regex match, or None if no pattern matched.
    """
    if pattern_name == "auto":
        names = AUTO_PATTERN_ORDER
    else:
        if pattern_name not in BUILTIN_PATTERNS:
            raise ValueError(
                f"Unknown pattern {pattern_name!r}. Available: {list(BUILTIN_PATTERNS)}"
            )
        names = (pattern_name,)

    for name in names:
        pat = BUILTIN_PATTERNS[name]
        m = pat.regex.match(filename)
        if m is not None:
            return (pat, m)

    return None
