"""Tests for the interactive hemisphere widgets (canvod.viz.widgets)."""

import subprocess
import sys
from pathlib import Path

import pytest


def test_canvod_viz_imports_without_anywidget():
    """Importing canvod.viz must not pull in anywidget."""
    code = "import canvod.viz, sys; assert 'anywidget' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_selector_assets_exist():
    """The JS and CSS each selector loads exist next to the widget module.

    anywidget wraps ``_esm`` and ``_css`` in a ``FileContents`` object, so
    we check the files the widget module points at (same directory as the
    module) rather than wrapping ``cls._esm`` in a ``Path``.
    """
    pytest.importorskip("anywidget")
    import canvod.viz.widgets as widgets
    from canvod.viz.widgets import HemisphereSelector2D, HemisphereSelector3D

    base = Path(widgets.__file__).parent
    for js in ("hemisphere_selector_2d.js", "hemisphere_selector_3d.js"):
        assert (base / js).is_file()
    assert (base / "hemisphere_selector.css").is_file()

    # each class resolves its assets to a file in the same directory
    for cls in (HemisphereSelector2D, HemisphereSelector3D):
        for attr in ("_esm", "_css"):
            assert (base / Path(getattr(cls, attr)._path).name).is_file()


def test_selectors_take_cells():
    """Each selector takes three cells and starts with no selection."""
    pytest.importorskip("anywidget")
    from canvod.viz.widgets import HemisphereSelector2D, HemisphereSelector3D

    three = [1.0, 2.0, 3.0]
    labels = ["a", "b", "c"]

    sel3d = HemisphereSelector3D(
        cell_centers_x=three,
        cell_centers_y=three,
        cell_centers_z=three,
        cell_values=three,
        cell_labels=labels,
    )
    assert sel3d.selected_cell_ids == []

    sel2d = HemisphereSelector2D(
        cell_theta=three,
        cell_phi=three,
        cell_values=three,
        cell_labels=labels,
    )
    assert sel2d.selected_cell_ids == []
