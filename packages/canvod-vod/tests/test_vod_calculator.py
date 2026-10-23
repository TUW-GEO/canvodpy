"""Comprehensive tests for VOD calculation."""

import unittest.mock

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError

from canvod.vod import TauOmegaZerothOrder
from canvod.vod.calculator import DELTA_SNR_ATTRS, VOD_ATTRS


class TestVODCalculatorValidation:
    """Test dataset validation."""

    def test_valid_datasets(self):
        """Test that valid datasets pass validation."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.random.randn(10, 5)),
                "phi": (["epoch", "sid"], np.random.rand(10, 5) * 2 * np.pi),
                "theta": (["epoch", "sid"], np.random.rand(10, 5) * np.pi / 2),
            }
        )
        sky_ds = canopy_ds.copy()

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        assert calculator.canopy_ds is not None
        assert calculator.sky_ds is not None

    def test_missing_snr_canopy(self):
        """Test that missing SNR in canopy raises error."""
        canopy_ds = xr.Dataset(
            {
                "phi": (["epoch", "sid"], np.random.rand(10, 5)),
                "theta": (["epoch", "sid"], np.random.rand(10, 5)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.random.randn(10, 5)),
            }
        )

        with pytest.raises(ValueError, match="must contain 'SNR'"):
            TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

    def test_missing_snr_sky(self):
        """Test that missing SNR in sky raises error."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.random.randn(10, 5)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "phi": (["epoch", "sid"], np.random.rand(10, 5)),
            }
        )

        with pytest.raises(ValueError, match="must contain 'SNR'"):
            TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

    def test_invalid_type_canopy(self):
        """Test that non-dataset canopy raises error."""
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.random.randn(10, 5)),
            }
        )

        with pytest.raises(
            ValidationError, match="Input should be an instance of Dataset"
        ):
            TauOmegaZerothOrder(canopy_ds="not a dataset", sky_ds=sky_ds)


class TestTauOmegaZerothOrder:
    """Test TauOmegaZerothOrder calculator."""

    def create_test_datasets(self, n_epoch=10, n_sid=5):
        """Create test datasets with known values."""
        # Create canopy dataset with higher SNR
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 20.0)),  # 20 dB
                "phi": (["epoch", "sid"], np.random.rand(n_epoch, n_sid) * 2 * np.pi),
                "theta": (
                    ["epoch", "sid"],
                    np.full((n_epoch, n_sid), np.pi / 4),
                ),  # 45°
            }
        )

        # Create sky dataset with lower SNR
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 10.0)),  # 10 dB
                "phi": (["epoch", "sid"], canopy_ds["phi"].values),
                "theta": (["epoch", "sid"], canopy_ds["theta"].values),
            }
        )

        return canopy_ds, sky_ds

    def test_get_delta_snr(self):
        """Test delta SNR calculation."""
        canopy_ds, sky_ds = self.create_test_datasets()
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        delta_snr = calculator.get_delta_snr()

        # delta_snr should be 20 - 10 = 10 dB everywhere
        assert np.allclose(delta_snr.values, 10.0)
        assert delta_snr.shape == canopy_ds["SNR"].shape

    def test_decibel2linear(self):
        """Test decibel to linear conversion."""
        canopy_ds, sky_ds = self.create_test_datasets()
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        # Test known conversion: 10 dB = 10^(10/10) = 10
        delta_snr = xr.DataArray(np.array([10.0, 20.0, 30.0]))
        linear = calculator.decibel2linear(delta_snr)

        expected = np.array([10.0, 100.0, 1000.0])
        assert np.allclose(linear.values, expected)

    def test_calculate_vod_shape(self):
        """Test that VOD output has correct shape."""
        canopy_ds, sky_ds = self.create_test_datasets(n_epoch=20, n_sid=8)
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        vod_ds = calculator.calculate_vod()

        assert "VOD" in vod_ds.data_vars
        assert vod_ds["VOD"].shape == (20, 8)

    def test_calculate_vod_keeps_cell_ids(self):
        """Grid cells assigned before the store write reach the VOD."""
        canopy_ds, sky_ds = self.create_test_datasets(n_epoch=20, n_sid=8)
        cells = np.arange(160.0).reshape(20, 8)
        canopy_ds["cell_id_equal_area_2.0deg"] = (("epoch", "sid"), cells)
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        vod_ds = calculator.calculate_vod()

        np.testing.assert_array_equal(vod_ds["cell_id_equal_area_2.0deg"].values, cells)

    def test_calculate_vod_describes_its_variables(self):
        """VOD and delta_snr carry their own attributes, none of the inputs'."""
        canopy_ds, sky_ds = self.create_test_datasets()
        for ds in (canopy_ds, sky_ds):
            ds["SNR"].attrs = {"long_name": "SNR", "units": "dB-Hz"}
            ds["theta"].attrs = {"long_name": "Polar angle", "valid_range": [0, 1.6]}
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        vod_ds = calculator.calculate_vod()

        assert vod_ds["VOD"].attrs == VOD_ATTRS
        assert vod_ds["delta_snr"].attrs == DELTA_SNR_ATTRS
        assert vod_ds["VOD"].attrs["coverage_content_type"] == "modelResult"

    def test_calculate_vod_coords(self):
        """Test that VOD output preserves coordinates."""
        canopy_ds, sky_ds = self.create_test_datasets()
        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        vod_ds = calculator.calculate_vod()

        assert "phi" in vod_ds.data_vars
        assert "theta" in vod_ds.data_vars
        assert np.allclose(vod_ds["phi"].values, canopy_ds["phi"].values)
        assert np.allclose(vod_ds["theta"].values, canopy_ds["theta"].values)

    def test_calculate_vod_values(self):
        """Test VOD calculation with known values."""
        # Create datasets with specific values for testing
        n_epoch, n_sid = 5, 3

        # Canopy has LOWER SNR than sky (attenuation through vegetation)
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )

        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        vod_ds = calculator.calculate_vod()

        # Manual calculation:
        # delta_snr = 10 - 20 = -10 dB
        # gamma = 10^(-10/10) = 10^(-1) = 0.1
        # VOD = -ln(0.1) * cos(π/4) = 2.303 * 0.707 ≈ 1.628

        expected_vod = -np.log(0.1) * np.cos(np.pi / 4)
        assert np.allclose(vod_ds["VOD"].values, expected_vod, rtol=0.01)
        assert np.all(vod_ds["VOD"].values > 0)  # VOD should be positive

    def test_calculate_vod_all_nan(self):
        """Test that all NaN delta_snr raises error."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), np.nan)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.zeros((10, 5))),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), np.nan)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.zeros((10, 5))),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)

        with pytest.raises(ValueError, match="All delta_snr values are NaN"):
            calculator.calculate_vod()

    def test_calculate_vod_all_nan_lazy(self):
        """All-NaN delta_snr also raises for dask-backed (store-read) inputs."""
        ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), np.nan)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.zeros((10, 5))),
            }
        ).chunk({"epoch": 5})

        calculator = TauOmegaZerothOrder(canopy_ds=ds, sky_ds=ds.copy())

        with pytest.raises(ValueError, match="All delta_snr values are NaN"):
            calculator.calculate_vod()

    def test_calculate_vod_lazy_result_stays_lazy(self):
        """The input checks do not compute the VOD result itself."""
        ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), 40.0)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.full((10, 5), np.pi / 4)),
            }
        ).chunk({"epoch": 5})
        sky = ds.copy()
        sky["SNR"] = sky["SNR"] + 3.0

        vod_ds = TauOmegaZerothOrder(canopy_ds=ds, sky_ds=sky).calculate_vod()

        assert vod_ds["VOD"].chunks is not None
        assert np.isfinite(vod_ds["VOD"].values).all()

    def test_calculate_vod_negative_transmissivity_warning(self):
        """Test warning when transmissivity <= 0."""
        n_epoch, n_sid = 5, 3
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )

        original_d2l = TauOmegaZerothOrder.decibel2linear

        def mock_d2l(self_arg, delta_snr_db):
            result = original_d2l(self_arg, delta_snr_db)
            # Inject some non-positive values
            result.values[0, 0] = 0.0
            result.values[0, 1] = -0.5
            return result

        with (
            unittest.mock.patch.object(TauOmegaZerothOrder, "decibel2linear", mock_d2l),
            unittest.mock.patch("canvod.vod.calculator.log") as mock_log,
        ):
            calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
            calculator.calculate_vod()

        mock_log.warning.assert_called_once_with(
            "invalid_transmissivity",
            invalid_count=unittest.mock.ANY,
            total_count=unittest.mock.ANY,
            percent=unittest.mock.ANY,
        )

    def test_calculate_vod_zero_delta_snr(self):
        """Test VOD is exactly 0 when canopy_SNR == sky_SNR (delta_snr = 0)."""
        n_epoch, n_sid = 5, 3
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 15.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((n_epoch, n_sid), 15.0)),
                "phi": (["epoch", "sid"], np.zeros((n_epoch, n_sid))),
                "theta": (["epoch", "sid"], np.full((n_epoch, n_sid), np.pi / 4)),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        vod_ds = calculator.calculate_vod()

        # delta_snr = 0, transmissivity = 10^0 = 1, VOD = -ln(1) * cos(theta) = 0
        assert np.allclose(vod_ds["VOD"].values, 0.0, atol=1e-15)

    def test_from_icechunkstore_import_error(self):
        """Test ImportError with helpful message when canvod-store not installed."""
        with unittest.mock.patch.dict("sys.modules", {"canvod.store": None}):
            with (
                pytest.warns(FutureWarning, match="compute_bulk"),
                pytest.raises(ImportError, match="canvod-store"),
            ):
                TauOmegaZerothOrder.from_icechunkstore(
                    "/fake/path", "canopy_01", "reference_01_canopy_01"
                )

    def test_from_icechunkstore_requires_groups(self):
        """No default groups: the old sky_group default named no stored group."""
        with (
            pytest.warns(FutureWarning, match="compute_bulk"),
            pytest.raises(TypeError, match="sky_group"),
        ):
            TauOmegaZerothOrder.from_icechunkstore("/fake/path", "canopy_01")


class TestFromDatasets:
    """Test from_datasets classmethod."""

    def test_from_datasets_align_argument_deprecated(self):
        """The ignored ``align`` argument warns."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.full((10, 5), np.pi / 4)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.full((10, 5), np.pi / 4)),
            }
        )

        with pytest.warns(FutureWarning, match="next major version"):
            vod_ds = TauOmegaZerothOrder.from_datasets(
                canopy_ds=canopy_ds, sky_ds=sky_ds, align=False
            )

        assert isinstance(vod_ds, xr.Dataset)
        assert "VOD" in vod_ds.data_vars

    def test_from_datasets_with_align(self):
        """Test from_datasets with alignment."""
        # Create datasets with different coordinates
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.full((10, 5), np.pi / 4)),
            },
            coords={"epoch": range(10), "sid": range(5)},
        )

        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((12, 6), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((12, 6))),
                "theta": (["epoch", "sid"], np.full((12, 6), np.pi / 4)),
            },
            coords={"epoch": range(2, 14), "sid": range(1, 7)},
        )

        vod_ds = TauOmegaZerothOrder.from_datasets(canopy_ds=canopy_ds, sky_ds=sky_ds)

        assert isinstance(vod_ds, xr.Dataset)
        assert "VOD" in vod_ds.data_vars
        # After inner join: epochs 2-9 (8 epochs), sids 1-4 (4 sids)
        assert vod_ds["VOD"].shape == (8, 4)

    def test_constructor_aligns(self):
        """Direct construction (as VODFactory does) aligns too.

        Without it the output kept every canopy epoch and signal, with NaN
        VOD where the reference had no data.
        """
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((10, 5), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((10, 5))),
                "theta": (["epoch", "sid"], np.full((10, 5), np.pi / 4)),
            },
            coords={"epoch": range(10), "sid": range(5)},
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((12, 6), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((12, 6))),
                "theta": (["epoch", "sid"], np.full((12, 6), np.pi / 4)),
            },
            coords={"epoch": range(2, 14), "sid": range(1, 7)},
        )

        vod_ds = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds).calculate_vod()

        assert dict(vod_ds.sizes) == {"epoch": 8, "sid": 4}
        assert not vod_ds["VOD"].isnull().any()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_theta(self):
        """Test VOD calculation with theta = 0 (zenith)."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((5, 3), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((5, 3))),
                "theta": (["epoch", "sid"], np.zeros((5, 3))),  # Zenith
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((5, 3), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((5, 3))),
                "theta": (["epoch", "sid"], np.zeros((5, 3))),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        vod_ds = calculator.calculate_vod()

        # At zenith: cos(0) = 1, so VOD = -ln(gamma) * 1
        # With gamma = 0.1: VOD = -ln(0.1) ≈ 2.303
        assert np.all(np.isfinite(vod_ds["VOD"].values))

    def test_horizon_theta(self):
        """Test VOD calculation with theta = π/2 (horizon)."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((5, 3), 10.0)),
                "phi": (["epoch", "sid"], np.zeros((5, 3))),
                "theta": (["epoch", "sid"], np.full((5, 3), np.pi / 2)),  # Horizon
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (["epoch", "sid"], np.full((5, 3), 20.0)),
                "phi": (["epoch", "sid"], np.zeros((5, 3))),
                "theta": (["epoch", "sid"], np.full((5, 3), np.pi / 2)),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        vod_ds = calculator.calculate_vod()

        # At horizon: cos(π/2) = 0, so VOD = -ln(gamma) * 0 = 0
        assert np.allclose(vod_ds["VOD"].values, 0.0, atol=1e-10)

    def test_mixed_valid_invalid(self):
        """Test with mix of valid and NaN values."""
        canopy_ds = xr.Dataset(
            {
                "SNR": (
                    ["epoch", "sid"],
                    [[10, 20, np.nan], [15, np.nan, 25], [np.nan, 18, 22]],
                ),
                "phi": (["epoch", "sid"], np.zeros((3, 3))),
                "theta": (["epoch", "sid"], np.full((3, 3), np.pi / 4)),
            }
        )
        sky_ds = xr.Dataset(
            {
                "SNR": (
                    ["epoch", "sid"],
                    [[20, 30, np.nan], [25, np.nan, 35], [np.nan, 28, 32]],
                ),
                "phi": (["epoch", "sid"], np.zeros((3, 3))),
                "theta": (["epoch", "sid"], np.full((3, 3), np.pi / 4)),
            }
        )

        calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
        vod_ds = calculator.calculate_vod()

        # Valid values should be finite
        valid_mask = ~np.isnan(canopy_ds["SNR"].values) & ~np.isnan(
            sky_ds["SNR"].values
        )
        assert np.all(np.isfinite(vod_ds["VOD"].values[valid_mask]))

        # NaN values should propagate
        invalid_mask = np.isnan(canopy_ds["SNR"].values) | np.isnan(
            sky_ds["SNR"].values
        )
        assert np.all(np.isnan(vod_ds["VOD"].values[invalid_mask]))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
