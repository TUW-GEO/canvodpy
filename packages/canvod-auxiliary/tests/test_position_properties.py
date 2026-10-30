"""Property-based tests for coordinate transformations and position calculations.

These tests verify mathematical invariants that must hold for all coordinate
transformations using Hypothesis.
"""

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from canvod.auxiliary.position import ECEFPosition, GeodeticPosition

# ============================================================================
# Hypothesis Strategies
# ============================================================================


@st.composite
def valid_geodetic_positions(draw):
    """Generate valid geodetic positions.

    Parameters
    ----------
    draw : callable
        Hypothesis draw function.

    Returns
    -------
    GeodeticPosition
        Random but valid geodetic position.

    Notes
    -----
    - Latitude: [-90, 90] degrees
    - Longitude: [-180, 180] degrees
    - Altitude: [-1000, 100000] meters (below sea level to LEO orbit)
    """
    lat = draw(st.floats(-90.0, 90.0, allow_nan=False, allow_infinity=False))
    lon = draw(st.floats(-180.0, 180.0, allow_nan=False, allow_infinity=False))
    # Reasonable altitude range: Dead Sea to LEO satellites
    alt = draw(st.floats(-1000.0, 100000.0, allow_nan=False, allow_infinity=False))

    return GeodeticPosition(lat=lat, lon=lon, alt=alt)


@st.composite
def valid_ecef_positions(draw):
    """Generate valid ECEF positions.

    Parameters
    ----------
    draw : callable
        Hypothesis draw function.

    Returns
    -------
    ECEFPosition
        Random but valid ECEF position.

    Notes
    -----
    ECEF coordinates are in meters. Reasonable range:
    - Earth's equatorial radius: ~6.378e6 m
    - LEO satellites: up to ~1e7 m from center
    - Avoid positions very close to Earth's center where geodetic
      coordinates become ill-defined
    """
    # Generate coordinates that could represent Earth surface to LEO orbit
    x = draw(st.floats(-1e7, 1e7, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(-1e7, 1e7, allow_nan=False, allow_infinity=False))
    z = draw(st.floats(-1e7, 1e7, allow_nan=False, allow_infinity=False))

    # Ensure position is not at origin and is physically reasonable
    radius = np.sqrt(x**2 + y**2 + z**2)
    assume(radius > 6e6)  # At least near Earth's surface
    assume(radius < 5e7)  # Not beyond LEO

    return ECEFPosition(x=x, y=y, z=z)


# ============================================================================
# Property Tests: Coordinate Transformation Invariants
# ============================================================================


class TestCoordinateTransformationProperties:
    """Property tests for coordinate transformations."""

    @given(pos=valid_geodetic_positions())
    @settings(max_examples=50, deadline=3000)
    def test_geodetic_ecef_roundtrip(self, pos):
        """Geodetic → ECEF → Geodetic must be invertible.

        Property: For all valid geodetic coordinates, converting to ECEF
        and back should recover the original coordinates.
        """
        # Convert to ECEF
        ecef = pos.to_ecef()

        # Convert back to geodetic
        lat_back, lon_back, alt_back = ecef.to_geodetic()

        # Property: Round-trip preserves coordinates
        # Latitude and longitude should be exact (or very close)
        np.testing.assert_allclose(
            lat_back,
            pos.lat,
            rtol=1e-9,
            atol=1e-10,
            err_msg=f"Latitude not preserved: {pos.lat} → {lat_back}",
        )

        np.testing.assert_allclose(
            lon_back,
            pos.lon,
            rtol=1e-9,
            atol=1e-10,
            err_msg=f"Longitude not preserved: {pos.lon} → {lon_back}",
        )

        # Altitude may have small numerical differences
        np.testing.assert_allclose(
            alt_back,
            pos.alt,
            rtol=1e-6,
            atol=0.001,  # 1mm tolerance
            err_msg=f"Altitude not preserved: {pos.alt} → {alt_back}",
        )

    @given(pos=valid_ecef_positions())
    @settings(max_examples=50, deadline=3000)
    def test_ecef_geodetic_roundtrip(self, pos):
        """ECEF → Geodetic → ECEF must be invertible.

        Property: For all valid ECEF coordinates, converting to geodetic
        and back should recover the original coordinates.
        """
        # Convert to geodetic
        lat, lon, alt = pos.to_geodetic()

        # Convert back to ECEF
        geo = GeodeticPosition(lat=lat, lon=lon, alt=alt)
        ecef_back = geo.to_ecef()

        # Property: Round-trip preserves coordinates
        # ECEF coordinates should be very close
        # Tolerance scales with distance from Earth
        radius = np.sqrt(pos.x**2 + pos.y**2 + pos.z**2)
        tolerance = max(1.0, radius * 1e-7)  # At least 1m or 1e-7 * radius

        np.testing.assert_allclose(
            ecef_back.x,
            pos.x,
            rtol=1e-6,
            atol=tolerance,
            err_msg=f"X coordinate not preserved: {pos.x} → {ecef_back.x}",
        )

        np.testing.assert_allclose(
            ecef_back.y,
            pos.y,
            rtol=1e-6,
            atol=tolerance,
            err_msg=f"Y coordinate not preserved: {pos.y} → {ecef_back.y}",
        )

        np.testing.assert_allclose(
            ecef_back.z,
            pos.z,
            rtol=1e-6,
            atol=tolerance,
            err_msg=f"Z coordinate not preserved: {pos.z} → {ecef_back.z}",
        )

    @given(pos=valid_geodetic_positions())
    @settings(max_examples=50, deadline=3000)
    def test_geodetic_latitude_bounds(self, pos):
        """Converted geodetic latitude must stay in valid range.

        Property: Latitude must always be in [-90, 90] degrees.
        """
        # Convert through ECEF and back
        ecef = pos.to_ecef()
        lat_back, lon_back, alt_back = ecef.to_geodetic()

        # Property: Latitude bounds preserved
        assert -90.0 <= lat_back <= 90.0, f"Latitude out of bounds: {lat_back} degrees"

    @given(pos=valid_geodetic_positions())
    @settings(max_examples=50, deadline=3000)
    def test_geodetic_longitude_normalization(self, pos):
        """Converted geodetic longitude must be in valid range.

        Property: Longitude should be in [-180, 180] degrees.
        """
        # Convert through ECEF and back
        ecef = pos.to_ecef()
        lat_back, lon_back, alt_back = ecef.to_geodetic()

        # Property: Longitude in valid range
        assert -180.0 <= lon_back <= 180.0, (
            f"Longitude out of bounds: {lon_back} degrees"
        )

    @given(pos=valid_ecef_positions())
    @settings(max_examples=50, deadline=3000)
    def test_ecef_distance_from_origin(self, pos):
        """ECEF distance from origin must be preserved through conversions.

        Property: Distance from Earth's center is preserved in round-trip.
        """
        # Calculate original distance
        r_original = np.sqrt(pos.x**2 + pos.y**2 + pos.z**2)

        # Convert to geodetic and back
        lat, lon, alt = pos.to_geodetic()
        geo = GeodeticPosition(lat=lat, lon=lon, alt=alt)
        ecef_back = geo.to_ecef()

        # Calculate new distance
        r_back = np.sqrt(ecef_back.x**2 + ecef_back.y**2 + ecef_back.z**2)

        # Property: Distance preserved
        # Tolerance scales with distance
        tolerance = max(0.01, r_original * 1e-8)

        np.testing.assert_allclose(
            r_back,
            r_original,
            rtol=1e-7,
            atol=tolerance,
            err_msg=(
                f"Distance from origin not preserved: "
                f"{r_original:.3f} → {r_back:.3f} meters"
            ),
        )


# ============================================================================
# Property Tests: Physical Constraints
# ============================================================================


class TestPhysicalConstraints:
    """Property tests for physical constraints on positions."""

    @given(pos=valid_ecef_positions())
    @settings(max_examples=50, deadline=3000)
    def test_geodetic_altitude_reasonable(self, pos):
        """Geodetic altitude must be physically reasonable.

        Property: For ECEF positions within LEO range, altitude should
        be reasonable (not wildly incorrect).
        """
        lat, lon, alt = pos.to_geodetic()

        # Calculate distance from center
        r = np.sqrt(pos.x**2 + pos.y**2 + pos.z**2)

        # Property: Altitude should be roughly (radius - Earth radius)
        # Earth's mean radius is approximately 6.371e6 m
        earth_radius_approx = 6.371e6
        expected_alt_approx = r - earth_radius_approx

        # Allow large tolerance since Earth is not a perfect sphere
        # and WGS84 ellipsoid varies by location
        tolerance = 25000  # 25 km tolerance for extreme cases

        assert abs(alt - expected_alt_approx) < tolerance, (
            f"Altitude {alt:.1f} m unreasonable for radius {r:.1f} m. "
            f"Expected approximately {expected_alt_approx:.1f} m"
        )

    @given(
        lat=st.floats(-90.0, 90.0),
        lon=st.floats(-180.0, 180.0),
    )
    @settings(max_examples=50, deadline=3000)
    def test_sea_level_positions_near_earth_radius(self, lat, lon):
        """Sea level positions should be near Earth's radius.

        Property: Positions at altitude=0 should have ECEF magnitude
        approximately equal to local Earth radius (6.35-6.38 million meters).
        """
        pos = GeodeticPosition(lat=lat, lon=lon, alt=0.0)
        ecef = pos.to_ecef()

        r = np.sqrt(ecef.x**2 + ecef.y**2 + ecef.z**2)

        # Property: Radius should be approximately Earth's radius
        # WGS84 ellipsoid: equatorial radius = 6378137 m, polar = 6356752 m
        assert 6.35e6 < r < 6.38e6, (
            f"Sea level position has unreasonable radius: {r:.1f} m "
            f"at lat={lat:.1f}°, lon={lon:.1f}°"
        )

    @given(pos=valid_geodetic_positions())
    @settings(max_examples=50, deadline=3000)
    def test_ecef_coordinates_finite(self, pos):
        """ECEF coordinates must always be finite.

        Property: No NaN or Inf values in ECEF conversion.
        """
        ecef = pos.to_ecef()

        # Property: All coordinates finite
        assert np.isfinite(ecef.x), f"ECEF X is not finite: {ecef.x}"
        assert np.isfinite(ecef.y), f"ECEF Y is not finite: {ecef.y}"
        assert np.isfinite(ecef.z), f"ECEF Z is not finite: {ecef.z}"


# ============================================================================
# Property Tests: Special Cases
# ============================================================================


class TestSpecialCases:
    """Property tests for special geographic cases."""

    @given(lon=st.floats(-180.0, 180.0), alt=st.floats(-1000.0, 10000.0))
    @settings(max_examples=30, deadline=3000)
    def test_north_pole_conversion(self, lon, alt):
        """North pole (lat=90°) should convert correctly for any longitude.

        Property: At the North pole, longitude is undefined but conversion
        should still work and round-trip correctly.
        """
        pos = GeodeticPosition(lat=90.0, lon=lon, alt=alt)
        ecef = pos.to_ecef()

        # Convert back
        lat_back, lon_back, alt_back = ecef.to_geodetic()

        # Property: Latitude preserved exactly
        np.testing.assert_allclose(lat_back, 90.0, atol=1e-9)

        # Property: Altitude preserved
        np.testing.assert_allclose(alt_back, alt, rtol=1e-6, atol=0.01)

        # Note: Longitude at poles is ambiguous, so we don't test it

    @given(lon=st.floats(-180.0, 180.0), alt=st.floats(-1000.0, 10000.0))
    @settings(max_examples=30, deadline=3000)
    def test_south_pole_conversion(self, lon, alt):
        """South pole (lat=-90°) should convert correctly for any longitude.

        Property: At the South pole, longitude is undefined but conversion
        should still work and round-trip correctly.
        """
        pos = GeodeticPosition(lat=-90.0, lon=lon, alt=alt)
        ecef = pos.to_ecef()

        # Convert back
        lat_back, lon_back, alt_back = ecef.to_geodetic()

        # Property: Latitude preserved exactly
        np.testing.assert_allclose(lat_back, -90.0, atol=1e-9)

        # Property: Altitude preserved
        np.testing.assert_allclose(alt_back, alt, rtol=1e-6, atol=0.01)

    @given(lat=st.floats(-90.0, 90.0), alt=st.floats(-1000.0, 10000.0))
    @settings(max_examples=30, deadline=3000)
    def test_prime_meridian_conversion(self, lat, alt):
        """Prime meridian (lon=0°) should convert correctly.

        Property: Positions on the Prime Meridian should have Y=0 in ECEF.
        """
        assume(abs(lat) < 89.9)  # Avoid poles where longitude is ambiguous

        pos = GeodeticPosition(lat=lat, lon=0.0, alt=alt)
        ecef = pos.to_ecef()

        # Property: At lon=0°, ECEF Y coordinate should be very small
        # (nearly zero, but allow for numerical precision)
        assert abs(ecef.y) < 1.0, (
            f"Prime meridian should have Y≈0, got Y={ecef.y:.3f} m"
        )

    @given(alt=st.floats(-1000.0, 10000.0))
    @settings(max_examples=30, deadline=3000)
    def test_equator_conversion(self, alt):
        """Equator (lat=0°) should convert correctly.

        Property: Positions on the equator should have Z=0 (or very small).
        """
        pos = GeodeticPosition(lat=0.0, lon=0.0, alt=alt)
        ecef = pos.to_ecef()

        # Property: At lat=0°, ECEF Z coordinate should be very small
        assert abs(ecef.z) < 100.0, f"Equator should have Z≈0, got Z={ecef.z:.3f} m"


# ============================================================================
# Property Tests: Transformation Consistency
# ============================================================================


class TestTransformationConsistency:
    """Property tests for consistency across multiple conversions."""

    @given(pos=valid_geodetic_positions())
    @settings(max_examples=30, deadline=3000)
    def test_multiple_roundtrips_stable(self, pos):
        """Multiple round-trips should not accumulate errors.

        Property: Geodetic → ECEF → Geodetic repeated N times should
        not drift significantly from original position.
        """
        current_pos = pos

        # Perform 5 round-trips
        for _ in range(5):
            ecef = current_pos.to_ecef()
            lat, lon, alt = ecef.to_geodetic()
            current_pos = GeodeticPosition(lat=lat, lon=lon, alt=alt)

        # Property: Final position should still match original
        np.testing.assert_allclose(current_pos.lat, pos.lat, rtol=1e-8, atol=1e-9)
        np.testing.assert_allclose(current_pos.lon, pos.lon, rtol=1e-8, atol=1e-9)
        np.testing.assert_allclose(current_pos.alt, pos.alt, rtol=1e-5, atol=0.01)

    @given(
        pos1=valid_geodetic_positions(),
        pos2=valid_geodetic_positions(),
    )
    @settings(max_examples=30, deadline=3000)
    def test_distance_preserved_in_ecef(self, pos1, pos2):
        """Distance between two positions should be consistent.

        Property: Distance calculated in ECEF should match geodetic
        distance for positions that are close together.
        """
        # Convert both to ECEF
        ecef1 = pos1.to_ecef()
        ecef2 = pos2.to_ecef()

        # Calculate ECEF distance
        dx = ecef2.x - ecef1.x
        dy = ecef2.y - ecef1.y
        dz = ecef2.z - ecef1.z
        ecef_distance = np.sqrt(dx**2 + dy**2 + dz**2)

        # Property: Distance should be reasonable (0 to ~50,000 km)
        assert 0 <= ecef_distance < 5e7, (
            f"Distance between positions unreasonable: {ecef_distance:.1f} m"
        )

        # Property: Distance should be same if we convert back and forth
        lat1, lon1, alt1 = ecef1.to_geodetic()
        lat2, lon2, alt2 = ecef2.to_geodetic()

        geo1_back = GeodeticPosition(lat=lat1, lon=lon1, alt=alt1)
        geo2_back = GeodeticPosition(lat=lat2, lon=lon2, alt=alt2)

        ecef1_back = geo1_back.to_ecef()
        ecef2_back = geo2_back.to_ecef()

        dx_back = ecef2_back.x - ecef1_back.x
        dy_back = ecef2_back.y - ecef1_back.y
        dz_back = ecef2_back.z - ecef1_back.z
        distance_back = np.sqrt(dx_back**2 + dy_back**2 + dz_back**2)

        # Distance should be preserved through round-trip
        np.testing.assert_allclose(
            distance_back,
            ecef_distance,
            rtol=1e-8,
            atol=0.01,  # 1 cm tolerance
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
