"""Satellite orbits from the broadcast ephemeris of RINEX navigation files.

The records of the navigation files (:func:`canvod.readers.rinex.nav.read_rinex_nav`)
give ECEF positions and velocities on a regular grid over the day, the same
layout as an SP3 product (ADR 0023). The grid then goes through the Hermite
interpolation of the precise ephemeris
(:func:`canvod.auxiliary.interpolation.interpolate_aux_day`).

For each grid time and satellite, the record whose time of ephemeris is
nearest is used where it is valid; elsewhere the satellite has no position
(NaN).

Systems so far: from Keplerian elements GPS (IS-GPS-200N, Table 20-IV),
Galileo (Galileo OS SIS ICD, Issue 2.1, Table 66), QZSS (IS-QZSS-PNT-005,
Section 5.6.1) and BeiDou (BDS-SIS-ICD-B1I-3.0, Table 5-11), with
velocities from central differences of the positions over 1 s; GLONASS by
numerical integration (ICD GLONASS, Edition 5.1, A.3.1.2,
:mod:`canvod.auxiliary.ephemeris.glonass`), with the integrated velocities;
SBAS from the position, velocity and acceleration of each record
(:func:`sbas_states`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr

from canvod.auxiliary.ephemeris.glonass import GLONASS_VALIDITY_S, glonass_states

#: Spacing of the orbit grid, seconds.
GRID_STEP_S = 300.0


@dataclass(frozen=True)
class KeplerSystem:
    """What the orbit of a system's Keplerian records depends on.

    Attributes
    ----------
    mu : float
        Earth's gravitational constant of the system, m^3/s^2.
    omega_e_dot : float
        Earth's rotation rate of the system, rad/s.
    fit_interval_h : float
        Fit interval, hours: a record is used within half of it on either
        side of its time of ephemeris, unless the record gives a longer
        fit interval (GPS).
    week_offset : int
        GPS week of the system's week 0.
    time_offset_s : float
        GPS time minus the system's time, seconds.
    """

    mu: float
    omega_e_dot: float
    fit_interval_h: float
    week_offset: int = 0
    time_offset_s: float = 0.0


#: The Keplerian systems read from navigation files.
#:
#: - GPS: IS-GPS-200N, Table 20-IV (WGS 84 values); fit interval flag 0
#:   means 4 hours (20.3.3.4.3.1); a record's fit interval may be longer.
#: - Galileo: OS SIS ICD, Issue 2.1, Table 66. The ICD gives no fit
#:   interval (5.1.9.2: "limited validity duration"); canvodpy uses
#:   records within 2 hours of their time of ephemeris, as for GPS. GST
#:   equals GPS time (RINEX 3.05, Table 1).
#: - QZSS: IS-QZSS-PNT-005, Section 5.6.1 (the GPS values); fit interval
#:   2 hours (Table 4.1.1-2).
#: - BeiDou: BDS-SIS-ICD-B1I-3.0, Table 5-11 (CGCS2000 values). The ICD
#:   gives no fit interval (ephemerides are updated every hour, 5.2.4.11);
#:   canvodpy uses records within 2 hours, as for GPS. BDT = GPS - 14 s
#:   (RINEX 3.05, Table 1 and 2); BDT week 0 is GPS week 1356 (Table 3).
KEPLER_SYSTEMS: dict[str, KeplerSystem] = {
    "G": KeplerSystem(mu=3.986005e14, omega_e_dot=7.2921151467e-5, fit_interval_h=4.0),
    "E": KeplerSystem(
        mu=3.986004418e14, omega_e_dot=7.2921151467e-5, fit_interval_h=4.0
    ),
    "J": KeplerSystem(mu=3.986005e14, omega_e_dot=7.2921151467e-5, fit_interval_h=2.0),
    "C": KeplerSystem(
        mu=3.986004418e14,
        omega_e_dot=7.2921150e-5,
        fit_interval_h=4.0,
        week_offset=1356,
        time_offset_s=14.0,
    ),
}

#: Systems whose navigation records give orbits here, by system letter.
ORBIT_SYSTEMS: tuple[str, ...] = (*KEPLER_SYSTEMS, "R", "S")

#: An SBAS record is used within this many seconds of its time of clock:
#: the time-out of the GEO navigation message (MT9) for en route, terminal
#: and non-precision approach (RTCA DO-229D, Table 2-1 and Table A-25).
#: DO-229D counts the time-out forward from the end of reception
#: (Section A.4.7); RINEX keeps no reception time, so the window here is
#: centered on the time of clock.
SBAS_VALIDITY_S = 360.0

#: BeiDou GEO satellites (BDS-SIS-ICD-B1I-3.0, Table 4-1: SV IDs 1-5 and
#: 59-63). Their orbits take the extra rotations of Table 5-11.
BEIDOU_GEO = frozenset(f"C{n:02d}" for n in (1, 2, 3, 4, 5, 59, 60, 61, 62, 63))

#: Inclination of the GEO reference frame, BDS-SIS-ICD-B1I-3.0, Table 5-11.
_BEIDOU_GEO_TILT = np.deg2rad(-5.0)

_SECONDS_PER_WEEK = 604_800
_GPS_EPOCH = np.datetime64("1980-01-06T00:00:00", "ns")
_KEPLER_ITERATIONS = 10  # IS-GPS-200N, Table 20-IV: at least three
_VELOCITY_HALF_STEP_S = 0.5


def _gps_seconds(t: np.ndarray) -> np.ndarray:
    """Seconds since the GPS epoch of GPS-time ``datetime64`` values."""
    return (np.asarray(t, "datetime64[ns]") - _GPS_EPOCH) / np.timedelta64(1, "s")


def _toe_gps_seconds(records: xr.Dataset, system: KeplerSystem) -> np.ndarray:
    """Times of ephemeris of records in seconds since the GPS epoch."""
    week = records["week"].values + system.week_offset
    return week * _SECONDS_PER_WEEK + records["toe"].values + system.time_offset_s


def kepler_positions(records: xr.Dataset, t: np.ndarray, sv: str) -> np.ndarray:
    """ECEF positions of one satellite's Keplerian records at GPS times.

    The user algorithm of IS-GPS-200N, Table 20-IV, which the Galileo, QZSS
    and BeiDou ICDs share, with the constants of :data:`KEPLER_SYSTEMS`.
    BeiDou GEO satellites take the rotations of BDS-SIS-ICD-B1I-3.0,
    Table 5-11.

    Parameters
    ----------
    records : xr.Dataset
        Records of ``sv`` along ``record`` (fields of
        :data:`canvod.readers.rinex.nav.FIELDS`), one per value of ``t``.
    t : np.ndarray
        Seconds since the GPS epoch (1980-01-06), one per record.
    sv : str
        The satellite, e.g. ``"C01"``.

    Returns
    -------
    np.ndarray
        ``(len(t), 3)`` ECEF X, Y, Z in meters.
    """
    system = KEPLER_SYSTEMS[sv[0]]
    omega_e = system.omega_e_dot

    def field(name: str) -> np.ndarray:
        return records[name].values

    tk = t - _toe_gps_seconds(records, system)  # continuous: no week crossover
    a = field("sqrt_a") ** 2
    n = np.sqrt(system.mu / a**3) + field("delta_n")
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
    geo = sv in BEIDOU_GEO
    # The node is rotated with the Earth, except for GEO satellites, whose
    # positions are rotated into the Earth-fixed frame below
    om = (
        field("omega0")
        + (field("omega_dot") - (0.0 if geo else omega_e)) * tk
        - omega_e * field("toe")
    )
    xyz = np.stack(
        [
            x_orb * np.cos(om) - y_orb * np.cos(i) * np.sin(om),
            x_orb * np.sin(om) + y_orb * np.cos(i) * np.cos(om),
            y_orb * np.sin(i),
        ],
        axis=-1,
    )
    if not geo:
        return xyz
    # R_Z(omega_e * tk) R_X(-5 deg), BDS-SIS-ICD-B1I-3.0, Table 5-11
    cx, sx = np.cos(_BEIDOU_GEO_TILT), np.sin(_BEIDOU_GEO_TILT)
    x_g = xyz[:, 0]
    y_g = cx * xyz[:, 1] + sx * xyz[:, 2]
    z_g = -sx * xyz[:, 1] + cx * xyz[:, 2]
    cz, sz = np.cos(omega_e * tk), np.sin(omega_e * tk)
    return np.stack([cz * x_g + sz * y_g, -sz * x_g + cz * y_g, z_g], axis=-1)


def sbas_states(records: xr.Dataset, dt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Positions and velocities of SBAS records ``dt`` seconds after ``toc``.

    A record gives the satellite's ECEF position, velocity and acceleration
    at its time of clock (RINEX 3.05, Table A16); the position moves with
    the velocity and the acceleration from there: ``x + v dt + a dt^2 / 2``.

    Parameters
    ----------
    records : xr.Dataset
        SBAS records along ``record`` (fields of
        :data:`canvod.readers.rinex.nav.SBAS_FIELDS`, km), one per value of
        ``dt``.
    dt : np.ndarray
        Seconds from each record's time of clock.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(len(dt), 3)`` ECEF positions (m) and velocities (m/s).
    """

    def vector(names: tuple[str, str, str]) -> np.ndarray:
        return np.stack([records[name].values for name in names], axis=-1) * 1000.0

    pos = vector(("x", "y", "z"))
    vel = vector(("vx", "vy", "vz"))
    acc = vector(("ax", "ay", "az"))
    dt = np.asarray(dt, dtype=np.float64)[:, None]
    return pos + vel * dt + acc * dt**2 / 2, vel + acc * dt


def _nearest_record(toc: np.ndarray, t: np.ndarray, validity_s: float) -> np.ndarray:
    """Index of the record nearest to each of ``t``, -1 beyond ``validity_s``."""
    nearest = np.abs(t[:, None] - toc[None, :]).argmin(axis=1)
    valid = np.abs(t - toc[nearest]) <= validity_s
    return np.where(valid, nearest, -1)


def _valid_record(records: xr.Dataset, t: np.ndarray, sv: str) -> np.ndarray:
    """Index of the record to use at each of ``t``, -1 where none is valid.

    The record with the nearest time of ephemeris, if ``t`` lies within half
    the fit interval of it (:data:`KEPLER_SYSTEMS`). GPS records give their
    fit interval in hours (RINEX 3.05, Table A6); GPS fit intervals are 4
    hours or longer (IS-GPS-200N, 20.3.3.4.3.1), so a smaller value, as
    some converters write the fit interval flag (0 or 1) instead of the
    hours, counts as 4 hours.
    """
    system = KEPLER_SYSTEMS[sv[0]]
    toe = _toe_gps_seconds(records, system)
    fit_h = np.full(toe.shape, system.fit_interval_h)
    if "fit_interval" in records:
        given = records["fit_interval"].values
        fit_h = np.where(np.isfinite(given) & (given > fit_h), given, fit_h)
    nearest = np.abs(t[:, None] - toe[None, :]).argmin(axis=1)
    valid = np.abs(t - toe[nearest]) <= fit_h[nearest] * 3600 / 2
    return np.where(valid, nearest, -1)


#: Systems whose records give the state at the time of clock: how long a
#: record is used around it, seconds, and the states it gives.
_STATE_SYSTEMS = {
    "R": (GLONASS_VALIDITY_S, glonass_states),
    "S": (SBAS_VALIDITY_S, sbas_states),
}


def broadcast_orbits(
    records: dict[str, xr.Dataset],
    day_start: np.datetime64,
    step_s: float = GRID_STEP_S,
) -> xr.Dataset:
    """Positions and velocities of every satellite on a grid over one day.

    Parameters
    ----------
    records : dict[str, xr.Dataset]
        Navigation records by system, from
        :func:`canvod.readers.rinex.nav.read_rinex_nav`. Systems without an
        orbit here are left out.
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

    by_sv = {
        str(sv): system_records.isel(
            record=np.flatnonzero(system_records.sv.values == sv)
        )
        for system, system_records in records.items()
        if system in ORBIT_SYSTEMS
        for sv in np.unique(system_records.sv.values)
    }
    svs = sorted(by_sv)
    pos = np.full((n_epochs, len(svs), 3), np.nan)
    vel = np.full_like(pos, np.nan)
    for j, sv in enumerate(svs):
        recs = by_sv[sv]
        if sv[0] in _STATE_SYSTEMS:
            validity_s, states = _STATE_SYSTEMS[sv[0]]
            toc = _gps_seconds(recs.toc.values)
            index = _nearest_record(toc, t, validity_s)
            ok = index >= 0
            pos[ok, j], vel[ok, j] = states(
                recs.isel(record=index[ok]), t[ok] - toc[index[ok]]
            )
            continue
        index = _valid_record(recs, t, sv)
        ok = index >= 0
        chosen = recs.isel(record=index[ok])
        tt = t[ok]
        pos[ok, j] = kepler_positions(chosen, tt, sv)
        vel[ok, j] = (
            kepler_positions(chosen, tt + _VELOCITY_HALF_STEP_S, sv)
            - kepler_positions(chosen, tt - _VELOCITY_HALF_STEP_S, sv)
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
