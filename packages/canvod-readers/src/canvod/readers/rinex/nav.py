"""RINEX 3.04/3.05 navigation files: the broadcast ephemeris records.

A navigation file holds one record per satellite and reference time: the
orbit parameters the satellite broadcasts. :func:`read_rinex_nav` reads the
records of one or more files into one dataset with a ``record`` dimension.

Read so far: GPS (RINEX 3.05, Table A6). Records of the other systems are
skipped. Times are GPS time, like the observation epochs.

The record layout is fixed-width: a record starts with the satellite
(``A1,I2.2``) and its epoch on the first line, followed by lines of four
``D19.12`` fields after four blanks (RINEX 3.05, Section 6 and Table A6).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import xarray as xr

#: RINEX versions this reader knows.
SUPPORTED_VERSIONS = ("3.04", "3.05")

#: The fields of a GPS record in file order (RINEX 3.05, Table A6), ``None``
#: for spares. Angles are radians, times seconds of the GPS week.
GPS_FIELDS = (
    "af0",  # SV clock bias (s)
    "af1",  # SV clock drift (s/s)
    "af2",  # SV clock drift rate (s/s2)
    "iode",
    "crs",  # (m)
    "delta_n",  # (rad/s)
    "m0",  # (rad)
    "cuc",  # (rad)
    "e",
    "cus",  # (rad)
    "sqrt_a",  # (sqrt(m))
    "toe",  # time of ephemeris (s of GPS week)
    "cic",  # (rad)
    "omega0",  # (rad)
    "cis",  # (rad)
    "i0",  # (rad)
    "crc",  # (m)
    "omega",  # (rad)
    "omega_dot",  # (rad/s)
    "idot",  # (rad/s)
    "l2_codes",
    "week",  # GPS week of toe, continuous (not mod 1024)
    "l2p_flag",
    "sv_accuracy",  # (m)
    "health",
    "tgd",  # (s)
    "iodc",
    "transmission_time",  # (s of GPS week)
    "fit_interval",  # (hours)
)

_FIELD_WIDTH = 19


def _header(lines: list[str], path: Path) -> int:
    """Check the header of a navigation file; index of its first record line."""
    first = lines[0] if lines else ""
    version = first[:9].strip()
    if "RINEX VERSION / TYPE" not in first or first[20:21] != "N":
        raise ValueError(f"{path} is not a RINEX navigation file")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"{path} is RINEX {version}; navigation files are read in RINEX "
            f"{' and '.join(SUPPORTED_VERSIONS)}"
        )
    for i, line in enumerate(lines):
        if "END OF HEADER" in line[60:]:
            return i + 1
    raise ValueError(f"{path} has no END OF HEADER line")


def _records(lines: list[str], start: int) -> Iterable[list[str]]:
    """The lines of each record: a record line starts with its satellite."""
    record: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            continue
        if line[0] != " " and record:
            yield record
            record = []
        record.append(line)
    if record:
        yield record


def _fields(record: list[str]) -> list[str]:
    """The numeric fields of a record, as text: 3 on the first line, 4 after."""
    first = record[0]
    fields = [
        first[23 + _FIELD_WIDTH * k : 23 + _FIELD_WIDTH * (k + 1)] for k in range(3)
    ]
    for line in record[1:]:
        fields += [
            line[4 + _FIELD_WIDTH * k : 4 + _FIELD_WIDTH * (k + 1)] for k in range(4)
        ]
    return fields


def read_rinex_nav(paths: Iterable[Path]) -> xr.Dataset:
    """Read the broadcast ephemeris records of RINEX navigation files.

    Parameters
    ----------
    paths : Iterable[Path]
        RINEX 3.04/3.05 navigation files, for example the files of one
        receiver-day. A record in several files is kept once.

    Returns
    -------
    xr.Dataset
        One entry per record along ``record``, sorted by satellite and time
        of clock: coordinates ``sv`` (e.g. ``"G01"``) and ``toc`` (time of
        clock, GPS time), and one variable per field of :data:`GPS_FIELDS`.

    Raises
    ------
    ValueError
        If a file is not a RINEX 3.04/3.05 navigation file, or the files
        hold no GPS record.
    """
    paths = [Path(path) for path in paths]
    svs: list[str] = []
    epochs: list[str] = []
    texts: list[list[str]] = []
    for path in paths:
        lines = path.read_text().splitlines()
        for record in _records(lines, _header(lines, path)):
            sv = record[0][:3]
            if sv[0] != "G":
                continue
            year, month, day, hour, minute, second = record[0][4:23].split()
            svs.append(sv)
            epochs.append(f"{year}-{month}-{day}T{hour}:{minute}:{second}")
            fields = _fields(record)
            texts.append((fields + [""] * len(GPS_FIELDS))[: len(GPS_FIELDS)])
    if not texts:
        raise ValueError(
            f"{', '.join(str(path) for path in paths)} hold no GPS record; "
            "navigation records of the other systems are not read yet"
        )

    values = np.char.replace(
        np.array(texts, dtype=str).reshape(-1, len(GPS_FIELDS)), "D", "E"
    )
    values = np.where(np.char.strip(values) == "", "nan", values).astype(np.float64)
    toc = np.array(epochs, dtype="datetime64[ns]")
    sv = np.array(svs, dtype=str)

    # A record repeats in every file written while it was current.
    iode = values[:, GPS_FIELDS.index("iode")]
    keys = np.rec.fromarrays([sv, toc, np.nan_to_num(iode, nan=-1.0)])
    _, first = np.unique(keys, return_index=True)
    order = first[np.lexsort((toc[first], sv[first]))]

    ds = xr.Dataset(
        {name: ("record", values[order, i]) for i, name in enumerate(GPS_FIELDS)},
        coords={"sv": ("record", sv[order]), "toc": ("record", toc[order])},
    )
    ds["toc"].attrs["time_system"] = "GPS"
    ds.attrs["source"] = "RINEX navigation files (RINEX 3.05, Table A6)"
    return ds
