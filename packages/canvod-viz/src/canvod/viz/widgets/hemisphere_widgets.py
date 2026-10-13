"""Interactive hemisphere selector widgets for marimo notebooks.

Provides anywidget-based 3D (plotly) and 2D (canvas) hemisphere selectors
with click-to-select and hover-tooltip support.
"""

from __future__ import annotations

from pathlib import Path

import anywidget
import traitlets


class HemisphereSelector3D(anywidget.AnyWidget):
    """3D interactive hemisphere selector using Plotly Scatter3d.

    Renders cell centers as scatter markers on a hemisphere.  Click to
    toggle cell selection; hover to preview cell info.

    Parameters (set as traits)
    --------------------------
    cell_centers_x/y/z : list[float]
        Cartesian coordinates of cell centers on the unit hemisphere.
    cell_values : list[float]
        Scalar value per cell (used for coloring).
    cell_labels : list[str]
        Tooltip label per cell.
    colorscale : str
        Plotly colorscale name (default ``"Viridis"``).
    selected_cell_ids : list[int]
        Indices of currently selected cells (read/write, synced to JS).
    hovered_cell_id : int
        Index of currently hovered cell (``-1`` if none).

    """

    _esm = Path(__file__).parent / "hemisphere_selector_3d.js"
    _css = Path(__file__).parent / "hemisphere_selector.css"

    # Python → JS
    cell_centers_x = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_centers_y = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_centers_z = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_values = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_labels = traitlets.List(traitlets.Unicode()).tag(sync=True)
    colorscale = traitlets.Unicode("Viridis").tag(sync=True)
    marker_size = traitlets.Int(6).tag(sync=True)

    # JS → Python
    selected_cell_ids = traitlets.List(traitlets.Int()).tag(sync=True)
    hovered_cell_id = traitlets.Int(-1).tag(sync=True)


class HemisphereSelector2D(anywidget.AnyWidget):
    """2D polar-projection hemisphere selector using HTML Canvas.

    Renders cells as filled wedges on a polar stereographic projection
    (North-up, clockwise azimuth).

    Parameters (set as traits)
    --------------------------
    cell_theta : list[float]
        Polar angle per cell center (radians, 0 = zenith).
    cell_phi : list[float]
        Azimuth per cell center (radians, 0 = North, CW).
    cell_values : list[float]
        Scalar value per cell.
    cell_labels : list[str]
        Tooltip label per cell.
    colorscale_name : str
        Name for display (coloring done in JS with viridis LUT).
    selected_cell_ids : list[int]
        Indices of selected cells.
    hovered_cell_id : int
        Index of hovered cell.

    """

    _esm = Path(__file__).parent / "hemisphere_selector_2d.js"
    _css = Path(__file__).parent / "hemisphere_selector.css"

    # Python → JS
    cell_theta = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_phi = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_values = traitlets.List(traitlets.Float()).tag(sync=True)
    cell_labels = traitlets.List(traitlets.Unicode()).tag(sync=True)
    colorscale_name = traitlets.Unicode("viridis").tag(sync=True)
    canvas_size = traitlets.Int(500).tag(sync=True)

    # JS → Python
    selected_cell_ids = traitlets.List(traitlets.Int()).tag(sync=True)
    hovered_cell_id = traitlets.Int(-1).tag(sync=True)
