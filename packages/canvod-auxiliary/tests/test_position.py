"""Tests for position and coordinate transformations."""

import numpy as np
import pytest
import xarray as xr
from canvod.utils import testing
from pydantic import ValidationError

from canvod.auxiliary.position import (
    ECEFPosition,
    GeodeticPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)


class TestECEFPositionGuardRail:
    """Regression tests for #111: reject implausible receiver positions.

    A zeroed/unpopulated RINEX ``APPROX POSITION XYZ`` header used to be
    silently accepted as (0, 0, 0) -- the Earth's center -- and passed on
    as the receiver position, corrupting every downstream satellite
    geometry computation without any error or warning.
    """

    def test_rejects_exact_origin(self):
        """(0, 0, 0) is never a valid ECEF point, receiver or otherwise."""
        with pytest.raises(ValidationError, match="Earth's center"):
            ECEFPosition(x=0.0, y=0.0, z=0.0)

    def test_rejects_nan_component(self):
        with pytest.raises(ValidationError, match="finite"):
            ECEFPosition(x=float("nan"), y=testing.ECEF_Y, z=testing.ECEF_Z)

    def test_rejects_inf_component(self):
        with pytest.raises(ValidationError, match="finite"):
            ECEFPosition(x=testing.ECEF_X, y=float("inf"), z=testing.ECEF_Z)

    def test_accepts_plausible_ground_station(self):
        """A real ground-station position must still construct cleanly."""
        pos = ECEFPosition(x=testing.ECEF_X, y=testing.ECEF_Y, z=testing.ECEF_Z)
        assert pos.x == testing.ECEF_X

    def test_satellite_range_positions_still_construct(self):
        """ECEFPosition itself stays general-purpose (satellite ranges too).

        Only from_ds_metadata() (the receiver-position parse boundary)
        enforces the tighter ground-station magnitude band -- bare
        ECEFPosition construction must keep accepting LEO-range points,
        since it's also used to represent satellite positions elsewhere
        (e.g. test_position_properties.py's Hypothesis strategies).
        """
        pos = ECEFPosition(x=2.5e7, y=5e6, z=1.5e7)
        assert pos.x == 2.5e7

    def test_from_ds_metadata_rejects_zeroed_header(self, sample_rinex_data):
        """The real-world failure mode: an unpopulated RINEX header."""
        corrupted = sample_rinex_data.copy()
        corrupted.attrs["APPROX POSITION X"] = 0.0
        corrupted.attrs["APPROX POSITION Y"] = 0.0
        corrupted.attrs["APPROX POSITION Z"] = 0.0

        with pytest.raises(ValidationError, match="Earth's center"):
            ECEFPosition.from_ds_metadata(corrupted)

    def test_from_ds_metadata_rejects_implausible_but_finite_position(
        self, sample_rinex_data
    ):
        """Finite, non-zero, but nowhere near a ground station -- e.g. a
        unit/scale mixup (km written where m was expected)."""
        corrupted = sample_rinex_data.copy()
        corrupted.attrs["APPROX POSITION X"] = 4075.5398
        corrupted.attrs["APPROX POSITION Y"] = 931.7353
        corrupted.attrs["APPROX POSITION Z"] = 4801.6296

        with pytest.raises(ValueError, match="plausible ECEF range"):
            ECEFPosition.from_ds_metadata(corrupted)

    def test_from_ds_metadata_accepts_real_position(self, sample_rinex_data):
        """Sanity check: the real, correct fixture position still passes."""
        pos = ECEFPosition.from_ds_metadata(sample_rinex_data)
        assert pos.x == testing.ECEF_X

    def test_alternative_format_rejects_zeroed_position(self):
        """The 'Approximate Position' string-format branch gets the same
        guard rail as the standard 'APPROX POSITION X/Y/Z' branch."""
        ds = xr.Dataset(
            attrs={"Approximate Position": "(X = 0.0 m, Y = 0.0 m, Z = 0.0 m)"}
        )
        with pytest.raises(ValidationError, match="Earth's center"):
            ECEFPosition.from_ds_metadata(ds)


class TestECEFPosition:
    """Test ECEFPosition class."""

    def test_initialization(self):
        """Test ECEF position can be created."""
        pos = ECEFPosition(x=testing.ECEF_X, y=testing.ECEF_Y, z=testing.ECEF_Z)

        assert pos.x == testing.ECEF_X
        assert pos.y == testing.ECEF_Y
        assert pos.z == testing.ECEF_Z

    def test_from_ds_metadata(self, sample_rinex_data):
        """Test creating ECEF from RINEX metadata."""
        pos = ECEFPosition.from_ds_metadata(sample_rinex_data)

        assert pos.x == testing.ECEF_X
        assert pos.y == testing.ECEF_Y
        assert pos.z == testing.ECEF_Z

    def test_to_geodetic_conversion(self, ecef_position):
        """Test ECEF to geodetic conversion."""
        lat, lon, alt = ecef_position.to_geodetic()

        # Expected: the geodetic position the ECEF constants were computed
        # from with PROJ (canvod.utils.testing)
        assert lat == pytest.approx(testing.LATITUDE, abs=1e-8)
        assert lon == pytest.approx(testing.LONGITUDE, abs=1e-8)
        assert alt == pytest.approx(testing.ALTITUDE_M, abs=1e-3)

    def test_roundtrip_ecef_geodetic(self):
        """Test ECEF → Geodetic → ECEF roundtrip."""
        original = ECEFPosition(x=testing.ECEF_X, y=testing.ECEF_Y, z=testing.ECEF_Z)

        # Convert to geodetic
        lat, lon, alt = original.to_geodetic()

        # Convert back to ECEF
        geo = GeodeticPosition(lat=lat, lon=lon, alt=alt)
        ecef_back = geo.to_ecef()

        # Should match within mm
        np.testing.assert_almost_equal(ecef_back.x, original.x, decimal=2)
        np.testing.assert_almost_equal(ecef_back.y, original.y, decimal=2)
        np.testing.assert_almost_equal(ecef_back.z, original.z, decimal=2)

    def test_attribute_access(self, ecef_position):
        """Test direct attribute access."""
        assert ecef_position.x == testing.ECEF_X
        assert ecef_position.y == testing.ECEF_Y
        assert ecef_position.z == testing.ECEF_Z

    def test_repr(self, ecef_position):
        """Test string representation."""
        repr_str = repr(ecef_position)

        assert "ECEFPosition" in repr_str
        assert f"{testing.ECEF_X:.3f}" in repr_str


class TestGeodeticPosition:
    """Test GeodeticPosition class."""

    def test_initialization(self):
        """Test geodetic position can be created."""
        pos = GeodeticPosition(
            lat=testing.LATITUDE, lon=testing.LONGITUDE, alt=testing.ALTITUDE_M
        )

        assert pos.lat == testing.LATITUDE
        assert pos.lon == testing.LONGITUDE
        assert pos.alt == testing.ALTITUDE_M

    def test_to_ecef_conversion(self, geodetic_position):
        """Test geodetic to ECEF conversion."""
        ecef = geodetic_position.to_ecef()

        # Expected: the ECEF position PROJ gives (canvod.utils.testing),
        # rounded to the millimeter there
        assert ecef.x == pytest.approx(testing.ECEF_X, abs=1e-3)
        assert ecef.y == pytest.approx(testing.ECEF_Y, abs=1e-3)
        assert ecef.z == pytest.approx(testing.ECEF_Z, abs=1e-3)

    def test_roundtrip_geodetic_ecef(self):
        """Test Geodetic → ECEF → Geodetic roundtrip."""
        original = GeodeticPosition(
            lat=testing.LATITUDE, lon=testing.LONGITUDE, alt=testing.ALTITUDE_M
        )

        # Convert to ECEF
        ecef = original.to_ecef()

        # Convert back to geodetic
        lat, lon, alt = ecef.to_geodetic()

        # Should match within reasonable precision
        np.testing.assert_almost_equal(lat, original.lat, decimal=5)
        np.testing.assert_almost_equal(lon, original.lon, decimal=5)
        np.testing.assert_almost_equal(alt, original.alt, decimal=1)

    def test_attribute_access(self, geodetic_position):
        """Test direct attribute access."""
        assert geodetic_position.lat == testing.LATITUDE
        assert geodetic_position.lon == testing.LONGITUDE
        assert geodetic_position.alt == testing.ALTITUDE_M

    def test_repr(self, geodetic_position):
        """Test string representation."""
        repr_str = repr(geodetic_position)

        assert "GeodeticPosition" in repr_str
        assert f"{testing.LATITUDE:.6f}" in repr_str


class TestComputeSphericalCoordinates:
    """Test compute_spherical_coordinates function."""

    def test_zenith_satellite(self, ecef_position):
        """Test satellite directly overhead (zenith)."""
        # Convert receiver to geodetic to get proper up direction
        lat, lon, alt = ecef_position.to_geodetic()

        # Place satellite far above receiver along local vertical.
        # Go way up in ECEF (not perfectly vertical but high enough).
        sat_x = ecef_position.x * 1.5
        sat_y = ecef_position.y * 1.5
        sat_z = ecef_position.z * 1.5

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        # r should be positive
        assert r > 0

        # theta should be relatively small (closer to zenith than horizon)
        assert theta < np.pi / 2  # Less than 90 degrees

    def test_horizon_satellite(self, ecef_position):
        """Test satellite at low elevation."""
        # Place satellite at similar distance but perpendicular to radial
        sat_x = ecef_position.x + 10e6
        sat_y = ecef_position.y + 10e6
        sat_z = ecef_position.z - 5e6

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        # Should have positive range
        assert r > 0

        # theta in valid range
        assert 0 <= theta <= np.pi

    def test_ranges_valid(self, ecef_position):
        """Test output ranges are physically valid."""
        # Random satellite position
        sat_x = 25e6
        sat_y = 5e6
        sat_z = 15e6

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        # r should be positive
        assert r > 0

        # theta should be [0, π]
        assert 0 <= theta <= np.pi

        # phi should be [0, 2π)
        assert 0 <= phi < 2 * np.pi

    def test_array_input(self, ecef_position):
        """Test arrays of satellite positions."""
        sat_x = np.array([25e6, 26e6, 27e6])
        sat_y = np.array([5e6, 5.1e6, 5.2e6])
        sat_z = np.array([15e6, 15.1e6, 15.2e6])

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        assert r.shape == (3,)
        assert theta.shape == (3,)
        assert phi.shape == (3,)

    def test_multidimensional_input(self, ecef_position):
        """Test multi-dimensional arrays (epoch × sid)."""
        sat_x = np.random.uniform(20e6, 30e6, size=(10, 5))
        sat_y = np.random.uniform(1e6, 5e6, size=(10, 5))
        sat_z = np.random.uniform(10e6, 20e6, size=(10, 5))

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        assert r.shape == (10, 5)
        assert theta.shape == (10, 5)
        assert phi.shape == (10, 5)

    def test_geodetic_position_input(self, geodetic_position):
        """Test using GeodeticPosition as receiver."""
        # Convert to ECEF (compute_spherical_coordinates expects ECEF)
        ecef_pos = geodetic_position.to_ecef()

        sat_x = 25e6
        sat_y = 5e6
        sat_z = 15e6

        r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, ecef_pos)

        assert r > 0
        assert 0 <= theta <= np.pi
        assert 0 <= phi < 2 * np.pi

    def test_physics_convention_azimuth(self, ecef_position):
        """Test azimuthal angle follows physics convention."""
        # Satellite at different position
        sat_x = ecef_position.x + 1e6
        sat_y = ecef_position.y + 1e6
        sat_z = ecef_position.z + 1e6

        _, _, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, ecef_position)

        # phi should be in valid range
        assert 0 <= phi < 2 * np.pi


class TestAddSphericalCoordsToDataset:
    """Test add_spherical_coords_to_dataset function."""

    def test_coords_added_to_dataset(self, sample_rinex_data):
        """Test spherical coordinates are added to dataset."""
        # Generate dummy spherical coordinates
        r = np.random.uniform(2e7, 3e7, size=sample_rinex_data["SNR"].shape)
        theta = np.random.uniform(0, np.pi, size=sample_rinex_data["SNR"].shape)
        phi = np.random.uniform(0, 2 * np.pi, size=sample_rinex_data["SNR"].shape)

        result = add_spherical_coords_to_dataset(sample_rinex_data, r, theta, phi)

        assert "r" in result.data_vars
        assert "theta" in result.data_vars
        assert "phi" in result.data_vars

    def test_original_data_preserved(self, sample_rinex_data):
        """Test original data variables are preserved."""
        r = np.random.uniform(2e7, 3e7, size=sample_rinex_data["SNR"].shape)
        theta = np.random.uniform(0, np.pi, size=sample_rinex_data["SNR"].shape)
        phi = np.random.uniform(0, 2 * np.pi, size=sample_rinex_data["SNR"].shape)

        result = add_spherical_coords_to_dataset(sample_rinex_data, r, theta, phi)

        # Original data should still exist
        assert "SNR" in result.data_vars
        np.testing.assert_array_equal(
            result["SNR"].values, sample_rinex_data["SNR"].values
        )

    def test_shapes_match(self, sample_rinex_data):
        """Test added coordinates have correct shapes."""
        r = np.random.uniform(2e7, 3e7, size=sample_rinex_data["SNR"].shape)
        theta = np.random.uniform(0, np.pi, size=sample_rinex_data["SNR"].shape)
        phi = np.random.uniform(0, 2 * np.pi, size=sample_rinex_data["SNR"].shape)

        result = add_spherical_coords_to_dataset(sample_rinex_data, r, theta, phi)

        assert result["r"].shape == sample_rinex_data["SNR"].shape
        assert result["theta"].shape == sample_rinex_data["SNR"].shape
        assert result["phi"].shape == sample_rinex_data["SNR"].shape

    def test_attributes_set(self, sample_rinex_data):
        """Test coordinate attributes are set correctly."""
        r = np.random.uniform(2e7, 3e7, size=sample_rinex_data["SNR"].shape)
        theta = np.random.uniform(0, np.pi, size=sample_rinex_data["SNR"].shape)
        phi = np.random.uniform(0, 2 * np.pi, size=sample_rinex_data["SNR"].shape)

        result = add_spherical_coords_to_dataset(sample_rinex_data, r, theta, phi)

        # Check units exist
        assert "units" in result["r"].attrs
        assert "units" in result["theta"].attrs
        assert "units" in result["phi"].attrs


class TestCoordinateTransformationIntegration:
    """Integration tests for complete coordinate transformation workflow."""

    def test_complete_augmentation_workflow(self, sample_rinex_data, ecef_position):
        """Test complete workflow from satellite ECEF to augmented RINEX."""
        # Step 1: Simulate satellite positions
        sat_x = np.random.uniform(20e6, 30e6, size=sample_rinex_data["SNR"].shape)
        sat_y = np.random.uniform(1e6, 5e6, size=sample_rinex_data["SNR"].shape)
        sat_z = np.random.uniform(10e6, 20e6, size=sample_rinex_data["SNR"].shape)

        # Step 2: Compute spherical coordinates
        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        # Step 3: Add to dataset
        augmented = add_spherical_coords_to_dataset(sample_rinex_data, r, theta, phi)

        # Verify complete
        assert "SNR" in augmented.data_vars  # Original
        assert "r" in augmented.data_vars  # Added
        assert "theta" in augmented.data_vars
        assert "phi" in augmented.data_vars

    def test_physical_validity(self, ecef_position):
        """Test physically valid transformations."""
        # A GPS satellite above the site: on the line from the geocenter
        # through the receiver, at the GPS reference orbit radius
        # (A_REF = 26,559,710 m, IS-GPS-200).
        receiver = np.array([ecef_position.x, ecef_position.y, ecef_position.z])
        receiver_radius = np.linalg.norm(receiver)
        sat_x, sat_y, sat_z = receiver * (26_559_710.0 / receiver_radius)

        r, theta, phi = compute_spherical_coordinates(
            sat_x, sat_y, sat_z, ecef_position
        )

        # GPS orbit altitude ~20,200 km above Earth surface
        assert 15e6 < r < 30e6  # 15,000 - 30,000 km range
        assert r == pytest.approx(26_559_710.0 - receiver_radius, abs=1e-3)

        # Should not be below horizon (theta > π/2 would be underground)
        assert 0 <= theta <= np.pi

    def test_coordinate_system_consistency(self, geodetic_position):
        """Test consistency between ECEF and geodetic as receiver."""
        # Same satellite, different receiver representations
        sat_x = 25e6
        sat_y = 5e6
        sat_z = 15e6

        # Convert geodetic to ECEF
        ecef = geodetic_position.to_ecef()

        # Compute with ECEF representation
        r1, theta1, phi1 = compute_spherical_coordinates(sat_x, sat_y, sat_z, ecef)

        # Should get valid results
        assert r1 > 0
        assert 0 <= theta1 <= np.pi
        assert 0 <= phi1 < 2 * np.pi
