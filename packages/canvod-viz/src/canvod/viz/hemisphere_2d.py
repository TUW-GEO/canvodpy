"""2D hemisphere visualization using matplotlib for publication-quality plots.

Provides polar projection plotting of hemispherical grids with various
rendering methods.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon

from canvod.viz.styles import PolarPlotStyle

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.projections.polar import PolarAxes

    from canvod.grids import HemiGrid


def _theta_to_rho(theta: np.ndarray, projection: str) -> np.ndarray:
    """Map zenith angle theta (radians, 0 at zenith, pi/2 at horizon) to plot radius rho.

    orthographic : rho = sin(theta) -- a straight-down view of the 3D
        hemisphere; cells compress toward the horizon at the rim.
    equidistant : rho = theta / (pi/2) -- a true polar plot with elevation
        rings evenly spaced (the conventional GNSS skyplot convention).
    """
    if projection == "orthographic":
        return np.sin(theta)
    elif projection == "equidistant":
        return theta / (np.pi / 2)
    raise ValueError(
        f"Unknown projection: {projection!r}. Use 'orthographic' or 'equidistant'."
    )


class HemisphereVisualizer2D:
    """2D hemisphere visualization using matplotlib.

    Creates publication-quality polar projection plots of hemispherical grids.
    Supports multiple grid types and rendering methods.

    Parameters
    ----------
    grid : HemiGrid
        Hemisphere grid to visualize

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import HemisphereVisualizer2D
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> viz = HemisphereVisualizer2D(grid)
    >>> fig, ax = viz.plot_grid_patches(data=vod_data, title="VOD Distribution")
    >>> plt.savefig("vod_plot.png", dpi=300, bbox_inches='tight')

    """

    def __init__(self, grid: HemiGrid) -> None:
        """Initialize 2D hemisphere visualizer.

        Parameters
        ----------
        grid : HemiGrid
            Hemisphere grid to visualize

        """
        self.grid = grid
        self._patches_cache: list[Polygon] | None = None
        self._cell_indices_cache: np.ndarray | None = None
        self._patches_cache_projection: str | None = None

    def plot_grid_patches(
        self,
        data: np.ndarray | None = None,
        style: PolarPlotStyle | None = None,
        ax: Axes | None = None,
        save_path: Path | str | None = None,
        **style_kwargs: Any,
    ) -> tuple[Figure, Axes]:
        """Plot hemisphere grid as colored patches in polar projection.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell. If None, plots uniform grid.
        style : PolarPlotStyle, optional
            Styling configuration. If None, uses defaults.
        ax : matplotlib.axes.Axes, optional
            Existing polar axes to plot on. If None, creates new figure.
        save_path : Path or str, optional
            If provided, saves figure to this path
        **style_kwargs
            Override individual style parameters

        Returns
        -------
        fig : matplotlib.figure.Figure
            Figure object
        ax : matplotlib.axes.Axes
            Polar axes with plot

        Examples
        --------
        >>> fig, ax = viz.plot_grid_patches(
        ...     data=vod_data,
        ...     title="VOD Distribution",
        ...     cmap='plasma',
        ...     save_path="output.png"
        ... )

        """
        # Initialize style
        if style is None:
            style = PolarPlotStyle(**style_kwargs)
        else:
            # Override style with kwargs
            for key, value in style_kwargs.items():
                if hasattr(style, key):
                    setattr(style, key, value)

        # Create figure if needed
        if ax is None:
            fig, ax = plt.subplots(
                figsize=style.figsize, dpi=style.dpi, subplot_kw={"projection": "polar"}
            )
        else:
            fig = cast("Figure", ax.figure)
        ax_polar = cast("PolarAxes", ax)

        # Get patches for grid
        patches, cell_indices = self._extract_grid_patches(style.projection)

        # Map data to patches
        patch_data = self._map_data_to_patches(data, cell_indices)

        # Determine color limits
        vmin = style.vmin if style.vmin is not None else np.nanmin(patch_data)
        vmax = style.vmax if style.vmax is not None else np.nanmax(patch_data)

        # Create patch collection
        pc = PatchCollection(
            patches,
            cmap=style.cmap,
            edgecolor=style.edgecolor,
            linewidth=style.linewidth,
            alpha=style.alpha,
        )
        pc.set_array(np.ma.masked_invalid(patch_data))
        pc.set_clim(vmin, vmax)

        # Add to axes
        ax.add_collection(pc)

        # Style polar axes
        self._apply_polar_styling(ax_polar, style)

        # Add colorbar
        cbar = fig.colorbar(
            pc,
            ax=ax,
            shrink=style.colorbar_shrink,
            pad=style.colorbar_pad,
        )
        cbar.set_label(style.colorbar_label, fontsize=style.colorbar_fontsize)

        # Set title
        if style.title:
            ax.set_title(style.title, y=1.08, fontsize=14)

        # Save if requested
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(
                save_path,
                dpi=style.dpi,
                bbox_inches="tight",
                facecolor="white",
                edgecolor="none",
            )

        return fig, ax

    def _extract_grid_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract 2D polygon patches from hemispherical grid.

        Parameters
        ----------
        projection : {'orthographic', 'equidistant'}, default 'orthographic'
            Radial mapping from zenith angle to plot radius (see
            ``PolarPlotStyle.projection``).

        Returns
        -------
        patches : list of Polygon
            Matplotlib polygon patches
        cell_indices : np.ndarray
            Corresponding cell indices in grid

        """
        if projection not in ("orthographic", "equidistant"):
            # Validated up front rather than inside _theta_to_rho: several
            # per-cell extraction loops below wrap their body in a broad
            # `except (..., ValueError)` and would otherwise silently
            # swallow an invalid projection name instead of raising it.
            raise ValueError(
                f"Unknown projection: {projection!r}. "
                "Use 'orthographic' or 'equidistant'."
            )

        # Use cache if available and built for the same projection
        if (
            self._patches_cache is not None
            and self._cell_indices_cache is not None
            and self._patches_cache_projection == projection
        ):
            return self._patches_cache, self._cell_indices_cache

        grid_type = self.grid.grid_type.lower()

        _rectangular_types = {"equal_area", "equal_angle", "equirectangular"}
        if grid_type in _rectangular_types:
            patches, indices = self._extract_rectangular_patches(projection)
        elif grid_type == "htm":
            patches, indices = self._extract_htm_patches(projection)
        elif grid_type == "geodesic":
            patches, indices = self._extract_geodesic_patches(projection)
        elif grid_type == "healpix":
            patches, indices = self._extract_healpix_patches(projection)
        elif grid_type == "fibonacci":
            patches, indices = self._extract_fibonacci_patches(projection)
        else:
            raise ValueError(f"Unsupported grid type: {grid_type}")

        # Cache results
        self._patches_cache = patches
        self._cell_indices_cache = indices
        self._patches_cache_projection = projection

        return patches, indices

    def _extract_rectangular_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract patches from rectangular/equal-area grid."""
        patches = []
        cell_indices = []

        # Access the grid DataFrame from GridData
        grid_df = self.grid.grid

        for idx, row in enumerate(grid_df.iter_rows(named=True)):
            phi_min = row["phi_min"]
            phi_max = row["phi_max"]
            theta_min = row["theta_min"]
            theta_max = row["theta_max"]

            # Skip cells beyond hemisphere
            if theta_min > np.pi / 2:
                continue

            rho_min = _theta_to_rho(theta_min, projection)
            rho_max = _theta_to_rho(theta_max, projection)

            # Create rectangular patch in polar coordinates
            vertices = np.array(
                [
                    [phi_min, rho_min],
                    [phi_max, rho_min],
                    [phi_max, rho_max],
                    [phi_min, rho_max],
                ]
            )

            patches.append(Polygon(vertices, closed=True))
            cell_indices.append(idx)

        return patches, np.array(cell_indices)

    def _extract_htm_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract triangular patches from HTM grid."""
        patches = []
        cell_indices = []

        # Access the grid DataFrame from GridData
        grid_df = self.grid.grid

        for idx, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                # HTM stores vertices as columns htm_vertex_0, htm_vertex_1,
                # htm_vertex_2.
                v0 = np.array(row["htm_vertex_0"], dtype=float)
                v1 = np.array(row["htm_vertex_1"], dtype=float)
                v2 = np.array(row["htm_vertex_2"], dtype=float)

                vertices_3d = np.array([v0, v1, v2])
                x, y, z = (
                    vertices_3d[:, 0],
                    vertices_3d[:, 1],
                    vertices_3d[:, 2],
                )

                # Convert to spherical coordinates
                r = np.sqrt(x**2 + y**2 + z**2)
                theta = np.arccos(np.clip(z / r, -1, 1))
                # unwrap (not mod 2*pi) so a triangle straddling the
                # phi=0/2*pi seam gets contiguous polygon vertices instead
                # of two clustered near 0 and one near 2*pi, which would
                # otherwise draw an edge streaking across the whole plot.
                phi = np.unwrap(np.arctan2(y, x))

                # Skip if beyond hemisphere
                if np.all(theta > np.pi / 2):
                    continue

                rho = _theta_to_rho(theta, projection)
                vertices_2d = np.column_stack([phi, rho])

                patches.append(Polygon(vertices_2d, closed=True))
                cell_indices.append(idx)

            except KeyError, TypeError:
                # Skip cells that don't have proper HTM vertex data
                continue

        return patches, np.array(cell_indices)

    def _extract_geodesic_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract triangular patches from geodesic grid.

        The ``geodesic_vertices`` column stores vertex **indices** into the
        shared ``grid.vertices`` coordinate array (shape ``(n_vertices, 3)``).
        """
        patches = []
        cell_indices = []

        grid_df = self.grid.grid
        shared_vertices = self.grid.vertices  # (n_vertices, 3) or None

        if shared_vertices is None or "geodesic_vertices" not in grid_df.columns:
            # No vertex data — fall back to bounding-box rectangles
            return self._extract_rectangular_patches(projection)

        for idx, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                v_indices = np.array(row["geodesic_vertices"], dtype=int)
                if len(v_indices) < 3:
                    continue

                # Look up actual 3D coordinates from shared vertex array
                verts_3d = shared_vertices[v_indices]  # (3, 3)
                x, y, z = verts_3d[:, 0], verts_3d[:, 1], verts_3d[:, 2]

                r = np.sqrt(x**2 + y**2 + z**2)
                theta = np.arccos(np.clip(z / r, -1, 1))
                # See _extract_htm_patches: unwrap keeps seam-straddling
                # triangles contiguous instead of streaking across the plot.
                phi = np.unwrap(np.arctan2(y, x))

                if np.all(theta > np.pi / 2):
                    continue

                rho = _theta_to_rho(theta, projection)
                vertices_2d = np.column_stack([phi, rho])
                patches.append(Polygon(vertices_2d, closed=True))
                cell_indices.append(idx)

            except IndexError, KeyError, TypeError, ValueError:
                continue

        return patches, np.array(cell_indices)

    def _extract_healpix_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract patches from HEALPix grid via ``healpy.boundaries``."""
        try:
            import healpy as hp
        except ImportError as e:
            raise ImportError(
                "healpy is required for HEALPix 2D visualization. "
                "Install with: uv add healpy"
            ) from e

        patches = []
        cell_indices = []
        grid_df = self.grid.grid
        nside = int(grid_df["healpix_nside"][0])

        for idx, row in enumerate(grid_df.iter_rows(named=True)):
            ipix = int(row["healpix_ipix"])
            # boundaries returns shape (3, n_vertices) in Cartesian
            boundary = hp.boundaries(nside, ipix, step=4)
            x, y, z = boundary[0], boundary[1], boundary[2]

            # Skip pixels entirely below horizon
            if np.all(z < -0.01):
                continue

            r = np.sqrt(x**2 + y**2 + z**2)
            theta = np.arccos(np.clip(z / r, -1, 1))
            # See _extract_htm_patches: unwrap keeps seam-straddling pixels
            # contiguous instead of streaking across the plot.
            phi = np.unwrap(np.arctan2(y, x))

            # Keep only vertices in upper hemisphere
            mask = theta <= np.pi / 2 + 0.01
            if not np.any(mask):
                continue

            rho = _theta_to_rho(theta, projection)
            vertices_2d = np.column_stack([phi, rho])
            patches.append(Polygon(vertices_2d, closed=True))
            cell_indices.append(idx)

        return patches, np.array(cell_indices)

    def _extract_fibonacci_patches(
        self, projection: str = "orthographic"
    ) -> tuple[list[Polygon], np.ndarray]:
        """Extract patches from Fibonacci grid using Voronoi regions."""
        patches = []
        cell_indices = []
        grid_df = self.grid.grid
        voronoi = self.grid.voronoi  # scipy.spatial.SphericalVoronoi or None

        if voronoi is None or "voronoi_region" not in grid_df.columns:
            # No Voronoi data — fall back to bounding-box rectangles
            return self._extract_rectangular_patches(projection)

        for idx, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                region_indices = row["voronoi_region"]
                if region_indices is None or len(region_indices) < 3:
                    continue

                verts_3d = voronoi.vertices[region_indices]
                x, y, z = verts_3d[:, 0], verts_3d[:, 1], verts_3d[:, 2]

                # Skip cells entirely below horizon
                if np.all(z < -0.01):
                    continue

                r = np.sqrt(x**2 + y**2 + z**2)
                theta = np.arccos(np.clip(z / r, -1, 1))
                # See _extract_htm_patches: unwrap keeps seam-straddling
                # cells contiguous instead of streaking across the plot.
                phi = np.unwrap(np.arctan2(y, x))

                # Vertices are already in polygon winding order from
                # sort_vertices_of_regions() — use directly.
                rho = _theta_to_rho(theta, projection)
                vertices_2d = np.column_stack([phi, rho])
                patches.append(Polygon(vertices_2d, closed=True))
                cell_indices.append(idx)

            except IndexError, KeyError, TypeError, ValueError:
                continue

        return patches, np.array(cell_indices)

    def _map_data_to_patches(
        self,
        data: np.ndarray | None,
        cell_indices: np.ndarray,
    ) -> np.ndarray:
        """Map data values to patches.

        Parameters
        ----------
        data : np.ndarray or None
            Data per grid cell
        cell_indices : np.ndarray
            Cell indices corresponding to patches

        Returns
        -------
        np.ndarray
            Data values for each patch

        """
        if data is None:
            return np.ones(len(cell_indices)) * 0.5

        return data[cell_indices]

    def _apply_polar_styling(
        self,
        ax: PolarAxes,
        style: PolarPlotStyle,
    ) -> None:
        """Apply styling to polar axes.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Polar axes to style
        style : PolarPlotStyle
            Styling configuration

        """
        # Set rho limits (0 to 1 for hemisphere projection)
        ax.set_ylim(0, 1.0)

        # Configure polar axis orientation
        ax.set_theta_zero_location("N")  # North at top
        ax.set_theta_direction(-1)  # Clockwise (azimuth convention)

        # Add degree labels on radial axis
        if style.show_degree_labels:
            theta_labels = style.theta_labels
            rho_ticks = [
                _theta_to_rho(np.radians(t), style.projection) for t in theta_labels
            ]
            ax.set_yticks(rho_ticks)
            ax.set_yticklabels([f"{t}°" for t in theta_labels])

        # Grid styling
        if style.show_grid:
            ax.grid(
                True,
                alpha=style.grid_alpha,
                linestyle=style.grid_linestyle,
                color="gray",
            )
        else:
            ax.grid(False)


# =============================================================================
# Convenience Functions
# =============================================================================


def visualize_grid(
    grid: HemiGrid,
    data: np.ndarray | None = None,
    style: PolarPlotStyle | None = None,
    **kwargs: Any,
) -> tuple[Figure, Axes]:
    """Visualize hemispherical grid in 2D polar projection.

    Convenience function providing simple interface to 2D visualization.

    Parameters
    ----------
    grid : HemiGrid
        Grid to visualize
    data : np.ndarray, optional
        Data values per cell. If None, plots uniform grid.
    style : PolarPlotStyle, optional
        Styling configuration. If None, uses defaults.
    **kwargs
        Additional style parameter overrides

    Returns
    -------
    fig : matplotlib.figure.Figure
        Figure object
    ax : matplotlib.axes.Axes
        Polar axes object

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import visualize_grid
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> fig, ax = visualize_grid(grid, data=vod_data, cmap='viridis')
    >>> plt.savefig("vod_plot.png", dpi=300)

    """
    viz = HemisphereVisualizer2D(grid)
    return viz.plot_grid_patches(data=data, style=style, **kwargs)


def add_tissot_indicatrix(
    ax: Axes,
    grid: HemiGrid,
    radius_deg: float | None = None,
    n_sample: int | None = None,
    facecolor: str = "gold",
    alpha: float = 0.6,
    edgecolor: str = "black",
    linewidth: float = 0.5,
    projection: str = "orthographic",
) -> Axes:
    """Add Tissot's indicatrix circles to existing polar plot.

    Adds equal-sized circles to visualize grid distortion. In equal-area grids,
    circles should appear roughly equal-sized. Variation indicates distortion.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Existing polar axis to add circles to
    grid : HemiGrid
        Grid instance
    radius_deg : float, optional
        Angular radius of circles in degrees. If None, auto-calculated
        as angular_resolution / 8.
    n_sample : int, optional
        Subsample cells (use every nth cell) for performance.
        If None, shows all cells.
    facecolor : str, default 'gold'
        Fill color for circles
    alpha : float, default 0.6
        Transparency (0=transparent, 1=opaque)
    edgecolor : str, default 'black'
        Edge color for circles
    linewidth : float, default 0.5
        Edge line width
    projection : {'orthographic', 'equidistant'}, default 'orthographic'
        Must match the projection used for the underlying ``ax`` (see
        ``PolarPlotStyle.projection``), otherwise circles will be
        misaligned with the grid patches.

    Returns
    -------
    ax : matplotlib.axes.Axes
        Modified axis with Tissot circles added

    Examples
    --------
    >>> fig, ax = visualize_grid(grid, data=vod_data)
    >>> add_tissot_indicatrix(ax, grid, radius_deg=3, n_sample=5)
    >>> plt.savefig("vod_with_tissot.png")

    """
    # Auto-calculate radius if not provided
    if radius_deg is None:
        if hasattr(grid, "angular_resolution"):
            radius_deg = grid.angular_resolution / 8
        else:
            theta_vals = grid.grid["theta"].to_numpy()
            theta_spacing = np.median(np.diff(np.sort(np.unique(theta_vals))))
            radius_deg = np.rad2deg(theta_spacing) / 8

    radius_rad = np.deg2rad(radius_deg)

    # Generate circle points on sphere
    n_circle_points = 32
    circle_angles = np.linspace(0, 2 * np.pi, n_circle_points, endpoint=False)

    cell_count = 0
    grid_df = grid.grid

    # Every grid type gets a true spherical circle constructed in 3D and
    # projected -- exact under whichever theta->rho projection is used here.
    # Rectangular grids (equal_area, equal_angle, equirectangular) used to
    # take a separate ellipse-approximation path (an axis-aligned ellipse in
    # (phi, rho), locally linearized around each cell center). That
    # approximation breaks down badly near the pole: as theta_center -> 0,
    # its azimuthal width term (2*radius_rad/sin(theta_center)) blows up
    # well before reaching the "true circle wraps the whole azimuth" regime,
    # rendering near-pole cells as a streak across the entire plot instead
    # of a small circle. The 3D construct-and-project approach below has no
    # such singularity -- it degenerates gracefully into a genuine
    # near-full-revolution polygon exactly when the physical circle actually
    # is that large relative to its distance from the pole.
    for i, row in enumerate(grid_df.iter_rows(named=True)):
        if n_sample is not None and i % n_sample != 0:
            continue

        phi_center = row["phi"]
        theta_center = row["theta"]

        if theta_center > np.pi / 2:
            continue

        # Convert cell center to 3D Cartesian
        x_c = np.sin(theta_center) * np.cos(phi_center)
        y_c = np.sin(theta_center) * np.sin(phi_center)
        z_c = np.cos(theta_center)
        center_3d = np.array([x_c, y_c, z_c])

        # Create tangent vectors
        if theta_center < 0.01:
            tangent_1 = np.array([1, 0, 0])
            tangent_2 = np.array([0, 1, 0])
        else:
            tangent_phi = np.array([-np.sin(phi_center), np.cos(phi_center), 0])
            tangent_phi = tangent_phi / np.linalg.norm(tangent_phi)

            tangent_theta = np.array(
                [
                    np.cos(theta_center) * np.cos(phi_center),
                    np.cos(theta_center) * np.sin(phi_center),
                    -np.sin(theta_center),
                ]
            )
            tangent_theta = tangent_theta / np.linalg.norm(tangent_theta)

            tangent_1 = tangent_phi
            tangent_2 = tangent_theta

        # Create circle on sphere surface
        circle_3d = []
        for angle in circle_angles:
            offset = radius_rad * (
                np.cos(angle) * tangent_1 + np.sin(angle) * tangent_2
            )
            point_3d = center_3d + offset
            norm = np.linalg.norm(point_3d)
            if norm > 1e-10:
                point_3d = point_3d / norm
            circle_3d.append(point_3d)

        circle_3d = np.array(circle_3d)

        # Project to 2D polar coordinates
        x_2d, y_2d, z_2d = circle_3d[:, 0], circle_3d[:, 1], circle_3d[:, 2]
        theta_2d = np.arccos(np.clip(z_2d, -1, 1))
        # arctan2's branch cut at +/-pi would otherwise split a circle
        # straddling that seam into vertices ~2*pi apart, drawing a
        # streak across the whole plot when connected into a polygon.
        # circle_angles walks the loop in order, so unwrap stitches the
        # projected sequence back into a contiguous span (and correctly
        # leaves a genuine full revolution around a near-pole cell
        # untouched, since that's a real 2*pi sweep, not a seam jump).
        phi_2d = np.unwrap(np.arctan2(y_2d, x_2d))

        # Convert to polar plot coordinates
        rho_2d = _theta_to_rho(theta_2d, projection)
        angle_2d = phi_2d

        vertices_2d = np.column_stack([angle_2d, rho_2d])

        poly = Polygon(
            vertices_2d,
            facecolor=facecolor,
            alpha=alpha,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
        ax.add_patch(poly)
        cell_count += 1

    # Update title
    current_title = ax.get_title()
    if current_title:
        ax.set_title(f"{current_title} + Tissot ({cell_count} circles)")
    else:
        ax.set_title(f"Tissot's Indicatrix - {grid.grid_type} ({cell_count} circles)")

    return ax
