"""Visualization and plotting utilities for GNSS VOD data.

This package provides 2D and 3D visualization capabilities for hemispherical
GNSS grids and VOD data, with both publication-quality (matplotlib) and
interactive (plotly) rendering options.

Examples
--------
2D polar visualization::

    from canvod.viz import HemisphereVisualizer2D
    from canvod.grids import create_hemigrid

    grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    viz = HemisphereVisualizer2D(grid)
    fig, ax = viz.plot_grid_patches(data=vod_data, title="VOD Distribution")

Convenience function::

    from canvod.viz import visualize_grid, add_tissot_indicatrix

    fig, ax = visualize_grid(grid, data=vod_data, cmap='viridis')
    add_tissot_indicatrix(ax, grid, n_sample=5)

3D interactive visualization::

    from canvod.viz import HemisphereVisualizer3D

    viz3d = HemisphereVisualizer3D(grid)
    fig = viz3d.plot_hemisphere_surface(data=vod_data, title="Interactive VOD")
    fig.show()

Unified API::

    from canvod.viz import HemisphereVisualizer

    viz = HemisphereVisualizer(grid)
    fig_2d, ax_2d = viz.plot_2d(data=vod_data)
    fig_3d = viz.plot_3d(data=vod_data)

"""

from importlib.metadata import version as _version

from canvod.viz.hemisphere_2d import (
    HemisphereVisualizer2D,
    PolarPlotStyle,
    add_tissot_indicatrix,
    visualize_grid,
)
from canvod.viz.hemisphere_3d import HemisphereVisualizer3D, visualize_grid_3d
from canvod.viz.styles import (
    RSE_COLORS,
    Colorscale,
    PlotStyle,
    apply_rse_style,
    create_interactive_style,
    create_publication_style,
    create_rse_style,
    fix_figure_for_dark_mode,
    rse_context,
    rse_style,
    style_colorbar,
)
from canvod.viz.visualizer import HemisphereVisualizer

__version__ = _version("canvod-viz")

__all__ = [
    "RSE_COLORS",
    # Styling
    "Colorscale",
    # Main visualizers
    "HemisphereVisualizer",
    "HemisphereVisualizer2D",
    "HemisphereVisualizer3D",
    "PlotStyle",
    "PolarPlotStyle",
    "add_tissot_indicatrix",
    "apply_rse_style",
    "create_interactive_style",
    "create_publication_style",
    "create_rse_style",
    "fix_figure_for_dark_mode",
    "rse_context",
    "rse_style",
    "style_colorbar",
    # Convenience functions
    "visualize_grid",
    "visualize_grid_3d",
]
