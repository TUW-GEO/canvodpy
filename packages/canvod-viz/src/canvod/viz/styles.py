"""Styling configuration for visualizations.

Provides consistent styling across 2D matplotlib and 3D plotly visualizations,
including publication-quality RSE journal style and colorscale utilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Literal


@dataclass
class PolarPlotStyle:
    """Configuration for 2D polar plot styling (matplotlib).

    Parameters
    ----------
    cmap : str, default 'viridis'
        Matplotlib colormap name
    edgecolor : str, default 'black'
        Edge color for grid cells
    linewidth : float, default 0.5
        Line width for cell edges
    alpha : float, default 1.0
        Transparency (0=transparent, 1=opaque)
    vmin : float or None, optional
        Minimum value for colormap
    vmax : float or None, optional
        Maximum value for colormap
    title : str or None, optional
        Plot title
    figsize : tuple of float, default (10, 10)
        Figure size in inches (width, height)
    dpi : int, default 100
        Dots per inch for figure
    colorbar_label : str, default 'Value'
        Label for colorbar
    colorbar_shrink : float, default 0.8
        Colorbar size relative to axis
    colorbar_pad : float, default 0.1
        Space between axis and colorbar
    colorbar_fontsize : int, default 11
        Font size for colorbar label
    show_grid : bool, default True
        Show polar grid lines
    grid_alpha : float, default 0.3
        Grid line transparency
    grid_linestyle : str, default '--'
        Grid line style
    show_degree_labels : bool, default True
        Show degree labels on radial axis
    theta_labels : list of int, default [0, 30, 60, 90]
        Elevation angles for labels (degrees)
    projection : {'orthographic', 'equidistant'}, default 'orthographic'
        Radial mapping from zenith angle theta to plot radius rho.
        'orthographic' (rho = sin(theta)) is a straight-down view of the 3D
        hemisphere -- cells compress toward the horizon at the rim.
        'equidistant' (rho = theta / (pi/2)) is a true polar plot with
        elevation rings evenly spaced, the conventional GNSS skyplot
        convention.

    """

    cmap: str = "viridis"
    edgecolor: str = "black"
    linewidth: float = 0.5
    alpha: float = 1.0
    vmin: float | None = None
    vmax: float | None = None
    title: str | None = None
    figsize: tuple[float, float] = (10, 10)
    dpi: int = 100
    colorbar_label: str = "Value"
    colorbar_shrink: float = 0.8
    colorbar_pad: float = 0.1
    colorbar_fontsize: int = 11
    show_grid: bool = True
    grid_alpha: float = 0.3
    grid_linestyle: str = "--"
    show_degree_labels: bool = True
    theta_labels: list[int] = field(default_factory=lambda: [0, 30, 60, 90])
    projection: Literal["orthographic", "equidistant"] = "orthographic"


@dataclass
class PlotStyle:
    """Unified styling configuration for both 2D and 3D plots.

    Parameters
    ----------
    colormap : str, default 'viridis'
        Colormap name (matplotlib or plotly)
    colorscale : str, default 'Viridis'
        Plotly colorscale name
    background_color : str, default 'white'
        Background color
    text_color : str, default 'black'
        Text color
    grid_color : str, default 'lightgray'
        Grid line color
    font_family : str, default 'sans-serif'
        Font family
    font_size : int, default 11
        Base font size
    title_size : int, default 14
        Title font size
    label_size : int, default 12
        Axis label font size
    edge_linewidth : float, default 0.5
        Edge line width for cells
    opacity : float, default 0.8
        3D surface opacity
    marker_size : int, default 8
        3D marker size
    line_width : int, default 1
        3D line width
    wireframe_opacity : float, default 0.2
        3D wireframe transparency
    dark_mode : bool, default False
        Use dark theme

    """

    colormap: str = "viridis"
    colorscale: str = "Viridis"
    background_color: str = "white"
    text_color: str = "black"
    grid_color: str = "lightgray"
    font_family: str = "sans-serif"
    font_size: int = 11
    title_size: int = 14
    label_size: int = 12
    edge_linewidth: float = 0.5
    opacity: float = 0.8
    marker_size: int = 8
    line_width: int = 1
    wireframe_opacity: float = 0.2
    dark_mode: bool = False

    def to_polar_style(self) -> PolarPlotStyle:
        """Convert to PolarPlotStyle for 2D matplotlib plots.

        Returns
        -------
        PolarPlotStyle
            Equivalent 2D styling configuration

        """
        return PolarPlotStyle(
            cmap=self.colormap,
            edgecolor="white" if self.dark_mode else self.text_color,
            linewidth=self.edge_linewidth,
            alpha=1.0,
            colorbar_fontsize=self.font_size,
        )

    def to_plotly_layout(self) -> dict[str, Any]:
        """Convert to plotly layout configuration.

        Returns
        -------
        dict
            Plotly layout settings

        """
        if self.dark_mode:
            return {
                "template": "plotly_dark",
                "paper_bgcolor": "#111111",
                "plot_bgcolor": "#111111",
                "font": {
                    "family": self.font_family,
                    "size": self.font_size,
                    "color": "white",
                },
            }
        return {
            "template": "plotly",
            "paper_bgcolor": self.background_color,
            "plot_bgcolor": self.background_color,
            "font": {
                "family": self.font_family,
                "size": self.font_size,
                "color": self.text_color,
            },
        }


def create_publication_style() -> PlotStyle:
    """Create styling optimized for publication-quality figures.

    Returns
    -------
    PlotStyle
        Publication-optimized styling configuration

    Examples
    --------
    >>> style = create_publication_style()
    >>> viz.plot_2d(data=vod_data, style=style)

    """
    return PlotStyle(
        colormap="viridis",
        colorscale="Viridis",
        background_color="white",
        text_color="black",
        font_family="sans-serif",
        font_size=12,
        title_size=16,
        label_size=14,
        edge_linewidth=0.3,
        opacity=0.9,
        dark_mode=False,
    )


def create_rse_style() -> PlotStyle:
    """Create styling matching Remote Sensing of Environment journal guidelines.

    Returns
    -------
    PlotStyle
        RSE-compatible styling with Arial/Helvetica fonts, 300 DPI,
        inward ticks, and colorblind-friendly color cycle.

    """
    return PlotStyle(
        colormap="viridis",
        colorscale="Viridis",
        background_color="white",
        text_color="black",
        font_family="Arial, Helvetica, DejaVu Sans, sans-serif",
        font_size=11,
        title_size=14,
        label_size=12,
        edge_linewidth=1.0,
        opacity=0.9,
        dark_mode=False,
    )


def create_interactive_style(dark_mode: bool = True) -> PlotStyle:
    """Create styling optimized for interactive exploration.

    Parameters
    ----------
    dark_mode : bool, default True
        Use dark theme for better screen viewing

    Returns
    -------
    PlotStyle
        Interactive-optimized styling configuration

    Examples
    --------
    >>> style = create_interactive_style(dark_mode=True)
    >>> viz.plot_3d(data=vod_data, style=style)

    """
    return PlotStyle(
        colormap="plasma" if dark_mode else "viridis",
        colorscale="Plasma" if dark_mode else "Viridis",
        background_color="#111111" if dark_mode else "white",
        text_color="white" if dark_mode else "black",
        font_family="Open Sans, sans-serif",
        font_size=11,
        title_size=14,
        label_size=12,
        edge_linewidth=0.5,
        opacity=0.85,
        marker_size=6,
        wireframe_opacity=0.15,
        dark_mode=dark_mode,
    )


# ==============================================================================
# RSE journal style (Remote Sensing of Environment)
# ==============================================================================

#: Colorblind-friendly palette (Wong, 2011).
RSE_COLORS: list[str] = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#E69F00",
    "#F0E442",
    "#000000",
]


def _rse_rcparams() -> dict[str, Any]:
    """Return matplotlib rcParams dict for RSE journal style."""
    import matplotlib.pyplot as plt

    return {
        "figure.figsize": (8.0, 6.0),
        "figure.dpi": 300,
        "figure.facecolor": "white",
        "figure.edgecolor": "white",
        "savefig.facecolor": "white",
        "savefig.edgecolor": "white",
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 11,
        "text.color": "black",
        "axes.linewidth": 1.0,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "axes.labelcolor": "black",
        "axes.edgecolor": "black",
        "axes.facecolor": "white",
        "axes.prop_cycle": plt.cycler(color=RSE_COLORS),
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.size": 4,
        "ytick.major.size": 4,
        "xtick.minor.size": 2,
        "ytick.minor.size": 2,
        "xtick.top": True,
        "ytick.right": True,
        "xtick.color": "black",
        "ytick.color": "black",
        "xtick.labelcolor": "black",
        "ytick.labelcolor": "black",
        "legend.frameon": True,
        "legend.framealpha": 0.8,
        "legend.fontsize": 10,
        "legend.edgecolor": "0.8",
        "errorbar.capsize": 3,
        "savefig.dpi": 300,
        "savefig.format": "tiff",
        "savefig.bbox": "tight",
        "image.cmap": "viridis",
    }


def apply_rse_style() -> dict[str, Any]:
    """Apply RSE journal style globally via ``plt.rcParams``.

    Returns
    -------
    dict
        The applied rcParams dictionary.

    """
    import matplotlib.pyplot as plt

    params = _rse_rcparams()
    plt.rcParams.update(params)  # ty: ignore[no-matching-overload]
    return params


def rse_context():
    """Return a context manager that temporarily applies RSE style.

    Usage::

        with rse_context():
            fig, ax = plt.subplots()
            ...

    """
    import matplotlib.pyplot as plt

    return plt.rc_context(_rse_rcparams())  # ty: ignore[invalid-argument-type]


def rse_style(func):
    """Decorator that applies RSE style to a plotting function.

    The decorated function is expected to return ``(fig, axes)``.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        import matplotlib.pyplot as plt

        with plt.rc_context(_rse_rcparams()):  # ty: ignore[invalid-argument-type]
            fig, axes = func(*args, **kwargs)
            fix_figure_for_dark_mode(fig)
            return fig, axes

    return wrapper


def style_colorbar(cbar, label: str | None = None):
    """Apply RSE-compatible styling to a matplotlib colorbar.

    Parameters
    ----------
    cbar : matplotlib.colorbar.Colorbar
        Colorbar instance to style.
    label : str, optional
        Label text.

    Returns
    -------
    matplotlib.colorbar.Colorbar
        The styled colorbar.

    """
    cbar.ax.tick_params(colors="black", labelcolor="black", labelsize=10)
    if label:
        cbar.set_label(label, color="black", size=12)
    for spine in cbar.ax.spines.values():
        spine.set_edgecolor("black")
    return cbar


def fix_figure_for_dark_mode(fig, axes=None):
    """Set explicit white backgrounds so figures render correctly in dark IDEs.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        Figure to fix.
    axes : list, optional
        Specific axes; defaults to all axes in the figure.

    Returns
    -------
    matplotlib.figure.Figure

    """
    fig.patch.set_facecolor("white")
    fig.patch.set_edgecolor("white")
    if axes is None:
        axes = fig.get_axes()
    for ax in axes:
        ax.set_facecolor("white")
        for spine in ax.spines.values():
            spine.set_color("black")
        ax.tick_params(colors="black", labelcolor="black")
    return fig


# ==============================================================================
# Colorscale — cross-framework colormap conversion
# ==============================================================================


@dataclass
class Colorscale:
    """Unified colorscale that converts between Plotly and matplotlib.

    Parameters
    ----------
    name : str
        Colorscale identifier.
    stops : list of (float, str)
        Normalized ``[(position, color), ...]`` where position is 0–1.

    """

    name: str
    stops: list[tuple[float, str]] = field(default_factory=list)

    @classmethod
    def from_matplotlib(cls, cmap_name: str, n_colors: int = 256) -> Colorscale:
        """Create from a matplotlib colormap name."""
        import matplotlib.pyplot as plt

        cmap = plt.get_cmap(cmap_name)
        stops = [
            (
                i / (n_colors - 1),
                f"rgb({int(c[0] * 255)},{int(c[1] * 255)},{int(c[2] * 255)})",
            )
            for i, c in ((j, cmap(j / (n_colors - 1))) for j in range(n_colors))
        ]
        return cls(name=cmap_name, stops=stops)

    @classmethod
    def from_colors(cls, colors: list[str], name: str = "custom") -> Colorscale:
        """Create from a list of color strings (hex, named, or rgb())."""
        n = len(colors)
        stops = [(i / (n - 1), c) for i, c in enumerate(colors)]
        return cls(name=name, stops=stops)

    def to_matplotlib(self, n_colors: int = 256):
        """Convert to a matplotlib ``LinearSegmentedColormap``.

        Returns
        -------
        matplotlib.colors.Colormap

        """
        from matplotlib.colors import LinearSegmentedColormap, to_rgb

        colors = []
        for _pos, color_str in self.stops:
            if color_str.startswith("rgb"):
                match = re.match(r"rgb\((\d+),?\s*(\d+),?\s*(\d+)\)", color_str)
                if match:
                    r, g, b = (int(x) for x in match.groups())
                    colors.append((r / 255, g / 255, b / 255))
                else:
                    raise ValueError(f"Invalid rgb format: {color_str}")
            else:
                colors.append(to_rgb(color_str))
        return LinearSegmentedColormap.from_list(self.name, colors, N=n_colors)

    def to_plotly(self) -> list[tuple[float, str]]:
        """Return Plotly-compatible colorscale list."""
        return list(self.stops)
