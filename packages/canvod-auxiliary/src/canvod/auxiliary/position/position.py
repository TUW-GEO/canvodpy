"""Position representations for GNSS data processing.

Provides classes for ECEF and geodetic position handling.
"""

import math
from dataclasses import dataclass
from typing import Self

import pymap3d as pm
import xarray as xr
from pydantic import BaseModel, ConfigDict, model_validator

# Ground-station plausibility band for ECEF magnitude: roughly on/near the
# WGS84 ellipsoid (equatorial radius 6378137 m, polar 6356752 m). Only
# enforced at the receiver-position parse boundary (from_ds_metadata()) --
# NOT a field constraint on ECEFPosition itself, since that class is also
# used as a general-purpose ECEF point (e.g. satellite positions in
# geometry/test code), which can be far outside this band.
_GROUND_STATION_MIN_RADIUS_M = 6.3e6
_GROUND_STATION_MAX_RADIUS_M = 6.5e6


class ECEFPosition(BaseModel):
    """Earth-Centered, Earth-Fixed (ECEF) position in meters.

    ECEF is a Cartesian coordinate system with:
    - Origin at Earth's center of mass
    - X-axis pointing to 0° latitude, 0° longitude (Prime Meridian at Equator)
    - Y-axis pointing to 0° latitude, 90° East longitude
    - Z-axis pointing to North Pole

    Parameters
    ----------
    x : float
        X coordinate in meters.
    y : float
        Y coordinate in meters.
    z : float
        Z coordinate in meters.

    Raises
    ------
    pydantic.ValidationError
        If any component is non-finite (NaN/inf), or the position is
        exactly (0, 0, 0) -- Earth's center, never a physically valid ECEF
        point for anything this codebase computes geometry relative to.
        This is deliberately a *general* sanity check (applies to satellite
        positions too, not just receivers) -- see ``from_ds_metadata()`` for
        the additional ground-station-specific plausibility check.

    Examples
    --------
    >>> # From RINEX dataset metadata
    >>> pos = ECEFPosition.from_ds_metadata(rinex_ds)
    >>> print(f"X: {pos.x:.3f} m")

    >>> # Manual creation
    >>> pos = ECEFPosition(x=4194304.123, y=176481.234, z=4780013.456)
    >>> lat, lon, alt = pos.to_geodetic()
    """

    model_config = ConfigDict(frozen=True)

    x: float  # meters
    y: float  # meters
    z: float  # meters

    @model_validator(mode="after")
    def _validate_physically_possible(self) -> Self:
        for _name, _v in (("x", self.x), ("y", self.y), ("z", self.z)):
            if not math.isfinite(_v):
                raise ValueError(f"ECEF {_name} must be finite, got {_v!r}")
        if self.x == 0.0 and self.y == 0.0 and self.z == 0.0:
            raise ValueError(
                "ECEF position is exactly (0, 0, 0) -- Earth's center, not "
                "a physically valid point. This usually means an upstream "
                "parser defaulted to a placeholder instead of a real "
                "position (e.g. a RINEX header's APPROX POSITION XYZ was "
                "never populated)."
            )
        return self

    def to_geodetic(self) -> tuple[float, float, float]:
        """Convert ECEF to geodetic coordinates.

        Returns
        -------
        tuple[float, float, float]
            (latitude, longitude, altitude) where:
            - latitude: degrees [-90, 90]
            - longitude: degrees [-180, 180]
            - altitude: meters above WGS84 ellipsoid
        """
        lat, lon, alt = pm.ecef2geodetic(self.x, self.y, self.z)
        return lat, lon, alt

    @classmethod
    def from_ds_metadata(cls, ds: xr.Dataset) -> Self:
        """Extract ECEF position from RINEX dataset metadata.

        Reads from standard RINEX header attributes.

        Parameters
        ----------
        ds : xr.Dataset
            RINEX dataset with position in attributes.

        Returns
        -------
        ECEFPosition
            Receiver position in ECEF.

        Raises
        ------
        KeyError
            If position attributes not found in dataset.
        pydantic.ValidationError
            If the position is non-finite or exactly (0, 0, 0) (see
            ``ECEFPosition``'s own validator).
        ValueError
            If the position's ECEF magnitude falls outside the plausible
            ground-station band (``_GROUND_STATION_MIN_RADIUS_M`` ..
            ``_GROUND_STATION_MAX_RADIUS_M``, i.e. on/near the WGS84
            ellipsoid) -- e.g. an unpopulated RINEX header defaulted to a
            position that happens to be finite and non-zero but still not a
            real ground station (this check is specific to *this* parse
            boundary, not a general ``ECEFPosition`` constraint -- see the
            class docstring).

        Examples
        --------
        >>> from canvod.readers import Rnxv3Obs
        >>> rnx = Rnxv3Obs(fpath="station.24o")
        >>> ds = rnx.to_ds()
        >>> pos = ECEFPosition.from_ds_metadata(ds)
        """
        # Try different attribute names
        if "APPROX POSITION X" in ds.attrs:
            # Standard RINEX v3 format
            x = ds.attrs["APPROX POSITION X"]
            y = ds.attrs["APPROX POSITION Y"]
            z = ds.attrs["APPROX POSITION Z"]
        elif "Approximate Position" in ds.attrs:
            # Alternative format: "X=..., Y=..., Z=..."
            pos = ds.attrs["Approximate Position"]
            pos_parts = pos.split(",")

            def sanitize(s: str) -> float:
                return float(s.split("=")[1].strip().split()[0])

            x = sanitize(pos_parts[0])
            y = sanitize(pos_parts[1])
            z = sanitize(pos_parts[2])
        else:
            raise KeyError(
                "Position not found in dataset attributes. "
                "Expected 'APPROX POSITION X/Y/Z' or 'Approximate Position'"
            )

        pos = cls(x=x, y=y, z=z)
        magnitude = math.sqrt(pos.x**2 + pos.y**2 + pos.z**2)
        if not (
            _GROUND_STATION_MIN_RADIUS_M <= magnitude <= _GROUND_STATION_MAX_RADIUS_M
        ):
            raise ValueError(
                f"Receiver position magnitude {magnitude:.1f} m is outside "
                "the plausible ECEF range for a ground station "
                f"({_GROUND_STATION_MIN_RADIUS_M:.2e}-"
                f"{_GROUND_STATION_MAX_RADIUS_M:.2e} m, i.e. on/near the "
                f"WGS84 ellipsoid): {pos!r}. This usually means the RINEX "
                "header's APPROX POSITION XYZ is wrong or was never "
                "populated with the real (e.g. PPP-derived) position."
            )
        return pos

    def __repr__(self) -> str:
        return f"ECEFPosition(x={self.x:.3f}, y={self.y:.3f}, z={self.z:.3f})"


@dataclass(frozen=True)
class GeodeticPosition:
    """Geodetic (WGS84) position.

    Parameters
    ----------
    lat : float
        Latitude in degrees [-90, 90].
    lon : float
        Longitude in degrees [-180, 180].
    alt : float
        Altitude in meters above WGS84 ellipsoid.

    Examples
    --------
    >>> pos = GeodeticPosition(lat=48.208, lon=16.373, alt=200.0)
    >>> print(f"Vienna: {pos.lat}°N, {pos.lon}°E, {pos.alt}m")
    """

    lat: float  # degrees
    lon: float  # degrees
    alt: float  # meters

    def to_ecef(self) -> ECEFPosition:
        """Convert geodetic to ECEF coordinates.

        Returns
        -------
        ECEFPosition
            Position in ECEF frame.
        """
        x, y, z = pm.geodetic2ecef(self.lat, self.lon, self.alt)
        return ECEFPosition(x=x, y=y, z=z)

    def __repr__(self) -> str:
        return (
            f"GeodeticPosition(lat={self.lat:.6f}°, "
            f"lon={self.lon:.6f}°, alt={self.alt:.1f}m)"
        )
