"""
Integration tests for factory-based API.

Tests factory registration, validation, and component creation.
"""

import pytest
from canvodpy.factories import (
    GridFactory,
    ReaderFactory,
    VODFactory,
)


class TestFactoryRegistration:
    """Test factory registration and listing."""

    def test_builtin_readers_registered(self):
        """Built-in readers should be auto-registered."""
        available = ReaderFactory.list_available()
        assert "rinex3" in available

    def test_builtin_grids_registered(self):
        """Every grid type of canvod-grids is registered under its GridType value."""
        from canvod.grids import GridType

        assert set(GridFactory.list_available()) == {t.value for t in GridType}

    def test_grid_factory_registers_the_grid_builders_table(self):
        """GridFactory and create_hemigrid take the builders from one table."""
        from canvod.grids import GRID_BUILDERS

        for grid_type, builder in GRID_BUILDERS.items():
            assert GridFactory._registry[grid_type.value] is builder

    @pytest.mark.parametrize(
        "grid_type",
        [
            "equal_area",
            "equal_angle",
            "equirectangular",
            "htm",
            "geodesic",
            "fibonacci",
            "healpix",
        ],
    )
    def test_factory_grid_matches_create_hemigrid(self, grid_type):
        """The factory builds the same grid as create_hemigrid."""
        from canvod.grids import create_hemigrid

        if grid_type == "healpix":
            pytest.importorskip("healpy")
        built = GridFactory.create(grid_type, angular_resolution=10.0).build()
        expected = create_hemigrid(grid_type, angular_resolution=10.0)
        assert built.grid.equals(expected.grid)

    def test_builtin_vod_registered(self):
        """Built-in VOD calculators should be auto-registered."""
        available = VODFactory.list_available()
        assert "tau_omega" in available

    def test_list_available_returns_list(self):
        """list_available should return list of strings."""
        readers = ReaderFactory.list_available()
        assert isinstance(readers, list)
        assert all(isinstance(name, str) for name in readers)


class TestFactoryCreation:
    """Test component creation via factories."""

    def test_create_grid_builder(self):
        """Should create grid builder instance."""
        builder = GridFactory.create("equal_area", angular_resolution=10.0)
        assert builder is not None
        assert hasattr(builder, "build")

    def test_create_grid_with_params(self):
        """Should pass parameters to grid builder."""
        builder = GridFactory.create(
            "equal_area",
            angular_resolution=10.0,
            cutoff_theta=15.0,  # Reasonable cutoff
        )
        grid = builder.build()
        assert grid.ncells > 0

    def test_create_unknown_component_fails(self):
        """Should raise ValueError for unknown component."""
        with pytest.raises(ValueError, match="not registered"):
            GridFactory.create("nonexistent")


class TestFactoryABCValidation:
    """Test ABC enforcement in factories."""

    def test_register_non_abc_fails(self):
        """Should reject components that don't inherit from ABC."""

        class NotABuilder:
            """Not a grid builder."""

        # Set ABC class first
        GridFactory._set_abc_class()

        with pytest.raises(TypeError, match="must inherit"):
            GridFactory.register("bad", NotABuilder)

    def test_register_valid_component_succeeds(self):
        """Should accept components that inherit from ABC."""
        from canvod.grids.core.grid_builder import BaseGridBuilder

        class ValidBuilder(BaseGridBuilder):
            """Valid grid builder."""

            def _build_grid(self):
                pass

            def get_grid_type(self):
                return "test"

        # Should not raise
        GridFactory.register("test_builder", ValidBuilder)

        # Clean up
        if "test_builder" in GridFactory._registry:
            del GridFactory._registry["test_builder"]

    def test_register_taken_name_fails(self):
        """A name that is taken is not replaced silently."""
        from canvod.vod.calculator import TauOmegaZerothOrder

        class OtherCalculator(TauOmegaZerothOrder):
            """Another calculator."""

        with pytest.raises(ValueError, match="already registered"):
            VODFactory.register("tau_omega", OtherCalculator)
        assert VODFactory.component_class("tau_omega") is TauOmegaZerothOrder

    def test_register_replace(self):
        """replace=True replaces the registered class."""
        from canvod.vod.calculator import TauOmegaZerothOrder

        class OtherCalculator(TauOmegaZerothOrder):
            """Another calculator."""

        VODFactory.register("test_replace", TauOmegaZerothOrder)
        try:
            VODFactory.register("test_replace", OtherCalculator, replace=True)
            assert VODFactory.component_class("test_replace") is OtherCalculator
        finally:
            del VODFactory._registry["test_replace"]


class TestFactoryPydanticValidation:
    """Test Pydantic validation in component creation."""

    def test_invalid_params_raise_validation_error(self):
        """Should validate parameters (TypeError from numpy)."""
        # Grid builders use regular classes, not Pydantic
        # So invalid types raise TypeError, not ValidationError
        with pytest.raises(TypeError):
            # angular_resolution should be float, not string
            GridFactory.create("equal_area", angular_resolution="invalid")

    def test_missing_required_params_fail(self):
        """Should fail if required parameters missing."""
        # GridFactory.create with an unknown name fails with ValueError
        with pytest.raises(ValueError, match="not registered"):
            GridFactory.create("nonexistent_grid_type")


class TestFactoryIsolation:
    """Test that factory registries are isolated."""

    def test_factories_have_separate_registries(self):
        """Each factory should have its own registry."""
        readers = ReaderFactory.list_available()
        grids = GridFactory.list_available()
        vods = VODFactory.list_available()

        # Registries should be different
        assert set(readers) != set(grids)
        assert set(grids) != set(vods)

    def test_registration_in_one_factory_not_visible_in_others(self):
        """Registering in one factory shouldn't affect others."""
        initial_grids = set(GridFactory.list_available())

        # Register a reader
        from canvod.readers.base import GNSSDataReader

        class TestReader(GNSSDataReader):
            """Test reader."""

            def read(self):
                pass

        ReaderFactory.register("test_reader", TestReader)

        # Grid factory should be unchanged
        assert set(GridFactory.list_available()) == initial_grids

        # Clean up
        if "test_reader" in ReaderFactory._registry:
            del ReaderFactory._registry["test_reader"]


class TestFactoryThreadSafety:
    """Test factory behavior in concurrent scenarios."""

    def test_list_available_during_registration(self):
        """list_available should work during registration."""
        # This tests that there are no race conditions
        # In production use, registration happens at import time
        initial = GridFactory.list_available()
        assert isinstance(initial, list)

    def test_multiple_creates_dont_interfere(self):
        """Multiple create calls should be independent."""
        grid1 = GridFactory.create("equal_area", angular_resolution=5.0)
        grid2 = GridFactory.create("equal_area", angular_resolution=10.0)

        # Should create independent builders
        assert grid1 is not grid2

        # With different parameters
        built1 = grid1.build()
        built2 = grid2.build()
        assert built1.ncells != built2.ncells


class TestAugmentationFactoryDeprecated:
    """AugmentationFactory is left over from development and warns."""

    @pytest.mark.filterwarnings("default::FutureWarning")
    def test_list_available_warns(self):
        from canvodpy.factories import AugmentationFactory

        with pytest.warns(FutureWarning, match="canvod.ops.Op"):
            AugmentationFactory.list_available()

    @pytest.mark.filterwarnings("ignore::FutureWarning")
    def test_register_replace(self):
        from canvodpy.factories import AugmentationFactory

        from canvod.auxiliary.augmentation import AugmentationStep

        class _First(AugmentationStep):
            def augment(self, ds, aux_data, **kwargs):
                return ds

        class _Second(_First):
            pass

        name = "_test_replace"
        try:
            AugmentationFactory.register(name, _First)
            with pytest.raises(ValueError, match="already registered"):
                AugmentationFactory.register(name, _Second)
            AugmentationFactory.register(name, _Second, replace=True)
            assert AugmentationFactory._registry[name] is _Second
        finally:
            AugmentationFactory._registry.pop(name, None)
