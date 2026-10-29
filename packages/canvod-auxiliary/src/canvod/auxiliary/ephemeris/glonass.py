"""GLONASS satellite orbits from broadcast ephemeris records.

A GLONASS record gives the satellite's position, velocity and luni-solar
acceleration at the time ``tb`` in the Earth-fixed PZ-90 frame. The orbit at
another time is the numerical integration of the equations of motion from
``tb`` (ICD GLONASS, Edition 5.1, 2008, A.3.1.2): central gravity, the second
zonal harmonic J2, the Earth's rotation, and the record's luni-solar
acceleration, constant over the integration interval of +/-15 minutes.
Integrated with the 4th order Runge-Kutta method (ICD GLONASS, A.3.1.2 and
A.3.1.1) in steps of at most 60 s.

The record fields are those of
:data:`canvod.readers.rinex.nav.GLONASS_FIELDS`: kilometers and seconds, as
in the RINEX navigation file (RINEX 3.05, Table A10).
"""

from __future__ import annotations

import numpy as np
import xarray as xr

#: Constants of the equations of motion (ICD GLONASS, Edition 5.1, 2008,
#: A.3.1.2): gravitational constant (m^3/s^2), semi-major axis of the Earth
#: (m), second zonal harmonic of the geopotential, Earth rotation rate
#: (rad/s).
GLONASS_MU = 398600.44e9
GLONASS_AE = 6_378_136.0
GLONASS_J2 = 1082625.7e-9
GLONASS_OMEGA = 7.292115e-5

#: The luni-solar accelerations of a record are constant over +/-15 minutes
#: around its time ``tb`` (ICD GLONASS, A.3.1.2): a record is used within
#: that interval only, seconds.
GLONASS_VALIDITY_S = 900.0

#: Longest Runge-Kutta step, seconds.
MAX_STEP_S = 60.0

_KM = 1000.0


def _derivatives(
    pos: np.ndarray, vel: np.ndarray, acc: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Velocity and acceleration of the equations of motion, ICD A.3.1.2.

    ``pos``, ``vel``, ``acc`` are ``(n, 3)`` arrays in m, m/s and m/s^2;
    ``acc`` is the record's luni-solar acceleration.

    Two terms differ from A.3.1.2 as printed in Edition 5.1: the Coriolis
    term of ``dVy/dt`` is ``-2 omega Vx`` (printed ``+``), and the J2 term of
    ``dVz/dt`` has ``(3 - 5 z^2/r^2)`` (printed ``1``), as in the precise
    algorithm, A.3.1.1, equation (1). With the printed signs, the orbits of
    the test day differ from the COD final orbits by a median of 28 km
    (Coriolis) and 5.8 m (J2), against 2.8 m with the terms used here.
    """
    x, y, z = pos.T
    r2 = np.einsum("ij,ij->i", pos, pos)
    r = np.sqrt(r2)
    mu_r3 = GLONASS_MU / (r2 * r)
    j2 = 1.5 * GLONASS_J2 * GLONASS_MU * GLONASS_AE**2 / (r2 * r2 * r)
    z2_r2 = 5.0 * z**2 / r2
    w2 = GLONASS_OMEGA**2
    dvx = (
        -mu_r3 * x
        - j2 * x * (1 - z2_r2)
        + w2 * x
        + 2 * GLONASS_OMEGA * vel[:, 1]
        + acc[:, 0]
    )
    dvy = (
        -mu_r3 * y
        - j2 * y * (1 - z2_r2)
        + w2 * y
        - 2 * GLONASS_OMEGA * vel[:, 0]
        + acc[:, 1]
    )
    dvz = -mu_r3 * z - j2 * z * (3 - z2_r2) + acc[:, 2]
    return vel, np.stack([dvx, dvy, dvz], axis=-1)


def glonass_states(
    records: xr.Dataset, dt: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Positions and velocities of GLONASS records ``dt`` seconds after ``tb``.

    Parameters
    ----------
    records : xr.Dataset
        GLONASS records along ``record`` (fields of
        :data:`canvod.readers.rinex.nav.GLONASS_FIELDS`), one per value of
        ``dt``.
    dt : np.ndarray
        Seconds from each record's time ``tb`` (negative: before it).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(len(dt), 3)`` ECEF positions (m) and velocities (m/s), PZ-90.
    """

    def vector(names: tuple[str, str, str]) -> np.ndarray:
        return np.stack([records[name].values for name in names], axis=-1) * _KM

    pos = vector(("x", "y", "z"))
    vel = vector(("vx", "vy", "vz"))
    acc = vector(("ax", "ay", "az"))
    dt = np.asarray(dt, dtype=np.float64)
    # The same number of steps for every record, each record its own step
    n_steps = max(1, int(np.ceil(np.abs(dt).max(initial=0.0) / MAX_STEP_S)))
    h = (dt / n_steps)[:, None]
    for _ in range(n_steps):
        k1p, k1v = _derivatives(pos, vel, acc)
        k2p, k2v = _derivatives(pos + h / 2 * k1p, vel + h / 2 * k1v, acc)
        k3p, k3v = _derivatives(pos + h / 2 * k2p, vel + h / 2 * k2v, acc)
        k4p, k4v = _derivatives(pos + h * k3p, vel + h * k3v, acc)
        pos = pos + h / 6 * (k1p + 2 * k2p + 2 * k3p + k4p)
        vel = vel + h / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
    return pos, vel


def glonass_valid_record(tb: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Index of the record to use at each of ``t``, -1 where none is valid.

    The record with the nearest time ``tb``, if ``t`` lies within
    :data:`GLONASS_VALIDITY_S` of it. ``tb`` and ``t`` are seconds on the
    same time scale.
    """
    nearest = np.abs(t[:, None] - tb[None, :]).argmin(axis=1)
    valid = np.abs(t - tb[nearest]) <= GLONASS_VALIDITY_S
    return np.where(valid, nearest, -1)
