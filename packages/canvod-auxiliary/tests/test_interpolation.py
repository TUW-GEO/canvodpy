"""Tests for interpolation strategies."""

import numpy as np
import xarray as xr

from canvod.auxiliary.interpolation import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
)
from canvod.auxiliary.interpolation.interpolator import _detect_jumps


class TestSp3Config:
    """Test Sp3Config dataclass."""

    def test_records_the_method(self):
        """The record in the aux store names the method and its epochs."""
        assert Sp3Config().to_dict() == {"method": "lagrange", "points": 11}


class TestClockConfig:
    """Test ClockConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = ClockConfig()

        assert config.window_size == 9
        assert config.jump_threshold == 1e-6

    def test_custom_config(self):
        """Test custom configuration."""
        config = ClockConfig(window_size=5, jump_threshold=1e-7)

        assert config.window_size == 5
        assert config.jump_threshold == 1e-7


class TestSp3InterpolationStrategy:
    """Test Sp3InterpolationStrategy class."""

    def test_initialization(self):
        """Test strategy can be initialized."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        assert strategy is not None
        assert strategy.config == config

    def test_interpolate_increases_epochs(self, sample_preprocessed_sp3):
        """Test interpolation increases number of epochs."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        # Create target epochs (more than input)
        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")

        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["epoch"] == 288
        assert result.sizes["epoch"] > sample_preprocessed_sp3.sizes["epoch"]

    def test_interpolate_preserves_sid(self, sample_preprocessed_sp3):
        """Test interpolation preserves sid dimension."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["sid"] == sample_preprocessed_sp3.sizes["sid"]

    def test_interpolate_all_variables(self, sample_preprocessed_sp3):
        """Test all position variables are interpolated."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert "X" in result.data_vars
        assert "Y" in result.data_vars
        assert "Z" in result.data_vars

    def test_interpolated_values_reasonable(self):
        """Interpolated positions of a circular orbit stay on its radius."""
        t = np.arange(0.0, 86_400.0 + 1, 900.0)
        epochs = np.datetime64("2024-01-01T00:00:00") + (t * 1e9).astype(
            "timedelta64[ns]"
        )
        pos = _circular_orbit(t)
        ds = xr.Dataset(
            {c: (("epoch", "sv"), pos[:, k : k + 1]) for k, c in enumerate("XYZ")},
            coords={"epoch": epochs, "sv": ["G01"]},
        )
        target_epochs = epochs[0] + np.arange(288) * np.timedelta64(5, "m")

        result = Sp3InterpolationStrategy(config=Sp3Config()).interpolate(
            ds, target_epochs
        )

        radius = np.sqrt(sum(result[c].values[:, 0] ** 2 for c in "XYZ"))
        np.testing.assert_allclose(radius, 26_560e3, atol=1.0)

    def test_with_velocities(self):
        """Test interpolation using velocities."""
        # Create dataset with velocities
        base_time = np.datetime64("2024-01-01T00:00:00")
        epochs = base_time + np.arange(10) * np.timedelta64(15, "m")
        sids = ["G01|L1|C", "G02|L2|W"]

        ds = xr.Dataset(
            {
                "X": (["epoch", "sid"], np.random.uniform(2e7, 3e7, (10, 2))),
                "Y": (["epoch", "sid"], np.random.uniform(1e6, 5e6, (10, 2))),
                "Z": (["epoch", "sid"], np.random.uniform(1e7, 2e7, (10, 2))),
                "VX": (["epoch", "sid"], np.random.uniform(-3000, 3000, (10, 2))),
                "VY": (["epoch", "sid"], np.random.uniform(-3000, 3000, (10, 2))),
                "VZ": (["epoch", "sid"], np.random.uniform(-3000, 3000, (10, 2))),
            },
            coords={"epoch": epochs, "sid": sids},
        )

        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        target_base = np.datetime64("2024-01-01T00:00:00")
        target_epochs = target_base + np.arange(30) * np.timedelta64(5, "m")
        result = strategy.interpolate(ds, target_epochs)

        assert result.sizes["epoch"] == 30


class TestClockInterpolationStrategy:
    """Test ClockInterpolationStrategy class."""

    def test_initialization(self):
        """Test strategy can be initialized."""
        config = ClockConfig()
        strategy = ClockInterpolationStrategy(config=config)

        assert strategy is not None
        assert strategy.config == config

    def test_interpolate_clock_data(self, sample_clk_data):
        """Test interpolation of clock data."""
        # Preprocess first
        from canvod.auxiliary import preprocess_aux_for_interpolation

        clk_preprocessed = preprocess_aux_for_interpolation(sample_clk_data)

        config = ClockConfig()
        strategy = ClockInterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(2880) * np.timedelta64(30, "s")
        result = strategy.interpolate(clk_preprocessed, target_epochs)

        assert result.sizes["epoch"] == 2880
        assert "clock_bias" in result.data_vars

    def test_handles_discontinuities(self):
        """Test handling of clock discontinuities."""
        # Create data with intentional jump
        base_time = np.datetime64("2024-01-01T00:00:00")
        epochs = base_time + np.arange(20) * np.timedelta64(5, "m")
        sids = ["G01|L1|C"]

        clock_bias = np.zeros(20)
        clock_bias[10:] = 1e-6  # Jump at epoch 10

        ds = xr.Dataset(
            {"clock_bias": (["epoch", "sid"], clock_bias.reshape(-1, 1))},
            coords={"epoch": epochs, "sid": sids},
        )

        config = ClockConfig(jump_threshold=5e-7)
        strategy = ClockInterpolationStrategy(config=config)

        target_base = np.datetime64("2024-01-01T00:00:00")
        target_epochs = target_base + np.arange(60) * np.timedelta64(2, "m")
        result = strategy.interpolate(ds, target_epochs)

        # Should handle discontinuity without crashing
        assert result.sizes["epoch"] == 60

        # The jump occurs between source epoch 9 (t=45min) and 10 (t=50min).
        # Target epochs near the boundary should either be NaN (interpolator
        # avoids interpolating across the jump) or should NOT smoothly
        # bridge the two segments.
        clock_vals = result["clock_bias"].sel(sid="G01|L1|C").values

        # Before the jump (target epochs at t<45min): should be ~0
        pre_jump = clock_vals[:22]  # 0..44min
        valid_pre = pre_jump[~np.isnan(pre_jump)]
        if len(valid_pre) > 0:
            assert np.allclose(valid_pre, 0.0, atol=1e-8)

        # After the jump (target epochs at t>50min): should be ~1e-6
        post_jump = clock_vals[26:]  # 52..118min
        valid_post = post_jump[~np.isnan(post_jump)]
        if len(valid_post) > 0:
            assert np.allclose(valid_post, 1e-6, atol=1e-8)

    def test_interpolated_values_bounded(self):
        """Test interpolated clock values stay within reasonable bounds."""
        base_time = np.datetime64("2024-01-01T00:00:00")
        epochs = base_time + np.arange(10) * np.timedelta64(5, "m")
        sids = ["G01|L1|C"]

        clock_bias = np.random.uniform(-1e-6, 1e-6, (10, 1))

        ds = xr.Dataset(
            {"clock_bias": (["epoch", "sid"], clock_bias)},
            coords={"epoch": epochs, "sid": sids},
        )

        config = ClockConfig()
        strategy = ClockInterpolationStrategy(config=config)

        target_base = np.datetime64("2024-01-01T00:00:00")
        target_epochs = target_base + np.arange(30) * np.timedelta64(2, "m")
        result = strategy.interpolate(ds, target_epochs)

        # Interpolated values shouldn't exceed input range significantly
        assert result["clock_bias"].min() >= -2e-6
        assert result["clock_bias"].max() <= 2e-6


class TestDetectJumps:
    """Test the windowed clock-jump detector (ClockConfig.window_size)."""

    def test_window_size_one_matches_raw_diff(self):
        """window_size<=1 must degenerate exactly to the pre-fix behavior."""
        rng = np.random.default_rng(0)
        data = rng.normal(scale=1e-7, size=50)
        data[30:] += 5e-6  # genuine sustained jump

        threshold = 1e-6
        expected = np.where(np.abs(np.diff(data)) > threshold)[0]
        actual = _detect_jumps(data, window_size=1, threshold=threshold)
        np.testing.assert_array_equal(actual, expected)

    def test_detects_genuine_sustained_jump(self):
        """A real, sustained step must still be found, precisely located."""
        data = np.zeros(20)
        data[10:] = 1e-6

        jumps = _detect_jumps(data, window_size=9, threshold=5e-7)
        np.testing.assert_array_equal(jumps, [9])

    def test_windowed_reduces_false_positives_under_noise(self):
        """A windowed comparison must be far less prone to spurious splits
        from ordinary sample-to-sample noise than the raw two-point diff —
        this robustness is the entire point of ClockConfig.window_size.
        """
        threshold = 1e-6
        rng = np.random.default_rng(42)
        # No real jump anywhere — pure noise at ~0.6x the jump threshold.
        noise = rng.normal(scale=0.6 * threshold, size=200)

        raw_jumps = _detect_jumps(noise, window_size=1, threshold=threshold)
        windowed_jumps = _detect_jumps(noise, window_size=9, threshold=threshold)

        assert len(raw_jumps) > 10, (
            "expected the raw single-sample diff to be noise-triggered often"
        )
        assert len(windowed_jumps) <= 1, (
            "windowed detection should suppress almost all noise-only false positives"
        )

    def test_empty_and_single_sample_inputs(self):
        assert len(_detect_jumps(np.array([]), window_size=9, threshold=1e-6)) == 0
        assert len(_detect_jumps(np.array([1.0]), window_size=9, threshold=1e-6)) == 0


class TestInterpolationIntegration:
    """Integration tests for complete interpolation workflow."""

    def test_sp3_to_rinex_alignment(self, sample_preprocessed_sp3, sample_rinex_data):
        """Test SP3 can be interpolated to RINEX epochs."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        # Use RINEX epochs as target
        target_epochs = sample_rinex_data.epoch.values

        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        # Should match RINEX epoch count
        assert result.sizes["epoch"] == sample_rinex_data.sizes["epoch"]

    def test_preprocessing_then_interpolation(self, sample_sp3_data):
        """Test complete workflow: preprocess → interpolate."""
        # Step 1: Preprocess
        from canvod.auxiliary import preprocess_aux_for_interpolation

        preprocessed = preprocess_aux_for_interpolation(sample_sp3_data)

        # Step 2: Interpolate
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        interpolated = strategy.interpolate(preprocessed, target_epochs)

        # Should work without errors
        assert interpolated.sizes["epoch"] == 288
        assert "sid" in interpolated.sizes

    def test_both_sp3_and_clock(self, sample_sp3_data, sample_clk_data):
        """Test interpolating both SP3 and CLK data."""
        from canvod.auxiliary import preprocess_aux_for_interpolation

        # Preprocess both
        sp3_prep = preprocess_aux_for_interpolation(sample_sp3_data)
        clk_prep = preprocess_aux_for_interpolation(sample_clk_data)

        # Interpolate both to same target epochs
        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(2880) * np.timedelta64(30, "s")

        sp3_config = Sp3Config()
        sp3_strategy = Sp3InterpolationStrategy(config=sp3_config)
        sp3_interp = sp3_strategy.interpolate(sp3_prep, target_epochs)

        clk_config = ClockConfig()
        clk_strategy = ClockInterpolationStrategy(config=clk_config)
        clk_interp = clk_strategy.interpolate(clk_prep, target_epochs)

        # Both should have same epoch count
        assert sp3_interp.sizes["epoch"] == clk_interp.sizes["epoch"]


class TestInterpolationEdgeCases:
    """Test edge cases and error handling."""

    def test_extrapolation_before_first_epoch(self, sample_preprocessed_sp3):
        """Test extrapolation before first epoch."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        # Target epochs before input data
        first_epoch = sample_preprocessed_sp3.epoch.values[0]
        target_epochs = first_epoch - np.arange(10, 0, -1) * np.timedelta64(15, "m")

        # Should handle without crashing
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)
        assert result.sizes["epoch"] == 10

    def test_extrapolation_after_last_epoch(self, sample_preprocessed_sp3):
        """Test extrapolation after last epoch."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        # Target epochs after input data
        last_epoch = sample_preprocessed_sp3.epoch.values[-1]
        target_epochs = last_epoch + np.arange(1, 11) * np.timedelta64(15, "m")

        # Should handle without crashing
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)
        assert result.sizes["epoch"] == 10

    def test_single_target_epoch(self, sample_preprocessed_sp3):
        """Test interpolation to single epoch."""
        config = Sp3Config()
        strategy = Sp3InterpolationStrategy(config=config)

        # Use middle epoch from input
        mid_epoch = sample_preprocessed_sp3.epoch.values[
            len(sample_preprocessed_sp3.epoch) // 2
        ]
        target_epochs = np.array([mid_epoch])

        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["epoch"] == 1


def _circular_orbit(t: np.ndarray, rate: bool = False) -> np.ndarray:
    """ECEF positions (m) of a circular orbit at GPS height, inclined 55°.

    With ``rate=True``, the velocities (m/s) instead, differentiated by hand.
    """
    radius, period, incl = 26_560e3, 43_082.0, np.radians(55.0)
    earth_rate = 7.2921151467e-5  # rad/s; turns the orbit into ECEF, as in SP3
    n = 2 * np.pi / period
    u, rot = n * t, earth_rate * t
    x, y = radius * np.cos(u), radius * np.cos(incl) * np.sin(u)
    z = radius * np.sin(incl) * np.sin(u)
    if not rate:
        return np.stack(
            [np.cos(rot) * x + np.sin(rot) * y, -np.sin(rot) * x + np.cos(rot) * y, z],
            axis=-1,
        )
    dx, dy = -n * radius * np.sin(u), n * radius * np.cos(incl) * np.cos(u)
    dz = n * radius * np.sin(incl) * np.cos(u)
    w = earth_rate
    return np.stack(
        [
            np.cos(rot) * dx
            + np.sin(rot) * dy
            - w * np.sin(rot) * x
            + w * np.cos(rot) * y,
            -np.sin(rot) * dx
            + np.cos(rot) * dy
            - w * np.cos(rot) * x
            - w * np.sin(rot) * y,
            dz,
        ],
        axis=-1,
    )


class TestSp3OrbitAccuracy:
    """Interpolated orbits between the epochs of a product (#563)."""

    @staticmethod
    def _orbit_dataset(step_s: float) -> xr.Dataset:
        t = np.arange(-3600.0, 86_400.0 + 3600.0 + 1, step_s)
        pos = _circular_orbit(t)
        epochs = np.datetime64("2025-01-01T00:00:00") + (t * 1e9).astype(
            "timedelta64[ns]"
        )
        return xr.Dataset(
            {c: (("epoch", "sv"), pos[:, k : k + 1]) for k, c in enumerate("XYZ")},
            coords={"epoch": epochs, "sv": ["G01"]},
        )

    def test_positions_between_15_minute_epochs(self):
        ds = self._orbit_dataset(900.0)
        t = np.arange(0.0, 86_400.0, 30.0)
        target = np.datetime64("2025-01-01T00:00:00") + (t * 1e9).astype(
            "timedelta64[ns]"
        )

        result = Sp3InterpolationStrategy(config=Sp3Config()).interpolate(ds, target)

        got = np.stack([result[c].values[:, 0] for c in "XYZ"], axis=-1)
        error = np.linalg.norm(got - _circular_orbit(t), axis=1)
        # The resolution of SP3 positions: km as F14.6, i.e. 1 mm (SP3-d,
        # Hilla 2016, p. 11, the Position and Clock Record)
        assert error.max() < 1e-3

    def test_velocities_are_the_derivative_of_the_orbit(self):
        ds = self._orbit_dataset(900.0)
        t = np.arange(0.0, 86_400.0, 30.0)
        target = np.datetime64("2025-01-01T00:00:00") + (t * 1e9).astype(
            "timedelta64[ns]"
        )

        result = Sp3InterpolationStrategy(config=Sp3Config()).interpolate(ds, target)

        got = np.stack([result[v].values[:, 0] for v in ("Vx", "Vy", "Vz")], axis=-1)
        assert np.abs(got - _circular_orbit(t, rate=True)).max() < 1e-5  # m/s

    def test_positions_at_the_epochs_are_the_product_values(self):
        ds = self._orbit_dataset(900.0)

        result = Sp3InterpolationStrategy(config=Sp3Config()).interpolate(
            ds, ds.epoch.values
        )

        np.testing.assert_allclose(result["X"].values, ds["X"].values, atol=1e-6)


class TestSp3ConfigDeprecatedArguments:
    def test_use_velocities_warns_and_changes_nothing(self):
        import pytest

        with pytest.warns(FutureWarning, match="use_velocities"):
            config = Sp3Config(use_velocities=False)
        assert config.to_dict() == Sp3Config().to_dict()

    def test_fallback_method_warns_and_changes_nothing(self):
        import pytest

        with pytest.warns(FutureWarning, match="fallback_method"):
            config = Sp3Config(fallback_method="nearest")
        assert config.to_dict() == Sp3Config().to_dict()
