"""Basic metadata tests for canvod-viz package."""

from importlib.metadata import version


def test_package_importable():
    """Test that package can be imported."""
    import canvod.viz

    assert canvod.viz is not None


def test_package_has_version():
    """Test that package has version attribute."""
    from canvod.viz import __version__

    assert isinstance(__version__, str)
    assert __version__ == version("canvod-viz")


def test_package_has_all():
    """Test that package has __all__ attribute."""
    import canvod.viz

    assert hasattr(canvod.viz, "__all__")
    assert isinstance(canvod.viz.__all__, list)
    assert len(canvod.viz.__all__) > 0


def test_all_exports_importable():
    """Test that all items in __all__ can be imported."""
    import canvod.viz
    from canvod.viz import __all__

    for name in __all__:
        assert hasattr(canvod.viz, name), f"{name} not found in canvod.viz"
        obj = getattr(canvod.viz, name)
        assert obj is not None, f"{name} is None"


def test_main_classes_exported():
    """Test that main classes are exported."""
    from canvod.viz import (
        HemisphereVisualizer,
        HemisphereVisualizer2D,
        HemisphereVisualizer3D,
    )

    assert HemisphereVisualizer is not None
    assert HemisphereVisualizer2D is not None
    assert HemisphereVisualizer3D is not None


def test_style_classes_exported():
    """Test that style classes are exported."""
    from canvod.viz import PlotStyle, PolarPlotStyle

    assert PolarPlotStyle is not None
    assert PlotStyle is not None


def test_style_factories_exported():
    """Test that style factory functions are exported."""
    from canvod.viz import create_interactive_style, create_publication_style

    assert callable(create_publication_style)
    assert callable(create_interactive_style)
