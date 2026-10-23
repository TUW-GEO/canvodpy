"""Spherical coordinate computation for GNSS satellite-receiver geometry.

Computes spherical coordinates (r, θ, φ) in navigation convention using
local ENU (East-North-Up) topocentric frame.

The azimuthal angle φ follows geographic/navigation standards with North=0°
and clockwise rotation (0°=North, 90°=East, 180°=South, 270°=West).
"""

import numpy as np
import pymap3d as pm
import xarray as xr

from canvod.auxiliary.position.position import ECEFPosition


def compute_spherical_coordinates(
    sat_x: np.ndarray | float,
    sat_y: np.ndarray | float,
    sat_z: np.ndarray | float,
    rx_pos: ECEFPosition,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute spherical coordinates (r, theta, phi) in navigation convention.

    Uses local ENU (East-North-Up) topocentric frame centered at receiver.

    Navigation Convention:
    - theta: Polar angle from +z axis (zenith), [0, π] radians
      * theta = 0 → zenith (straight up)
      * theta = π/2 → horizon
      * theta > π/2 → below horizon (set to NaN)
    - phi: Azimuthal angle from North, clockwise, [0, 2π) radians
      * phi = 0 → North
      * phi = π/2 → East
      * phi = π → South
      * phi = 3π/2 → West
    - r: Radial distance in meters

    Note
    ----
    The phi convention follows geographic/navigation standards where:
    - 0° points North (positive Y in ENU frame)
    - Angles increase clockwise when viewed from above
    - This is computed as arctan2(East, North), giving North=0° reference
    - Differs from physics convention which uses East=0° reference

    Parameters
    ----------
    sat_x : np.ndarray
        Satellite X coordinates in ECEF (meters).
    sat_y : np.ndarray
        Satellite Y coordinates in ECEF (meters).
    sat_z : np.ndarray
        Satellite Z coordinates in ECEF (meters).
    rx_pos : ECEFPosition
        Receiver position in ECEF.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        (r, theta, phi) where:
        - r: distances in meters
        - theta: polar angles in radians [0, π]
        - phi: azimuthal angles in radians [0, 2π)

    Notes
    -----
    Satellites below horizon (theta > π/2) are set to NaN.

    Examples
    --------
    >>> from canvod.auxiliary.position import (
    ...     ECEFPosition, compute_spherical_coordinates,
    ... )
    >>>
    >>> # Receiver position
    >>> rx = ECEFPosition(x=4194304.0, y=176481.0, z=4780013.0)
    >>>
    >>> # Satellite positions (example)
    >>> sat_x = np.array([16364123.0, 10205789.0])
    >>> sat_y = np.array([12123456.0, -8901234.0])
    >>> sat_z = np.array([18456789.0, 21234567.0])
    >>>
    >>> r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, rx)
    >>> print(f"Distance: {r[0]/1e6:.2f} Mm")
    >>> print(f"Polar angle: {np.degrees(theta[0]):.1f}°")
    >>> print(f"Azimuth: {np.degrees(phi[0]):.1f}°")
    """
    # Receiver ECEF coordinates
    rx_x = rx_pos.x
    rx_y = rx_pos.y
    rx_z = rx_pos.z

    # Convert receiver ECEF to geodetic (lat, lon, alt)
    lat, lon, alt = pm.ecef2geodetic(rx_x, rx_y, rx_z)

    # Convert satellite ECEF to ENU (East-North-Up) relative to receiver
    e, n, u = pm.ecef2enu(sat_x, sat_y, sat_z, lat, lon, alt)

    # Compute radial distance
    r = np.sqrt(e**2 + n**2 + u**2)

    # Compute theta: polar angle from +z (Up) axis
    # Clamp u/r to [-1, 1] to handle numerical errors
    cos_theta = np.clip(
        np.divide(u, r, out=np.full_like(r, np.nan, dtype=float), where=r != 0),
        -1.0,
        1.0,
    )
    theta = np.arccos(cos_theta)

    # Mask satellites below horizon (u < 0 means below horizon)
    below_horizon = u < 0

    # Compute phi: azimuthal angle from North, clockwise (navigation convention)
    # phi = arctan2(East, North) gives North=0°, East=90°, South=180°, West=270°
    phi = np.arctan2(e, n)
    phi = np.mod(phi, 2 * np.pi)  # Wrap to [0, 2π)

    # Set below-horizon satellites to NaN
    r = np.where(below_horizon, np.nan, r)
    theta = np.where(below_horizon, np.nan, theta)
    phi = np.where(below_horizon, np.nan, phi)

    return r, theta, phi


_BROADCAST_OBS_THETA_ATTRS: dict[str, object] = {
    "long_name": "Satellite polar angle (broadcast ephemeris)",
    "coverage_content_type": "auxiliaryInformation",
    "short_name": "θ_B",
    "units": "rad",
    "description": "Polar angle from zenith (+z/Up), broadcast navigation solution",
    "valid_range": [0.0, np.pi / 2],
    "convention": "physics (0=zenith, π/2=horizon)",
    "source": "SBF SatVisibility block, receiver firmware (broadcast ephemeris)",
    "comment": (
        "Computed by the receiver firmware from the satellite's broadcast "
        "ephemeris (SatVisibility SatelliteInfo = 2), reported in steps of "
        "0.01 deg. Almanac-based angles are excluded (NaN). "
        "NOT from independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
}

_BROADCAST_OBS_PHI_ATTRS: dict[str, object] = {
    "long_name": "Azimuthal angle (broadcast ephemeris, navigation convention)",
    "coverage_content_type": "auxiliaryInformation",
    "short_name": "φ_B",
    "units": "rad",
    "description": "Azimuthal angle from North in ENU frame, clockwise (broadcast)",
    "valid_range": [0.0, 2 * np.pi],
    "convention": "navigation (0=North, π/2=East, π=South, 3π/2=West)",
    "source": "SBF SatVisibility block, receiver firmware (broadcast ephemeris)",
    "comment": (
        "Computed by the receiver firmware from the satellite's broadcast "
        "ephemeris (SatVisibility SatelliteInfo = 2), reported in steps of "
        "0.01 deg. Almanac-based angles are excluded (NaN). "
        "NOT from independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
}


def add_broadcast_spherical_coords_to_dataset(
    ds: xr.Dataset,
    theta: np.ndarray,
    phi: np.ndarray,
) -> xr.Dataset:
    """Add broadcast spherical coordinates to xarray Dataset.

    Same convention as :func:`add_spherical_coords_to_dataset` but attrs
    reflect that values come from the receiver's SBF SatVisibility block
    (broadcast ephemeris) rather than independently-computed SP3/CLK
    ephemerides.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with 'epoch' and 'sid' dimensions.
    theta : np.ndarray
        Polar angles in radians [0, π].
    phi : np.ndarray
        Azimuthal angles in radians [0, 2π).

    Returns
    -------
    xr.Dataset
        Dataset with phi and theta variables added.
    """
    ds["theta"] = xr.DataArray(
        theta,
        coords=[ds["epoch"], ds["sid"]],
        dims=["epoch", "sid"],
        attrs=_BROADCAST_OBS_THETA_ATTRS,
    )
    ds["phi"] = xr.DataArray(
        phi,
        coords=[ds["epoch"], ds["sid"]],
        dims=["epoch", "sid"],
        attrs=_BROADCAST_OBS_PHI_ATTRS,
    )
    return ds


def add_spherical_coords_to_dataset(
    ds: xr.Dataset,
    r: np.ndarray,
    theta: np.ndarray,
    phi: np.ndarray,
) -> xr.Dataset:
    """Add spherical coordinates to xarray Dataset with proper metadata.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with 'epoch' and 'sid' dimensions.
    r : np.ndarray
        Radial distances in meters.
    theta : np.ndarray
        Polar angles in radians [0, π].
    phi : np.ndarray
        Azimuthal angles in radians [0, 2π).

    Returns
    -------
    xr.Dataset
        Dataset with phi, theta, r variables added.

    Notes
    -----
    Variables are added with CF-compliant attributes following physics
    convention.

    Examples
    --------
    >>> # After computing spherical coordinates
    >>> r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, rx_pos)
    >>>
    >>> # Add to RINEX dataset
    >>> augmented_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)
    >>> print(augmented_ds.phi.attrs['description'])
    """
    ds = ds.assign(
        {
            "phi": xr.DataArray(
                phi,
                coords=[ds["epoch"], ds["sid"]],
                dims=["epoch", "sid"],
                attrs={
                    "long_name": "Azimuthal angle (navigation convention)",
                    "coverage_content_type": "auxiliaryInformation",
                    "short_name": "φ",
                    "units": "rad",
                    "description": (
                        "Azimuthal angle from North in ENU frame, clockwise"
                    ),
                    "valid_range": [0.0, 2 * np.pi],
                    "convention": "navigation (0=North, π/2=East, π=South, 3π/2=West)",
                },
            ),
            "theta": xr.DataArray(
                theta,
                coords=[ds["epoch"], ds["sid"]],
                dims=["epoch", "sid"],
                attrs={
                    "long_name": "Polar angle (physics convention)",
                    "coverage_content_type": "auxiliaryInformation",
                    "short_name": "θ",
                    "units": "rad",
                    "description": "Polar angle from zenith (+z/Up)",
                    "valid_range": [0.0, np.pi / 2],
                    "convention": "physics (0=zenith, π/2=horizon)",
                },
            ),
            "r": xr.DataArray(
                r,
                coords=[ds["epoch"], ds["sid"]],
                dims=["epoch", "sid"],
                attrs={
                    "long_name": "Distance",
                    "coverage_content_type": "auxiliaryInformation",
                    "short_name": "r",
                    "units": "m",
                    "description": "Distance between satellite and receiver",
                },
            ),
        }
    )
    return ds
