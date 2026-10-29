"""Satellite orbits from the broadcast ephemeris of RINEX navigation files.

The records of the navigation files (:func:`canvod.readers.rinex.nav.read_rinex_nav`)
give ECEF positions and velocities on a regular grid over the day, the same
layout as an SP3 product (ADR 0023). The grid then goes through the Hermite
interpolation of the precise ephemeris
(:func:`canvod.auxiliary.interpolation.interpolate_aux_day`).

For each grid time and satellite, the record whose time of ephemeris is
nearest is used where it is valid; elsewhere the satellite has no position
(NaN). Velocities are central differences of the positions over 1 s.

Systems so far: GPS (IS-GPS-200N, Table 20-IV).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import xarray as xr

#: Spacing of the orbit grid, seconds.
GRID_STEP_S = 300.0

#: Earth's gravitational constant for GPS users, m^3/s^2, and Earth's
#: rotation rate, rad/s (IS-GPS-200N, Table 20-IV, WGS 84 values).
GPS_MU = 3.986005e14
GPS_OMEGA_E_DOT = 7.2921151467e-5

#: Fit interval of a GPS record whose fit interval field is below 4 or
#: blank, hours: fit interval flag 0 (IS-GPS-200N, 20.3.3.4.3.1).
GPS_DEFAULT_FIT_INTERVAL_H = 4.0

_SECONDS_PER_WEEK = 604_800
_GPS_EPOCH = np.datetime64("1980-01-06T00:00:00", "ns")
_KEPLER_ITERATIONS = 10  # IS-GPS-200N, Table 20-IV: at least three
_VELOCITY_HALF_STEP_S = 0.5


def _gps_seconds(t: np.ndarray) -> np.ndarray:
    """Seconds since the GPS epoch of GPS-time ``datetime64`` values."""
    return (np.asarray(t, "datetime64[ns]") - _GPS_EPOCH) / np.timedelta64(1, "s")


def gps_positions(records: xr.Dataset, t: np.ndarray) -> np.ndarray:
    """ECEF positions of GPS records at GPS times, IS-GPS-200N Table 20-IV.

    Parameters
    ----------
    records : xr.Dataset
        GPS records along ``record`` (fields of
        :data:`canvod.readers.rinex.nav.GPS_FIELDS`), one per value of ``t``.
    t : np.ndarray
        Seconds since the GPS epoch (1980-01-06), one per record.

    Returns
    -------
    np.ndarray
        ``(len(t), 3)`` ECEF X, Y, Z in meters.
    """

    def field(name: str) -> np.ndarray:
        return records[name].values

    toe = field("week") * _SECONDS_PER_WEEK + field("toe")
    tk = t - toe  # whole GPS seconds: no week crossover to correct
    a = field("sqrt_a") ** 2
    n = np.sqrt(GPS_MU / a**3) + field("delta_n")
    mk = field("m0") + n * tk
    e = field("e")
    ek = mk.copy()
    for _ in range(_KEPLER_ITERATIONS):
        ek = ek + (mk - ek + e * np.sin(ek)) / (1 - e * np.cos(ek))
    nu = np.arctan2(np.sqrt(1 - e**2) * np.sin(ek), np.cos(ek) - e)
    phi = nu + field("omega")
    s2, c2 = np.sin(2 * phi), np.cos(2 * phi)
    u = phi + field("cus") * s2 + field("cuc") * c2
    r = a * (1 - e * np.cos(ek)) + field("crs") * s2 + field("crc") * c2
    i = field("i0") + field("idot") * tk + field("cis") * s2 + field("cic") * c2
    x_orb, y_orb = r * np.cos(u), r * np.sin(u)
    om = (
        field("omega0")
        + (field("omega_dot") - GPS_OMEGA_E_DOT) * tk
        - GPS_OMEGA_E_DOT * field("toe")
    )
    return np.stack(
        [
            x_orb * np.cos(om) - y_orb * np.cos(i) * np.sin(om),
            x_orb * np.sin(om) + y_orb * np.cos(i) * np.cos(om),
            y_orb * np.sin(i),
        ],
        axis=-1,
    )


def _valid_record(records: xr.Dataset, t: np.ndarray) -> np.ndarray:
    """Index of the record to use at each of ``t``, -1 where none is valid.

    The record with the nearest time of ephemeris, if ``t`` lies within half
    its fit interval of it (RINEX 3.05, Table A6: fit interval in hours).
    GPS fit intervals are 4 hours or longer (IS-GPS-200N, 20.3.3.4.3.1);
    a smaller value, as some converters write the fit interval flag (0 or
    1) instead of the hours, counts as 4 hours.
    """
    toe = records["week"].values * _SECONDS_PER_WEEK + records["toe"].values
    fit_h = records["fit_interval"].values
    fit_h = np.where(
        np.isfinite(fit_h) & (fit_h >= GPS_DEFAULT_FIT_INTERVAL_H),
        fit_h,
        GPS_DEFAULT_FIT_INTERVAL_H,
    )
    nearest = np.abs(t[:, None] - toe[None, :]).argmin(axis=1)
    valid = np.abs(t - toe[nearest]) <= fit_h[nearest] * 3600 / 2
    return np.where(valid, nearest, -1)


def broadcast_orbits(
    records: xr.Dataset, day_start: np.datetime64, step_s: float = GRID_STEP_S
) -> xr.Dataset:
    """Positions and velocities of every satellite on a grid over one day.

    Parameters
    ----------
    records : xr.Dataset
        Navigation records, from :func:`canvod.readers.rinex.nav.read_rinex_nav`.
    day_start : np.datetime64
        00:00 of the day, GPS time.
    step_s : float
        Grid spacing in seconds; the grid runs from 00:00 to 24:00.

    Returns
    -------
    xr.Dataset
        ``X``, ``Y``, ``Z`` (m) and ``Vx``, ``Vy``, ``Vz`` (m/s) on
        ``(epoch, sv)``, like an SP3 product with velocities; NaN where a
        satellite has no valid record.
    """
    start = np.asarray(day_start).astype("datetime64[D]").astype("datetime64[ns]")
    n_epochs = int(round(86_400 / step_s)) + 1
    epochs = start + (np.arange(n_epochs) * step_s * 1e9).astype("timedelta64[ns]")
    t = _gps_seconds(epochs)

    svs = sorted({str(sv) for sv in records.sv.values if str(sv).startswith("G")})
    pos = np.full((n_epochs, len(svs), 3), np.nan)
    vel = np.full_like(pos, np.nan)
    for j, sv in enumerate(svs):
        recs = records.isel(record=np.flatnonzero(records.sv.values == sv))
        index = _valid_record(recs, t)
        ok = index >= 0
        chosen = recs.isel(record=index[ok])
        tt = t[ok]
        pos[ok, j] = gps_positions(chosen, tt)
        vel[ok, j] = (
            gps_positions(chosen, tt + _VELOCITY_HALF_STEP_S)
            - gps_positions(chosen, tt - _VELOCITY_HALF_STEP_S)
        ) / (2 * _VELOCITY_HALF_STEP_S)

    dims = ("epoch", "sv")
    ds = xr.Dataset(
        {name: (dims, pos[..., k]) for k, name in enumerate("XYZ")}
        | {name: (dims, vel[..., k]) for k, name in enumerate(("Vx", "Vy", "Vz"))},
        coords={"epoch": epochs, "sv": np.array(svs, dtype=str)},
    )
    for name in "XYZ":
        ds[name].attrs = {
            "long_name": f"{name.lower()}-coordinate in ECEF",
            "units": "m",
        }
    for name in ("Vx", "Vy", "Vz"):
        ds[name].attrs = {"long_name": f"{name} in ECEF", "units": "m/s"}
    ds.attrs["source"] = "broadcast ephemeris, RINEX navigation files"
    return ds


def broadcast_ephemerides(
    nav_files: Iterable[Path],
    day_start: np.datetime64,
    keep_sids: list[str] | None = None,
    aggregate_glonass_fdma: bool = True,
) -> xr.Dataset:
    """Orbit grid of one day from navigation files, mapped to SIDs.

    The broadcast counterpart of the ``ephemerides`` of
    :class:`canvod.auxiliary.pipeline.AuxDataPipeline`: ready for
    :func:`canvod.auxiliary.interpolation.interpolate_aux_day`.

    Parameters
    ----------
    nav_files : Iterable[Path]
        RINEX 3.04/3.05 navigation files of the day.
    day_start : np.datetime64
        00:00 of the day, GPS time.
    keep_sids : list[str] | None
        SIDs to keep, ``None`` for all.
    aggregate_glonass_fdma : bool
        As for the observations.

    Returns
    -------
    xr.Dataset
        ``X``, ``Y``, ``Z``, ``Vx``, ``Vy``, ``Vz`` on ``(epoch, sid)``.
    """
    from canvod.readers.rinex.nav import read_rinex_nav

    from canvod.auxiliary.preprocessing import prep_aux_ds

    orbits = broadcast_orbits(read_rinex_nav(nav_files), day_start)
    return prep_aux_ds(
        orbits, keep_sids=keep_sids, aggregate_glonass_fdma=aggregate_glonass_fdma
    )
