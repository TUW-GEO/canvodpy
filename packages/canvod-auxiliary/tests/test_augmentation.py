"""Tests for canvod.auxiliary.augmentation module."""

from unittest.mock import MagicMock

import numpy as np
import pytest
import xarray as xr

from canvod.auxiliary.augmentation import (
    AugmentationContext,
    AugmentationStep,
    AuxDataAugmenter,
    ClockCorrectionAugmentation,
    SphericalCoordinateAugmentation,
)
from canvod.auxiliary.position import ECEFPosition

# The augmentation framework is deprecated; the tests below keep it working
# until it is removed, TestDeprecation checks the warnings.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rinex_ds(n_epochs: int = 5, n_sids: int = 3) -> xr.Dataset:
    """Minimal RINEX-like dataset for augmentation tests."""
    rng = np.random.default_rng(42)
    epochs = np.array(
        [
            np.datetime64("2024-10-29T00:00:00") + np.timedelta64(i * 30, "s")
            for i in range(n_epochs)
        ]
    )
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    return xr.Dataset(
        {"SNR": (["epoch", "sid"], rng.uniform(20, 50, (n_epochs, n_sids)))},
        coords={"epoch": epochs, "sid": sids},
        attrs={
            "APPROX POSITION XYZ": "4000000.0 1000000.0 4800000.0",
        },
    )


def _make_ephem_ds(n_epochs: int = 5, n_sids: int = 3) -> xr.Dataset:
    """Minimal ephemerides dataset."""
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
            "X": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Y": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Z": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


# ---------------------------------------------------------------------------
# AugmentationContext
# ---------------------------------------------------------------------------


class TestAugmentationContext:
    """Tests for AugmentationContext."""

    def test_init_defaults(self):
        ctx = AugmentationContext()
        assert ctx.receiver_position is None
        assert ctx.receiver_type is None
        assert ctx.matched_datasets == {}
        assert ctx.metadata == {}

    def test_init_with_params(self):
        pos = ECEFPosition(x=4000000.0, y=1000000.0, z=4800000.0)
        ds = _make_ephem_ds()
        ctx = AugmentationContext(
            receiver_position=pos,
            receiver_type="canopy",
            matched_datasets={"ephemerides": ds},
            metadata={"key": "val"},
        )
        assert ctx.receiver_position == pos
        assert ctx.receiver_type == "canopy"
        assert "ephemerides" in ctx.matched_datasets
        assert ctx.metadata["key"] == "val"

    def test_get_matched_dataset(self):
        ds = _make_ephem_ds()
        ctx = AugmentationContext(matched_datasets={"ephemerides": ds})
        result = ctx.get_matched_dataset("ephemerides")
        assert result is ds

    def test_get_matched_dataset_missing_raises(self):
        ctx = AugmentationContext()
        with pytest.raises(KeyError, match="not in matched datasets"):
            ctx.get_matched_dataset("nonexistent")

    def test_set_receiver_position(self):
        ctx = AugmentationContext()
        pos = ECEFPosition(x=1.0, y=2.0, z=3.0)
        ctx.set_receiver_position(pos)
        assert ctx.receiver_position == pos

    def test_repr(self):
        ctx = AugmentationContext(receiver_type="canopy")
        r = repr(ctx)
        assert "canopy" in r
        assert "AugmentationContext" in r


# ---------------------------------------------------------------------------
# SphericalCoordinateAugmentation
# ---------------------------------------------------------------------------


class TestSphericalCoordinateAugmentation:
    """Tests for SphericalCoordinateAugmentation."""

    def test_init(self):
        step = SphericalCoordinateAugmentation()
        assert step.name == "SphericalCoordinates"

    def test_required_aux_files(self):
        step = SphericalCoordinateAugmentation()
        assert step.get_required_aux_files() == ["ephemerides"]

    def test_augment_no_position_raises(self):
        step = SphericalCoordinateAugmentation()
        ds = _make_rinex_ds()
        ctx = AugmentationContext(matched_datasets={"ephemerides": _make_ephem_ds()})
        pipeline = MagicMock()

        with pytest.raises(ValueError, match="requires receiver position"):
            step.augment(ds, pipeline, ctx)

    def test_augment_no_ephemerides_raises(self):
        step = SphericalCoordinateAugmentation()
        ds = _make_rinex_ds()
        pos = ECEFPosition(x=4000000.0, y=1000000.0, z=4800000.0)
        ctx = AugmentationContext(
            receiver_position=pos,
            matched_datasets={},
        )
        pipeline = MagicMock()

        with pytest.raises(ValueError, match="requires 'ephemerides'"):
            step.augment(ds, pipeline, ctx)

    def test_augment_adds_coords(self):
        step = SphericalCoordinateAugmentation()
        ds = _make_rinex_ds()
        ephem_ds = _make_ephem_ds()
        pos = ECEFPosition(x=4000000.0, y=1000000.0, z=4800000.0)
        ctx = AugmentationContext(
            receiver_position=pos,
            matched_datasets={"ephemerides": ephem_ds},
        )
        pipeline = MagicMock()

        result = step.augment(ds, pipeline, ctx)
        assert "phi" in result.data_vars
        assert "theta" in result.data_vars
        assert "r" in result.data_vars


# ---------------------------------------------------------------------------
# ClockCorrectionAugmentation
# ---------------------------------------------------------------------------


class TestClockCorrectionAugmentation:
    """Tests for ClockCorrectionAugmentation."""

    def test_init(self):
        step = ClockCorrectionAugmentation()
        assert step.name == "ClockCorrection"

    def test_required_aux_files(self):
        """Empty on purpose: clock is optional (fetch_clock config flag),
        and augment() already handles its absence gracefully."""
        step = ClockCorrectionAugmentation()
        assert step.get_required_aux_files() == []

    def test_augment_returns_unchanged(self):
        """Placeholder step returns dataset unchanged."""
        step = ClockCorrectionAugmentation()
        ds = _make_rinex_ds()
        ctx = AugmentationContext(
            matched_datasets={"clock": xr.Dataset()},
        )
        pipeline = MagicMock()

        result = step.augment(ds, pipeline, ctx)
        assert set(result.data_vars) == set(ds.data_vars)

    def test_augment_missing_clock_warns(self):
        """Missing clock data should log warning, not raise."""
        step = ClockCorrectionAugmentation()
        ds = _make_rinex_ds()
        ctx = AugmentationContext(matched_datasets={})
        pipeline = MagicMock()

        result = step.augment(ds, pipeline, ctx)
        assert result is ds


# ---------------------------------------------------------------------------
# AuxDataAugmenter
# ---------------------------------------------------------------------------


class TestAuxDataAugmenter:
    """Tests for AuxDataAugmenter orchestrator."""

    def test_init_default_steps(self):
        pipeline = MagicMock()
        augmenter = AuxDataAugmenter(pipeline)
        assert len(augmenter.steps) == 2
        assert augmenter.steps[0].name == "SphericalCoordinates"
        assert augmenter.steps[1].name == "ClockCorrection"

    def test_init_custom_steps(self):
        pipeline = MagicMock()
        step = ClockCorrectionAugmentation()
        augmenter = AuxDataAugmenter(pipeline, steps=[step])
        assert len(augmenter.steps) == 1

    def test_add_step(self):
        pipeline = MagicMock()
        step = ClockCorrectionAugmentation()
        augmenter = AuxDataAugmenter(pipeline, steps=[step])
        augmenter.add_step(ClockCorrectionAugmentation())
        assert len(augmenter.steps) == 2

    def test_augment_dataset_required_not_loaded_raises(self):
        """If a required aux file is not loaded, augment should raise."""
        pipeline = MagicMock()
        pipeline.is_loaded.return_value = False
        augmenter = AuxDataAugmenter(pipeline)

        ds = _make_rinex_ds()

        with pytest.raises((ValueError, RuntimeError, KeyError)):
            augmenter.augment_dataset(ds)

    def test_repr(self):
        pipeline = MagicMock()
        augmenter = AuxDataAugmenter(pipeline)
        r = repr(augmenter)
        assert "AuxDataAugmenter" in r


# ---------------------------------------------------------------------------
# AugmentationStep (abstract)
# ---------------------------------------------------------------------------


class TestAugmentationStepABC:
    """Test the abstract base class contract."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AugmentationStep("test")

    def test_concrete_subclass(self):
        class Dummy(AugmentationStep):
            def augment(self, ds, aux_pipeline, context):
                return ds

            def get_required_aux_files(self):
                return []

        step = Dummy("dummy")
        assert step.name == "dummy"
        assert repr(step) == "Dummy(name='dummy')"


class TestDeprecation:
    """Every part of the augmentation framework warns and names a replacement."""

    @pytest.mark.parametrize(
        ("make", "replacement"),
        [
            (lambda: AugmentationContext(), "canvod.ops.Op"),
            (lambda: AuxDataAugmenter(MagicMock()), "add_spherical_coords"),
            (SphericalCoordinateAugmentation, "add_spherical_coords"),
            (ClockCorrectionAugmentation, "drop it"),
        ],
    )
    @pytest.mark.filterwarnings("default::FutureWarning")
    def test_warns(self, make, replacement) -> None:
        with pytest.warns(FutureWarning, match=replacement):
            make()

    @pytest.mark.filterwarnings("default::FutureWarning")
    def test_step_subclass_warns(self) -> None:
        class _Step(AugmentationStep):
            def augment(self, ds, aux_pipeline, context):
                return ds

            def get_required_aux_files(self):
                return []

        with pytest.warns(FutureWarning, match="`AugmentationStep` is left over"):
            _Step(name="x")
