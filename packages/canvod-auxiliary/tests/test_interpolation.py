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

    def test_default_config(self):
        """Test default configuration."""
        config = Sp3Config()

        assert config.use_velocities is True
        assert config.fallback_method == "linear"

    def test_custom_config(self):
        """Test custom configuration."""
        config = Sp3Config(use_velocities=False, fallback_method="cubic")

        assert config.use_velocities is False
        assert config.fallback_method == "cubic"

    def test_config_fields_accessible(self):
        """Test config fields are accessible."""
        config = Sp3Config(use_velocities=True, fallback_method="nearest")

        assert hasattr(config, "use_velocities")
        assert hasattr(config, "fallback_method")


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
        config = Sp3Config(use_velocities=False)  # Simpler test
        strategy = Sp3InterpolationStrategy(config=config)

        # Create target epochs (more than input)
        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")

        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["epoch"] == 288
        assert result.sizes["epoch"] > sample_preprocessed_sp3.sizes["epoch"]

    def test_interpolate_preserves_sid(self, sample_preprocessed_sp3):
        """Test interpolation preserves sid dimension."""
        config = Sp3Config(use_velocities=False)
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["sid"] == sample_preprocessed_sp3.sizes["sid"]

    def test_interpolate_all_variables(self, sample_preprocessed_sp3):
        """Test all position variables are interpolated."""
        config = Sp3Config(use_velocities=False)
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert "X" in result.data_vars
        assert "Y" in result.data_vars
        assert "Z" in result.data_vars

    def test_interpolated_values_reasonable(self, sample_preprocessed_sp3):
        """Test interpolated values are within reasonable range."""
        config = Sp3Config(use_velocities=False)
        strategy = Sp3InterpolationStrategy(config=config)

        base_time = np.datetime64("2024-01-01T00:00:00")
        target_epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        # Position values should be similar to input range
        assert result["X"].min() > 1e7
        assert result["X"].max() < 4e7

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

        config = Sp3Config(use_velocities=True)
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
        config = Sp3Config(use_velocities=False)
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
        config = Sp3Config(use_velocities=False)
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

        sp3_config = Sp3Config(use_velocities=False)
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
        config = Sp3Config(use_velocities=False, fallback_method="nearest")
        strategy = Sp3InterpolationStrategy(config=config)

        # Target epochs before input data
        first_epoch = sample_preprocessed_sp3.epoch.values[0]
        target_epochs = first_epoch - np.arange(10, 0, -1) * np.timedelta64(15, "m")

        # Should handle without crashing
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)
        assert result.sizes["epoch"] == 10

    def test_extrapolation_after_last_epoch(self, sample_preprocessed_sp3):
        """Test extrapolation after last epoch."""
        config = Sp3Config(use_velocities=False, fallback_method="nearest")
        strategy = Sp3InterpolationStrategy(config=config)

        # Target epochs after input data
        last_epoch = sample_preprocessed_sp3.epoch.values[-1]
        target_epochs = last_epoch + np.arange(1, 11) * np.timedelta64(15, "m")

        # Should handle without crashing
        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)
        assert result.sizes["epoch"] == 10

    def test_single_target_epoch(self, sample_preprocessed_sp3):
        """Test interpolation to single epoch."""
        config = Sp3Config(use_velocities=False)
        strategy = Sp3InterpolationStrategy(config=config)

        # Use middle epoch from input
        mid_epoch = sample_preprocessed_sp3.epoch.values[
            len(sample_preprocessed_sp3.epoch) // 2
        ]
        target_epochs = np.array([mid_epoch])

        result = strategy.interpolate(sample_preprocessed_sp3, target_epochs)

        assert result.sizes["epoch"] == 1
