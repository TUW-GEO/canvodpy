"""Solar position calculations and corrections for VOD data.

Provides tools to compute solar positions and apply corrections to account
for solar radiation effects on vegetation optical depth measurements.

Classes
-------
SolarPositionCalculator – solar zenith / azimuth and VOD correction.

Convenience functions
---------------------
``compute_solar_zenith``   – quick zenith-only computation.
``filter_daytime_data``    – mask nighttime observations.

Notes
-----
* When *pvlib* is installed it is preferred for high-accuracy
  calculations.  The built-in fallback uses NOAA algorithms
  (accuracy ~0.01° for 1800–2100).
* All public methods accept either ``np.ndarray`` of ``datetime64``
  or ``pd.DatetimeIndex``.

"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd
import structlog
import xarray as xr

logger = structlog.get_logger(__name__)


class SolarPositionCalculator:
    """Calculate solar positions for VOD corrections.

    Parameters
    ----------
    lat : float
        Observer latitude in degrees (positive = North).
    lon : float
        Observer longitude in degrees (positive = East).
    elevation : float
        Elevation above sea level in meters (default: 0).
    use_pvlib : bool
        If ``True``, use *pvlib* when available (more accurate).
        Falls back to built-in formulas automatically.

    Examples
    --------
    >>> calc = SolarPositionCalculator(lat=40.0, lon=-105.0, elevation=1655)
    >>> times = pd.date_range('2025-01-01', periods=24, freq='1H')
    >>> zenith, azimuth = calc.compute_solar_position(times)
    >>> corrected = calc.apply_solar_correction(vod_data, times)

    """

    def __init__(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        use_pvlib: bool = True,
    ) -> None:
        """Initialize the solar position calculator.

        Parameters
        ----------
        lat : float
            Observer latitude in degrees.
        lon : float
            Observer longitude in degrees.
        elevation : float, default 0.0
            Elevation above sea level in meters.
        use_pvlib : bool, default True
            Whether to use pvlib if available.

        """
        self.lat = lat
        self.lon = lon
        self.elevation = elevation
        self.use_pvlib = use_pvlib
        self.pvlib = None

        if use_pvlib:
            try:
                import pvlib  # type: ignore[unresolved-import]

                self.pvlib = pvlib
                logger.info("Using pvlib for solar position calculations")
            except ImportError:
                logger.warning(
                    "pvlib not available, falling back to built-in formulas. "
                    "Install pvlib for higher accuracy: uv add pvlib"
                )
                self.use_pvlib = False

    # ------------------------------------------------------------------
    # Core position computation
    # ------------------------------------------------------------------

    def compute_solar_position(
        self, times: np.ndarray | pd.DatetimeIndex
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute solar zenith and azimuth angles.

        Parameters
        ----------
        times : np.ndarray or pd.DatetimeIndex
            Array of ``datetime64`` or ``DatetimeIndex``.

        Returns
        -------
        solar_zenith : np.ndarray
            Solar polar angles in degrees (0° = directly overhead).
        solar_azimuth : np.ndarray
            Solar azimuth angles in degrees (0° = North, 90° = East).

        """
        if isinstance(times, np.ndarray):
            times = pd.to_datetime(times)

        if self.use_pvlib and self.pvlib is not None:
            return self._compute_solar_position_pvlib(times)
        return self._compute_solar_position_builtin(times)

    def _compute_solar_position_pvlib(
        self, times: pd.DatetimeIndex
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute solar position using pvlib (high accuracy)."""
        location = self.pvlib.location.Location(  # ty: ignore[unresolved-attribute]
            latitude=self.lat,
            longitude=self.lon,
            altitude=self.elevation,
            tz="UTC",
        )

        if times.tz is None:
            times = times.tz_localize("UTC")

        solar_position = location.get_solarposition(times)

        zenith = solar_position["apparent_zenith"].values
        azimuth = solar_position["azimuth"].values
        return zenith, azimuth

    def _compute_solar_position_builtin(
        self, times: pd.DatetimeIndex
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute solar position using built-in NOAA algorithms.

        Accuracy ~0.01° for years 1800–2100.
        """
        jd = self._datetime_to_julian_day(times)
        jc = (jd - 2451545.0) / 36525.0

        # Geometric mean longitude of sun (degrees)
        geom_mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360

        # Geometric mean anomaly of sun (degrees)
        geom_mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)

        # Eccentricity of Earth's orbit
        eccent = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)

        # Sun equation of center
        sun_eq_ctr = (
            np.sin(np.radians(geom_mean_anom))
            * (1.914602 - jc * (0.004817 + 0.000014 * jc))
            + np.sin(np.radians(2 * geom_mean_anom)) * (0.019993 - 0.000101 * jc)
            + np.sin(np.radians(3 * geom_mean_anom)) * 0.000289
        )

        # Sun true longitude (degrees)
        sun_true_long = geom_mean_long + sun_eq_ctr

        # Sun apparent longitude (degrees)
        sun_app_long = (
            sun_true_long
            - 0.00569
            - 0.00478 * np.sin(np.radians(125.04 - 1934.136 * jc))
        )

        # Mean obliquity of ecliptic (degrees)
        mean_obliq_ecliptic = (
            23
            + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
        )

        # Obliquity correction (degrees)
        obliq_corr = mean_obliq_ecliptic + 0.00256 * np.cos(
            np.radians(125.04 - 1934.136 * jc)
        )

        # Sun declination (degrees)
        sun_decl = np.degrees(
            np.arcsin(np.sin(np.radians(obliq_corr)) * np.sin(np.radians(sun_app_long)))
        )

        # Equation of time (minutes)
        var_y = np.tan(np.radians(obliq_corr / 2)) ** 2
        eq_of_time = 4 * np.degrees(
            var_y * np.sin(2 * np.radians(geom_mean_long))
            - 2 * eccent * np.sin(np.radians(geom_mean_anom))
            + 4
            * eccent
            * var_y
            * np.sin(np.radians(geom_mean_anom))
            * np.cos(2 * np.radians(geom_mean_long))
            - 0.5 * var_y * var_y * np.sin(4 * np.radians(geom_mean_long))
            - 1.25 * eccent * eccent * np.sin(2 * np.radians(geom_mean_anom))
        )

        # True solar time (minutes)
        time_offset = eq_of_time + 4 * self.lon
        hour = times.hour + times.minute / 60.0 + times.second / 3600.0  # ty: ignore[unresolved-attribute]
        true_solar_time = (hour * 60 + time_offset) % 1440

        # Hour angle (degrees)
        hour_angle = true_solar_time / 4 - 180
        hour_angle = np.where(hour_angle < 0, hour_angle + 360, hour_angle)

        # Solar polar angle (degrees)
        lat_rad = np.radians(self.lat)
        decl_rad = np.radians(sun_decl)
        ha_rad = np.radians(hour_angle)

        zenith = np.degrees(
            np.arccos(
                np.sin(lat_rad) * np.sin(decl_rad)
                + np.cos(lat_rad) * np.cos(decl_rad) * np.cos(ha_rad)
            )
        )

        # Solar azimuth angle (degrees from North)
        azimuth_rad = np.arccos(
            (np.sin(lat_rad) * np.cos(np.radians(zenith)) - np.sin(decl_rad))
            / (np.cos(lat_rad) * np.sin(np.radians(zenith)))
        )
        azimuth = np.degrees(azimuth_rad)

        # Adjust for morning vs afternoon
        azimuth = np.where(hour_angle > 0, azimuth, 360 - azimuth)

        return zenith, azimuth

    @staticmethod
    def _datetime_to_julian_day(times: pd.DatetimeIndex) -> np.ndarray:
        """Convert datetime to Julian Day Number."""
        dt = pd.to_datetime(times)
        year = dt.year  # ty: ignore[unresolved-attribute]
        month = dt.month  # ty: ignore[unresolved-attribute]
        day = dt.day  # ty: ignore[unresolved-attribute]
        hour = dt.hour  # ty: ignore[unresolved-attribute]
        minute = dt.minute  # ty: ignore[unresolved-attribute]
        second = dt.second  # ty: ignore[unresolved-attribute]

        a = (14 - month) // 12
        y = year + 4800 - a
        m = month + 12 * a - 3

        jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
        fraction = (hour - 12) / 24.0 + minute / 1440.0 + second / 86400.0

        return jdn + fraction

    # ------------------------------------------------------------------
    # Derived quantities
    # ------------------------------------------------------------------

    def compute_solar_elevation(
        self, times: np.ndarray | pd.DatetimeIndex
    ) -> np.ndarray:
        """Compute solar elevation angle (complementary to zenith).

        Parameters
        ----------
        times : np.ndarray or pd.DatetimeIndex
            Array of times.

        Returns
        -------
        np.ndarray
            Solar elevation angles in degrees (0° = horizon, 90° = overhead).

        """
        zenith, _ = self.compute_solar_position(times)
        return 90.0 - zenith

    def is_daytime(
        self,
        times: np.ndarray | pd.DatetimeIndex,
        twilight_angle: float = -6.0,
    ) -> np.ndarray:
        """Determine if times are during daytime.

        Parameters
        ----------
        times : np.ndarray or pd.DatetimeIndex
            Array of times.
        twilight_angle : float
            Solar elevation threshold in degrees.
            Common values: ``0`` (geometric), ``-6`` (civil),
            ``-12`` (nautical), ``-18`` (astronomical).

        Returns
        -------
        np.ndarray
            Boolean array (``True`` = daytime).

        """
        elevation = self.compute_solar_elevation(times)
        return elevation > twilight_angle

    # ------------------------------------------------------------------
    # Solar correction
    # ------------------------------------------------------------------

    def apply_solar_correction(
        self,
        data: xr.DataArray,
        method: Literal["normalize", "residual", "cos_correction"] = "normalize",
        reference_zenith: float = 45.0,
    ) -> xr.DataArray:
        """Apply solar correction to data.

        Parameters
        ----------
        data : xr.DataArray
            Input data with a time dimension (``'epoch'`` or ``'time'``).
        method : str
            Correction method:

            * ``'normalize'``      – normalize by cos(zenith) relative to
              *reference_zenith*.
            * ``'residual'``       – subtract a 4th-order polynomial fitted
              to the diurnal pattern (1-D data only; falls back to
              ``'normalize'`` for multi-dimensional data).
            * ``'cos_correction'`` – simple cosine correction.
        reference_zenith : float
            Reference polar angle for normalization (degrees).

        Returns
        -------
        xr.DataArray
            Solar-corrected data with correction metadata in attrs.

        """
        time_dim = "epoch" if "epoch" in data.dims else "time"
        times = pd.to_datetime(data[time_dim].values)

        zenith, _ = self.compute_solar_position(times)
        zenith_da = xr.DataArray(
            zenith,
            coords={time_dim: data[time_dim]},
            dims=[time_dim],
        )

        if method == "normalize":
            correction_factor = np.cos(np.radians(reference_zenith)) / np.cos(
                np.radians(zenith_da)
            )
            correction_factor = correction_factor.clip(0.5, 2.0)

            corrected = data * correction_factor
            corrected.attrs["solar_correction"] = "normalized"
            corrected.attrs["reference_zenith"] = reference_zenith

        elif method == "cos_correction":
            correction_factor = np.cos(np.radians(zenith_da))
            correction_factor = correction_factor.clip(0.1, 1.0)

            corrected = data / correction_factor
            corrected.attrs["solar_correction"] = "cos_correction"

        elif method == "residual":
            hour = times.hour + times.minute / 60.0  # ty: ignore[unresolved-attribute]

            if len(data.dims) == 1:
                valid = np.isfinite(data.values)
                if np.sum(valid) > 10:
                    coeffs = np.polyfit(hour[valid], data.values[valid], deg=4)
                    solar_model = np.polyval(coeffs, hour)
                    solar_model_da = xr.DataArray(
                        solar_model,
                        coords={time_dim: data[time_dim]},
                        dims=[time_dim],
                    )
                    corrected = data - solar_model_da
                    corrected.attrs["solar_correction"] = "residual"
                    corrected.attrs["polynomial_degree"] = 4
                else:
                    logger.warning("Insufficient data for residual correction")
                    corrected = data
            else:
                logger.warning(
                    "Residual correction for multi-dimensional data not yet "
                    "implemented, using normalize instead"
                )
                correction_factor = np.cos(np.radians(reference_zenith)) / np.cos(
                    np.radians(zenith_da)
                )
                correction_factor = correction_factor.clip(0.5, 2.0)
                corrected = data * correction_factor
                corrected.attrs["solar_correction"] = "normalize_fallback"
        else:
            raise ValueError(f"Unknown correction method: {method}")

        return corrected

    # ------------------------------------------------------------------
    # Binning & sunrise/sunset
    # ------------------------------------------------------------------

    def compute_solar_bins(
        self,
        times: np.ndarray | pd.DatetimeIndex,
        n_bins: int = 12,
    ) -> np.ndarray:
        """Bin times by solar elevation angle.

        Useful for solar-elevation-based composites instead of
        hour-of-day composites.

        Parameters
        ----------
        times : np.ndarray or pd.DatetimeIndex
            Array of times.
        n_bins : int
            Number of solar elevation bins (range −20° to 90°).

        Returns
        -------
        np.ndarray
            Bin indices (0-based) for each time.

        """
        elevation = self.compute_solar_elevation(times)
        bin_edges = np.linspace(-20, 90, n_bins + 1)
        bin_indices = np.digitize(elevation, bin_edges) - 1
        return np.clip(bin_indices, 0, n_bins - 1)

    def get_sunrise_sunset(
        self, date: datetime
    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        """Compute sunrise and sunset times for a given date.

        Parameters
        ----------
        date : datetime
            Date to compute sunrise/sunset for.

        Returns
        -------
        sunrise : pd.Timestamp or None
            Sunrise time in UTC, or ``None`` if the sun never rises.
        sunset : pd.Timestamp or None
            Sunset time in UTC, or ``None`` if the sun never sets.

        """
        times = pd.date_range(
            start=date.replace(hour=0, minute=0, second=0),
            end=date.replace(hour=23, minute=59, second=59),
            freq="1min",
        )

        elevation = self.compute_solar_elevation(times)
        above_horizon = np.where(elevation > 0)[0]

        sunrise = times[above_horizon[0]] if len(above_horizon) > 0 else None
        sunset = times[above_horizon[-1]] if len(above_horizon) > 0 else None

        return sunrise, sunset

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.

        """
        method = "pvlib" if self.use_pvlib else "builtin"
        return (
            f"SolarPositionCalculator(lat={self.lat:.4f}°, lon={self.lon:.4f}°, "
            f"elevation={self.elevation:.0f}m, method={method})"
        )


# ----------------------------------------------------------------------
# Convenience functions
# ----------------------------------------------------------------------


def compute_solar_zenith(
    lat: float, lon: float, times: np.ndarray | pd.DatetimeIndex
) -> np.ndarray:
    """Quick computation of solar polar angles.

    Parameters
    ----------
    lat : float
        Observer latitude in degrees.
    lon : float
        Observer longitude in degrees.
    times : np.ndarray or pd.DatetimeIndex
        Times to compute for.

    Returns
    -------
    np.ndarray
        Solar polar angles in degrees.

    """
    calc = SolarPositionCalculator(lat, lon)
    zenith, _ = calc.compute_solar_position(times)
    return zenith


def filter_daytime_data(
    data: xr.DataArray,
    lat: float,
    lon: float,
    twilight_angle: float = -6.0,
) -> xr.DataArray:
    """Filter data to include only daytime observations.

    Nighttime values are set to NaN.

    Parameters
    ----------
    data : xr.DataArray
        Data with a time dimension (``'epoch'`` or ``'time'``).
    lat : float
        Observer latitude in degrees.
    lon : float
        Observer longitude in degrees.
    twilight_angle : float
        Elevation threshold for daytime (degrees below horizon).

    Returns
    -------
    xr.DataArray
        Filtered data.

    """
    calc = SolarPositionCalculator(lat, lon)
    time_dim = "epoch" if "epoch" in data.dims else "time"
    times = pd.to_datetime(data[time_dim].values)
    is_day = calc.is_daytime(times, twilight_angle)
    return data.where(is_day)
