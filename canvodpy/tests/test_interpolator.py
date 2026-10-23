"""Tests for the deprecated canvodpy.orchestrator.interpolator module.

The names there are subclasses of ``canvod.auxiliary.interpolation`` without
logic of their own; these tests make sure they still work and warn.
"""

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator import interpolator as orch
from canvodpy.orchestrator.interpolator import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
    create_interpolator_from_attrs,
)

from canvod.auxiliary import interpolation as aux

pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


@pytest.mark.filterwarnings("default::FutureWarning")
@pytest.mark.parametrize(
    "name",
    [
        "InterpolatorConfig",
        "Sp3Config",
        "ClockConfig",
        "Sp3InterpolationStrategy",
        "ClockInterpolationStrategy",
    ],
)
def test_names_are_deprecated_subclasses(name):
    assert issubclass(getattr(orch, name), getattr(aux, name))
    kwargs = {}
    if name.endswith("Strategy"):
        config = "Sp3Config" if name.startswith("Sp3") else "ClockConfig"
        kwargs = {"config": getattr(aux, config)()}
    with pytest.warns(
        FutureWarning, match=f"Use canvod.auxiliary.interpolation.{name}"
    ):
        getattr(orch, name)(**kwargs)


@pytest.mark.filterwarnings("default::FutureWarning")
def test_create_interpolator_from_attrs_is_deprecated():
    attrs = {
        "interpolator_config": aux.Sp3InterpolationStrategy(
            config=aux.Sp3Config()
        ).to_attrs()
    }
    with pytest.warns(FutureWarning, match="left over from development"):
        interp = create_interpolator_from_attrs(attrs)
    assert type(interp) is aux.Sp3InterpolationStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sp3_ds(n_epochs: int = 10, n_sids: int = 3) -> xr.Dataset:
    """Create a synthetic SP3 dataset with positions and velocities."""
    rng = np.random.default_rng(42)
    epochs = np.array(
        [
            np.datetime64("2024-10-29T00:00:00") + np.timedelta64(i * 900, "s")
            for i in range(n_epochs)
        ]
    )
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    return xr.Dataset(
        {
            "X": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Y": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Z": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Vx": (["epoch", "sid"], rng.uniform(-100, 100, (n_epochs, n_sids))),
            "Vy": (["epoch", "sid"], rng.uniform(-100, 100, (n_epochs, n_sids))),
            "Vz": (["epoch", "sid"], rng.uniform(-100, 100, (n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


def _make_clock_ds(n_epochs: int = 20, n_sids: int = 3) -> xr.Dataset:
    """Create a synthetic clock dataset."""
    rng = np.random.default_rng(42)
    epochs = np.array(
        [
            np.datetime64("2024-10-29T00:00:00") + np.timedelta64(i * 30, "s")
            for i in range(n_epochs)
        ]
    )
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    return xr.Dataset(
        {
            "clock_offset": (
                ["epoch", "sid"],
                rng.uniform(-1e-3, 1e-3, (n_epochs, n_sids)),
            ),
        },
        coords={"epoch": epochs, "sid": sids},
    )


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


class TestSp3Config:
    """Tests for Sp3Config."""

    def test_defaults(self):
        cfg = Sp3Config()
        assert cfg.use_velocities is True
        assert cfg.fallback_method == "linear"

    def test_custom(self):
        cfg = Sp3Config(use_velocities=False, fallback_method="nearest")
        assert cfg.use_velocities is False
        assert cfg.fallback_method == "nearest"

    def test_to_dict(self):
        cfg = Sp3Config()
        d = cfg.to_dict()
        assert d["use_velocities"] is True
        assert d["fallback_method"] == "linear"


class TestClockConfig:
    """Tests for ClockConfig."""

    def test_defaults(self):
        cfg = ClockConfig()
        assert cfg.window_size == 9
        assert cfg.jump_threshold == 1e-6

    def test_custom(self):
        cfg = ClockConfig(window_size=5, jump_threshold=1e-5)
        assert cfg.window_size == 5

    def test_to_dict(self):
        cfg = ClockConfig()
        d = cfg.to_dict()
        assert "window_size" in d
        assert "jump_threshold" in d


# ---------------------------------------------------------------------------
# Sp3InterpolationStrategy
# ---------------------------------------------------------------------------


class TestSp3InterpolationStrategy:
    """Tests for Sp3InterpolationStrategy."""

    def test_interpolate_with_velocities(self):
        ds = _make_sp3_ds(n_epochs=10)
        config = Sp3Config(use_velocities=True)
        interp = Sp3InterpolationStrategy(config=config)

        # Target epochs between source epochs
        target = np.array(
            [
                np.datetime64("2024-10-29T00:07:30") + np.timedelta64(i * 900, "s")
                for i in range(5)
            ]
        )

        result = interp.interpolate(ds, target)
        assert isinstance(result, xr.Dataset)
        assert "X" in result.data_vars
        assert "Y" in result.data_vars
        assert "Z" in result.data_vars
        assert len(result.epoch) == 5

    def test_interpolate_positions_only(self):
        ds = _make_sp3_ds(n_epochs=10)
        # Remove velocities
        ds = ds.drop_vars(["Vx", "Vy", "Vz"])
        config = Sp3Config(use_velocities=True)
        interp = Sp3InterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-10-29T00:07:30") + np.timedelta64(i * 900, "s")
                for i in range(5)
            ]
        )

        result = interp.interpolate(ds, target)
        assert isinstance(result, xr.Dataset)
        assert "X" in result.data_vars

    def test_interpolate_fallback_method(self):
        ds = _make_sp3_ds(n_epochs=10)
        ds = ds.drop_vars(["Vx", "Vy", "Vz"])
        config = Sp3Config(use_velocities=False)
        interp = Sp3InterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-10-29T00:07:30") + np.timedelta64(i * 900, "s")
                for i in range(5)
            ]
        )

        result = interp.interpolate(ds, target)
        assert isinstance(result, xr.Dataset)

    def test_to_attrs(self):
        config = Sp3Config()
        interp = Sp3InterpolationStrategy(config=config)
        attrs = interp.to_attrs()
        assert attrs["interpolator_type"] == "Sp3InterpolationStrategy"
        assert "config" in attrs

    def test_interpolate_all_nan_satellite(self):
        """All-NaN satellite must produce NaN output, not uninitialized
        memory. Regression test: coords/vels arrays are pre-allocated with
        np.empty() (garbage, not zeros/NaN); _interpolate_sv's all-NaN skip
        branches must explicitly write NaN before continuing, or a skipped
        satellite's entire column silently keeps whatever was already in
        that memory -- which then gets treated downstream as a real ECEF
        position (canvodpy #geometry-augmentation-bug, 2026-08).
        """
        ds = _make_sp3_ds(n_epochs=10, n_sids=3)
        for var in ["X", "Y", "Z", "Vx", "Vy", "Vz"]:
            data = ds[var].values.copy()
            data[:, 0] = np.nan
            ds[var] = (["epoch", "sid"], data)

        config = Sp3Config(use_velocities=True)
        interp = Sp3InterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-10-29T00:07:30") + np.timedelta64(i * 900, "s")
                for i in range(5)
            ]
        )

        result = interp.interpolate(ds, target)
        for var in ["X", "Y", "Z", "Vx", "Vy", "Vz"]:
            assert np.all(np.isnan(result[var].values[:, 0])), (
                f"{var}: all-NaN satellite produced non-NaN (garbage) output"
            )
        # Untouched satellites still interpolate normally.
        assert np.all(np.isfinite(result["X"].values[:, 1]))


# ---------------------------------------------------------------------------
# ClockInterpolationStrategy
# ---------------------------------------------------------------------------


class TestClockInterpolationStrategy:
    """Tests for ClockInterpolationStrategy."""

    def test_interpolate(self):
        ds = _make_clock_ds(n_epochs=20)
        config = ClockConfig()
        interp = ClockInterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-10-29T00:00:15") + np.timedelta64(i * 30, "s")
                for i in range(10)
            ]
        )

        result = interp.interpolate(ds, target)
        assert isinstance(result, xr.Dataset)
        assert "clock_offset" in result.data_vars
        assert len(result.epoch) == 10

    def test_interpolate_all_nan(self):
        """All-NaN SV should produce NaN output."""
        ds = _make_clock_ds(n_epochs=10, n_sids=2)
        # Set first SV to all NaN
        data = ds["clock_offset"].values.copy()
        data[:, 0] = np.nan
        ds["clock_offset"] = (["epoch", "sid"], data)

        config = ClockConfig()
        interp = ClockInterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-10-29T00:00:15") + np.timedelta64(i * 30, "s")
                for i in range(5)
            ]
        )

        result = interp.interpolate(ds, target)
        assert np.all(np.isnan(result["clock_offset"].values[:, 0]))

    def test_no_clock_vars_raises(self):
        ds = xr.Dataset(
            {"position": (["epoch", "sid"], np.zeros((5, 2)))},
            coords={
                "epoch": np.array(
                    [
                        np.datetime64("2024-01-01") + np.timedelta64(i, "s")
                        for i in range(5)
                    ]
                ),
                "sid": ["G01", "G02"],
            },
        )
        config = ClockConfig()
        interp = ClockInterpolationStrategy(config=config)

        target = np.array(
            [
                np.datetime64("2024-01-01T00:00:00") + np.timedelta64(i, "s")
                for i in range(3)
            ]
        )

        with pytest.raises(ValueError, match="No clock variables"):
            interp.interpolate(ds, target)


# ---------------------------------------------------------------------------
# create_interpolator_from_attrs
# ---------------------------------------------------------------------------


class TestCreateInterpolatorFromAttrs:
    """Tests for factory function."""

    def test_sp3_from_attrs(self):
        attrs = {
            "interpolator_config": {
                "interpolator_type": "Sp3InterpolationStrategy",
                "config": {"use_velocities": True, "fallback_method": "linear"},
            }
        }
        interp = create_interpolator_from_attrs(attrs)
        assert isinstance(interp, aux.Sp3InterpolationStrategy)

    def test_clock_from_attrs(self):
        attrs = {
            "interpolator_config": {
                "interpolator_type": "ClockInterpolationStrategy",
                "config": {"window_size": 9, "jump_threshold": 1e-6},
            }
        }
        interp = create_interpolator_from_attrs(attrs)
        assert isinstance(interp, aux.ClockInterpolationStrategy)

    def test_unknown_type_raises(self):
        attrs = {
            "interpolator_config": {
                "interpolator_type": "UnknownStrategy",
                "config": {},
            }
        }
        with pytest.raises(ValueError, match="Unknown interpolator type"):
            create_interpolator_from_attrs(attrs)
