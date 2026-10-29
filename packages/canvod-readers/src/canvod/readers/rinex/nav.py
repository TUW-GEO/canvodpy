"""RINEX 3.04/3.05 navigation files: the broadcast ephemeris records.

A navigation file holds one record per satellite and reference time: the
orbit parameters the satellite broadcasts. :func:`read_rinex_nav` reads the
records of one or more files into one dataset per system, each with a
``record`` dimension.

Read so far: GPS (RINEX 3.05, Table A6), Galileo (Table A8), GLONASS
(Table A10), QZSS (Table A12) and BeiDou (Table A14). Records of the other
systems are skipped. Times of clock are converted to GPS time, like the
observation epochs; times of ephemeris and weeks stay as written, in the
system's time.

The record layout is fixed-width: a record starts with the satellite
(``A1,I2.2``) and its epoch on the first line, followed by lines of four
``D19.12`` fields after four blanks (RINEX 3.05, Section 6 and Table A6).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import xarray as xr

from canvod.readers.gnss_specs.leap_seconds import gps_minus_utc

#: RINEX versions this reader knows.
SUPPORTED_VERSIONS = ("3.04", "3.05")

#: The fields of a GPS record in file order (RINEX 3.05, Table A6). Angles
#: are radians, times seconds of the GPS week.
GPS_FIELDS: tuple[str | None, ...] = (
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

#: The fields of a Galileo record in file order (RINEX 3.05, Table A8),
#: ``None`` for spares. Times are seconds of the GAL week, which is the
#: continuous GPS week (Table A8, note *****).
GALILEO_FIELDS: tuple[str | None, ...] = (
    "af0",
    "af1",
    "af2",
    "iodnav",
    "crs",
    "delta_n",
    "m0",
    "cuc",
    "e",
    "cus",
    "sqrt_a",
    "toe",
    "cic",
    "omega0",
    "cis",
    "i0",
    "crc",
    "omega",
    "omega_dot",
    "idot",
    "data_sources",  # bit 0 I/NAV E1-B, bit 1 F/NAV E5a-I, bit 2 I/NAV E5b-I
    "week",  # GAL week of toe, continuous, aligned to the GPS week
    None,
    "sisa",  # (m)
    "health",
    "bgd_e5a_e1",  # (s)
    "bgd_e5b_e1",  # (s)
    "transmission_time",  # (s of GAL week)
)

#: The fields of a QZSS record in file order (RINEX 3.05, Table A12): those
#: of GPS, with the fit interval flag (0: 2 hours) in place of the hours.
QZSS_FIELDS: tuple[str | None, ...] = (*GPS_FIELDS[:-1], "fit_interval_flag")

#: The fields of a BeiDou record in file order (RINEX 3.05, Table A14),
#: ``None`` for spares. Times are seconds of the BDT week.
BEIDOU_FIELDS: tuple[str | None, ...] = (
    "af0",
    "af1",
    "af2",
    "aode",
    "crs",
    "delta_n",
    "m0",
    "cuc",
    "e",
    "cus",
    "sqrt_a",
    "toe",  # (s of BDT week)
    "cic",
    "omega0",
    "cis",
    "i0",
    "crc",
    "omega",
    "omega_dot",
    "idot",
    None,
    "week",  # BDT week of toe, continuous; BDT week 0 is GPS week 1356
    None,
    "sv_accuracy",  # (m)
    "sat_h1",
    "tgd1",  # B1/B3 (s)
    "tgd2",  # B2/B3 (s)
    "transmission_time",  # (s of BDT week)
    "aodc",
)

#: The fields of a GLONASS record in file order (RINEX 3.05, Table A10):
#: position, velocity and luni-solar acceleration in the PZ-90 frame, in
#: km, km/s and km/s2. The last four fields are the fifth line RINEX 3.05
#: added; NaN in RINEX 3.04 files.
GLONASS_FIELDS: tuple[str | None, ...] = (
    "minus_tau_n",  # SV clock bias (s), -TauN
    "gamma_n",  # SV relative frequency bias, +GammaN
    "frame_time",  # message frame time tk + nd*86400 (s of the UTC week)
    "x",
    "vx",
    "ax",
    "health",  # 0 healthy, 1 unhealthy (MSB of Bn)
    "y",
    "vy",
    "ay",
    "frequency_number",  # -7...+13
    "z",
    "vz",
    "az",
    "age",  # age of operational information E (days)
    "status_flags",
    "delta_tau_l1_l2",  # L1/L2 group delay difference (s)
    "urai",
    "health_flags",
)

#: Fields of each system read, by system letter.
FIELDS: dict[str, tuple[str | None, ...]] = {
    "G": GPS_FIELDS,
    "E": GALILEO_FIELDS,
    "R": GLONASS_FIELDS,
    "J": QZSS_FIELDS,
    "C": BEIDOU_FIELDS,
}

#: Fields that, with satellite and time of clock, identify a record: a
#: record repeats in every file written while it was current. Galileo sends
#: the same issue of data in I/NAV and F/NAV records.
_RECORD_KEYS: dict[str, tuple[str, ...]] = {
    "G": ("iode",),
    "E": ("iodnav", "data_sources"),
    "R": (),
    "J": ("iode",),
    "C": ("aode",),
}

#: Time of clock minus GPS time, by system (RINEX 3.05, Table 1 and 2:
#: BDT = GPS - 14 s; GAL and QZS equal GPS). GLONASS times of clock are
#: UTC (Table A10), which differs from GPS time by the leap seconds of the
#: date: :func:`_utc_minus_gps`.
_TOC_MINUS_GPS = {"C": np.timedelta64(-14, "s")}

#: Source of each system's records.
_SOURCES = {
    "G": "RINEX 3.05, Table A6",
    "E": "RINEX 3.05, Table A8",
    "R": "RINEX 3.05, Table A10",
    "J": "RINEX 3.05, Table A12",
    "C": "RINEX 3.05, Table A14",
}

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


def _utc_minus_gps(toc: np.ndarray) -> np.ndarray:
    """UTC minus GPS time at UTC times: minus the leap seconds of each."""
    times = np.unique(toc)
    leap = [gps_minus_utc(t.astype("datetime64[us]").item()) for t in times]
    return -np.array(leap, dtype="timedelta64[s]")[np.searchsorted(times, toc)]


def _system_records(
    system: str, svs: list[str], epochs: list[str], texts: list[list[str]]
) -> xr.Dataset:
    """The records of one system as a dataset along ``record``."""
    fields = FIELDS[system]
    values = np.char.replace(np.array(texts, dtype=str), "D", "E")
    values = np.where(np.char.strip(values) == "", "nan", values).astype(np.float64)
    toc = np.array(epochs, dtype="datetime64[ns]")
    if system == "R":
        toc = toc - _utc_minus_gps(toc)
    else:
        toc = toc - _TOC_MINUS_GPS.get(system, np.timedelta64(0, "s"))
    sv = np.array(svs, dtype=str)

    keys = [sv, toc] + [
        np.nan_to_num(values[:, fields.index(name)], nan=-1.0)
        for name in _RECORD_KEYS[system]
    ]
    _, first = np.unique(np.rec.fromarrays(keys), return_index=True)
    order = first[np.lexsort((toc[first], sv[first]))]

    ds = xr.Dataset(
        {
            name: ("record", values[order, i])
            for i, name in enumerate(fields)
            if name is not None
        },
        coords={"sv": ("record", sv[order]), "toc": ("record", toc[order])},
    )
    ds["toc"].attrs["time_system"] = "GPS"
    ds.attrs["source"] = f"RINEX navigation files ({_SOURCES[system]})"
    return ds


def read_rinex_nav(paths: Iterable[Path]) -> dict[str, xr.Dataset]:
    """Read the broadcast ephemeris records of RINEX navigation files.

    Parameters
    ----------
    paths : Iterable[Path]
        RINEX 3.04/3.05 navigation files, for example the files of one
        receiver-day. A record in several files is kept once.

    Returns
    -------
    dict[str, xr.Dataset]
        One dataset per system letter found (``"G"``, ``"E"``, ``"J"``,
        ``"C"``), with one entry per record along ``record``, sorted by
        satellite and time of clock: coordinates ``sv`` (e.g. ``"G01"``)
        and ``toc`` (time of clock, GPS time), and one variable per field
        of the system's table in :data:`FIELDS`.

    Raises
    ------
    ValueError
        If no files are given, a file is not a RINEX 3.04/3.05 navigation
        file, or the files hold no record of a system read.
    """
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("no navigation files given")
    found: dict[str, tuple[list[str], list[str], list[list[str]]]] = {}
    for path in paths:
        lines = path.read_text().splitlines()
        for record in _records(lines, _header(lines, path)):
            system = record[0][0]
            fields = FIELDS.get(system)
            if fields is None:
                continue
            # QZSS writes the number as I2, the others as I2.2 (Table A12)
            sv = f"{system}{int(record[0][1:3]):02d}"
            year, month, day, hour, minute, second = map(int, record[0][4:23].split())
            svs, epochs, texts = found.setdefault(system, ([], [], []))
            svs.append(sv)
            epochs.append(
                f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
            )
            texts.append((_fields(record) + [""] * len(fields))[: len(fields)])
    if not found:
        raise ValueError(
            f"{', '.join(str(path) for path in paths)} hold no record of "
            f"{', '.join(sorted(FIELDS))}; navigation records of the other "
            "systems are not read yet"
        )
    return {
        system: _system_records(system, *columns)
        for system, columns in sorted(found.items())
    }
