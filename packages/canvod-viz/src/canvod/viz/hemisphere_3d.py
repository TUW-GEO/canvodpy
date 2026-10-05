"""3D hemisphere visualization using plotly for interactive exploration.

Provides interactive 3D sphere surface plots with zoom, pan, and rotation capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from canvod.viz.styles import PlotStyle

if TYPE_CHECKING:
    from canvod.grids import HemiGrid


#: Color of cells without data (NaN), like matplotlib's ``set_bad``.
DEFAULT_NAN_COLOR = "lightgray"


def _split_missing(trace: go.Mesh3d | go.Scatter3d, nan_color: str) -> list:
    """Draw the cells without data (NaN) of ``trace`` in ``nan_color``.

    Plotly has no color for NaN: a NaN intensity is drawn in the lowest
    color of the scale, so a cell without data looks like the minimum.
    The cells with data stay in ``trace``; the others move to a second
    trace of one fixed color, which the color scale does not include.
    """
    if isinstance(trace, go.Mesh3d):
        intensity = np.asarray(trace.intensity, dtype=float)
        tri = np.column_stack([trace.i, trace.j, trace.k])
        missing = np.isnan(intensity[tri]).any(axis=1)
        if not missing.any():
            return [trace]
        kept = go.Mesh3d(trace)
        kept.update(
            i=tri[~missing, 0],
            j=tri[~missing, 1],
            k=tri[~missing, 2],
            cmin=np.nanmin(intensity) if (~missing).any() else None,
            cmax=np.nanmax(intensity) if (~missing).any() else None,
        )
        empty = go.Mesh3d(
            x=trace.x,
            y=trace.y,
            z=trace.z,
            i=tri[missing, 0],
            j=tri[missing, 1],
            k=tri[missing, 2],
            color=nan_color,
            opacity=trace.opacity,
            flatshading=True,
            name="No data",
            hoverinfo="name",
        )
        return [kept, empty] if (~missing).any() else [empty]
    values = np.asarray(trace.marker.color, dtype=float)
    missing = np.isnan(values)
    if not missing.any():
        return [trace]
    xyz = [np.asarray(trace[c]) for c in ("x", "y", "z")]
    kept = go.Scatter3d(trace)
    kept.update(
        x=xyz[0][~missing],
        y=xyz[1][~missing],
        z=xyz[2][~missing],
        marker_color=values[~missing],
        text=np.asarray(trace.text)[~missing] if trace.text is not None else None,
    )
    empty = go.Scatter3d(
        x=xyz[0][missing],
        y=xyz[1][missing],
        z=xyz[2][missing],
        mode="markers",
        marker=dict(size=trace.marker.size, color=nan_color),
        name="No data",
        hoverinfo="name",
    )
    return [kept, empty]


class HemisphereVisualizer3D:
    """3D hemisphere visualization using plotly.

    Creates interactive 3D plots with rotation, zoom, and hover capabilities.
    Designed for exploratory data analysis and presentations.

    Parameters
    ----------
    grid : HemiGrid
        Hemisphere grid to visualize

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import HemisphereVisualizer3D
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> viz = HemisphereVisualizer3D(grid)
    >>> fig = viz.plot_hemisphere_surface(data=vod_data, title="Interactive VOD")
    >>> fig.show()

    """

    def __init__(self, grid: HemiGrid) -> None:
        """Initialize 3D hemisphere visualizer.

        Parameters
        ----------
        grid : HemiGrid
            Hemisphere grid to visualize

        """
        self.grid = grid

    def plot_hemisphere_surface(
        self,
        data: np.ndarray | None = None,
        style: PlotStyle | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        opacity: float = 0.8,
        show_wireframe: bool = True,
        show_colorbar: bool = True,
        width: int = 800,
        height: int = 600,
        nan_color: str = DEFAULT_NAN_COLOR,
        **kwargs: Any,
    ) -> go.Figure:
        """Create 3D surface plot on hemisphere with actual cell patches.

        Renders grid cells as colored 3D patches (not just points).

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell. If None, shows grid structure.
        style : PlotStyle, optional
            Styling configuration. If None, uses defaults.
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        opacity : float, default 0.8
            Surface opacity (0=transparent, 1=opaque)
        show_wireframe : bool, default True
            Show grid lines on surface
        show_colorbar : bool, default True
            Display colorbar
        width : int, default 800
            Figure width in pixels
        height : int, default 600
            Figure height in pixels
        nan_color : str, default 'lightgray'
            Color of cells without data (NaN); not part of the color scale.
        **kwargs
            Additional plotly trace parameters

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive 3D figure with cell patches

        Examples
        --------
        >>> fig = viz.plot_hemisphere_surface(
        ...     data=vod_data,
        ...     title="VOD Distribution 3D",
        ...     colorscale='Plasma',
        ...     opacity=0.9
        ... )
        >>> fig.write_html("vod_3d.html")

        """
        # Initialize style
        if style is None:
            style = PlotStyle()
        else:
            colorscale = style.colorscale

        # Render grid based on type
        grid_type = self.grid.grid_type.lower()

        if grid_type in ["equal_area", "equal_angle", "equirectangular"]:
            trace = self._render_rectangular_cells(
                data,
                colorscale,
                opacity,
                show_colorbar,
            )
        elif grid_type == "htm":
            trace = self._render_htm_cells(data, colorscale, opacity, show_colorbar)
        elif grid_type == "geodesic":
            trace = self._render_geodesic_cells(
                data, colorscale, opacity, show_colorbar
            )
        elif grid_type == "healpix":
            trace = self._render_healpix_cells(data, colorscale, opacity, show_colorbar)
        elif grid_type == "fibonacci":
            trace = self._render_fibonacci_cells(
                data, colorscale, opacity, show_colorbar
            )
        else:
            # Fallback to scatter for unknown types
            trace = self._render_scatter_fallback(
                data,
                colorscale,
                opacity,
                show_colorbar,
            )

        fig_data = _split_missing(trace, nan_color) if data is not None else [trace]
        if show_wireframe:
            fig_data.append(self._extract_wireframe_lines())
        fig = go.Figure(data=fig_data)

        # Apply layout
        layout_config = style.to_plotly_layout() if style else {}
        layout_config.update(
            {
                "title": title or "Hemisphere 3D",
                "scene": dict(
                    aspectmode="data",
                    # visible=False (not just showbackground=False) --
                    # otherwise Plotly's native axis line, ticks, and
                    # "East"/"North"/"Up" title still render, showing
                    # meaningless raw sin/cos-projected tick values
                    # alongside add_custom_axes()'s own E/N/Up labels.
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                    zaxis=dict(visible=False),
                    bgcolor=layout_config.get("plot_bgcolor", "white"),
                ),
                "width": width,
                "height": height,
                "margin": dict(l=0, r=0, b=0, t=40),
            }
        )

        fig.update_layout(**layout_config)

        return fig

    def _render_rectangular_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render rectangular grid cells as 3D mesh patches."""
        grid_df = self.grid.grid

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []

        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                phi_min, phi_max = row["phi_min"], row["phi_max"]
                theta_min, theta_max = row["theta_min"], row["theta_max"]

                # Skip if beyond hemisphere
                if theta_min > np.pi / 2:
                    continue

                # Create 4 corners of rectangular cell
                phi_corners = [phi_min, phi_max, phi_max, phi_min]
                theta_corners = [theta_min, theta_min, theta_max, theta_max]

                patch_x, patch_y, patch_z = [], [], []
                for phi, theta in zip(phi_corners, theta_corners):
                    # Convert to 3D Cartesian
                    x = np.sin(theta) * np.sin(phi)
                    y = np.sin(theta) * np.cos(phi)
                    z = np.cos(theta)
                    patch_x.append(x)
                    patch_y.append(y)
                    patch_z.append(z)

                all_x.extend(patch_x)
                all_y.extend(patch_y)
                all_z.extend(patch_z)

                # Color value for this cell
                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 4)

                # Two triangles per rectangle
                all_i.extend([vertex_count, vertex_count])
                all_j.extend([vertex_count + 1, vertex_count + 2])
                all_k.extend([vertex_count + 2, vertex_count + 3])

                vertex_count += 4

            except KeyError, IndexError:
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name=f"{self.grid.grid_type.title()} Grid",
        )

    def _render_htm_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render HTM triangular cells as 3D mesh."""
        grid_df = self.grid.grid

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []

        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                v0 = np.array(row["htm_vertex_0"], dtype=float)
                v1 = np.array(row["htm_vertex_1"], dtype=float)
                v2 = np.array(row["htm_vertex_2"], dtype=float)

                # Skip if beyond hemisphere
                if np.all([v[2] < 0 for v in [v0, v1, v2]]):
                    continue

                all_x.extend([v0[1], v1[1], v2[1]])
                all_y.extend([v0[0], v1[0], v2[0]])
                all_z.extend([v0[2], v1[2], v2[2]])

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 3)

                # One triangle per cell
                all_i.append(vertex_count)
                all_j.append(vertex_count + 1)
                all_k.append(vertex_count + 2)

                vertex_count += 3

            except KeyError, TypeError, ValueError:
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name=f"{self.grid.grid_type.title()} Grid",
        )

    def _render_geodesic_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d | go.Scatter3d:
        """Render geodesic triangular cells as 3D mesh.

        Reads ``geodesic_vertices`` (3 vertex indices per cell) and looks up
        3D Cartesian coordinates from the shared ``grid.vertices`` array.
        """
        grid_df = self.grid.grid
        shared_vertices = self.grid.vertices

        if shared_vertices is None or "geodesic_vertices" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                v_indices = np.array(row["geodesic_vertices"], dtype=int)
                if len(v_indices) < 3:
                    continue

                verts = shared_vertices[v_indices]  # (3, 3)

                if np.all(verts[:, 2] < 0):
                    continue

                all_x.extend(verts[:, 1].tolist())
                all_y.extend(verts[:, 0].tolist())
                all_z.extend(verts[:, 2].tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 3)

                all_i.append(vertex_count)
                all_j.append(vertex_count + 1)
                all_k.append(vertex_count + 2)
                vertex_count += 3

            except KeyError, IndexError, TypeError, ValueError:
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="Geodesic Grid",
        )

    def _render_healpix_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d | go.Scatter3d:
        """Render HEALPix curvilinear cells as 3D mesh.

        Uses ``healpy.boundaries()`` to obtain true pixel boundaries,
        then fan-triangulates each quadrilateral pixel.
        """
        try:
            import healpy as hp
        except ImportError:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        grid_df = self.grid.grid
        if "healpix_ipix" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        nside = int(grid_df["healpix_nside"][0])
        step = 4  # 4 sub-points per edge → 16 boundary vertices

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                ipix = int(row["healpix_ipix"])
                boundary = hp.boundaries(nside, ipix, step=step)
                x, y, z = boundary[1], boundary[0], boundary[2]

                if np.all(z < -0.01):
                    continue

                n_verts = len(x)
                all_x.extend(x.tolist())
                all_y.extend(y.tolist())
                all_z.extend(z.tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * n_verts)

                # Fan triangulation from first vertex
                for j in range(1, n_verts - 1):
                    all_i.append(vertex_count)
                    all_j.append(vertex_count + j)
                    all_k.append(vertex_count + j + 1)

                vertex_count += n_verts

            except KeyError, IndexError, TypeError, ValueError:
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="HEALPix Grid",
        )

    def _render_fibonacci_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d | go.Scatter3d:
        """Render Fibonacci Voronoi cells as 3D mesh.

        Reads ``voronoi_region`` (variable-length vertex index list) and
        looks up 3D coordinates from ``grid.voronoi.vertices``.  The
        vertex indices are already in correct polygon winding order
        (``SphericalVoronoi.sort_vertices_of_regions()`` was called
        during grid construction), so no re-sorting is needed.
        Fan-triangulates each polygon for ``go.Mesh3d``.
        """
        grid_df = self.grid.grid
        voronoi = self.grid.voronoi

        if voronoi is None or "voronoi_region" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                region_indices = row["voronoi_region"]
                if region_indices is None or len(region_indices) < 3:
                    continue

                verts = voronoi.vertices[region_indices]

                if np.all(verts[:, 2] < -0.01):
                    continue

                # Vertices are already in polygon winding order from
                # sort_vertices_of_regions() — use directly.
                n_verts = len(verts)

                all_x.extend(verts[:, 1].tolist())
                all_y.extend(verts[:, 0].tolist())
                all_z.extend(verts[:, 2].tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * n_verts)

                # Fan triangulation from first vertex
                for j in range(1, n_verts - 1):
                    all_i.append(vertex_count)
                    all_j.append(vertex_count + j)
                    all_k.append(vertex_count + j + 1)

                vertex_count += n_verts

            except KeyError, IndexError, TypeError, ValueError:
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="Fibonacci Grid",
        )

    def _render_scatter_fallback(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Scatter3d:
        """Fallback scatter plot for unsupported grid types."""
        grid_df = self.grid.grid
        theta = grid_df["theta"].to_numpy()
        phi = grid_df["phi"].to_numpy()

        # Convert to 3D Cartesian coordinates
        x = np.sin(theta) * np.sin(phi)
        y = np.sin(theta) * np.cos(phi)
        z = np.cos(theta)

        # Prepare data values
        if data is None:
            values = np.ones(self.grid.ncells) * 0.5
        else:
            values = data

        # Filter hemisphere only
        hemisphere_mask = theta <= np.pi / 2
        x = x[hemisphere_mask]
        y = y[hemisphere_mask]
        z = z[hemisphere_mask]
        values = values[hemisphere_mask]

        return go.Scatter3d(
            x=x,
            y=y,
            z=z,
            mode="markers",
            marker=dict(
                size=6,
                color=values,
                colorscale=colorscale,
                opacity=opacity,
                colorbar=dict(title="Value") if show_colorbar else None,
                cmin=np.nanmin(values),
                cmax=np.nanmax(values),
            ),
            text=[f"Cell {i}<br>Value: {v:.3f}" for i, v in enumerate(values)],
            hoverinfo="text",
        )

    def _extract_wireframe_lines(self) -> go.Scatter3d:
        """Build one Scatter3d trace outlining every cell's boundary.

        Mirrors the per-grid-type vertex extraction each `_render_*_cells`
        method already does, but emits closed perimeter line loops
        (None-separated segments, one trace total) instead of a
        triangulated Mesh3d -- this is what `show_wireframe` in
        `plot_hemisphere_surface` actually draws (previously a no-op: the
        parameter was declared and documented but never wired to
        anything, so cell boundaries were never visible in 3D).
        """
        grid_type = self.grid.grid_type.lower()
        grid_df = self.grid.grid

        xs: list[float | None] = []
        ys: list[float | None] = []
        zs: list[float | None] = []

        def _add_ring(verts_xyz: np.ndarray) -> None:
            closed = np.vstack([verts_xyz, verts_xyz[:1]])
            xs.extend([*closed[:, 0].tolist(), None])
            ys.extend([*closed[:, 1].tolist(), None])
            zs.extend([*closed[:, 2].tolist(), None])

        if grid_type in ("equal_area", "equal_angle", "equirectangular"):
            for row in grid_df.iter_rows(named=True):
                theta_min, theta_max = row["theta_min"], row["theta_max"]
                if theta_min > np.pi / 2:
                    continue
                phi_min, phi_max = row["phi_min"], row["phi_max"]
                phi_c = [phi_min, phi_max, phi_max, phi_min]
                theta_c = [theta_min, theta_min, theta_max, theta_max]
                verts = np.array(
                    [
                        [np.sin(t) * np.sin(p), np.sin(t) * np.cos(p), np.cos(t)]
                        for p, t in zip(phi_c, theta_c)
                    ]
                )
                _add_ring(verts)

        elif grid_type == "htm":
            for row in grid_df.iter_rows(named=True):
                try:
                    v0 = np.array(row["htm_vertex_0"], dtype=float)
                    v1 = np.array(row["htm_vertex_1"], dtype=float)
                    v2 = np.array(row["htm_vertex_2"], dtype=float)
                    if np.all([v[2] < 0 for v in [v0, v1, v2]]):
                        continue
                    verts = np.array([[v[1], v[0], v[2]] for v in (v0, v1, v2)])
                    _add_ring(verts)
                except KeyError, TypeError, ValueError:
                    continue

        elif grid_type == "geodesic":
            shared_vertices = self.grid.vertices
            if shared_vertices is not None and "geodesic_vertices" in grid_df.columns:
                for row in grid_df.iter_rows(named=True):
                    try:
                        v_indices = np.array(row["geodesic_vertices"], dtype=int)
                        if len(v_indices) < 3:
                            continue
                        v = shared_vertices[v_indices]
                        if np.all(v[:, 2] < 0):
                            continue
                        verts = np.column_stack([v[:, 1], v[:, 0], v[:, 2]])
                        _add_ring(verts)
                    except KeyError, IndexError, TypeError, ValueError:
                        continue

        elif grid_type == "healpix":
            # Pre-declared as Any so ty doesn't narrow hp's type from the
            # successful-import branch alone -- that narrowing is what
            # made a plain `except ImportError: hp = None` flip between a
            # real invalid-assignment error (healpy installed, ty resolves
            # the module type) and an unused-ignore-comment error (healpy
            # absent, ty can't resolve the import) depending on the
            # environment ty runs in, rather than the code itself.
            hp: Any = None
            try:
                import healpy as hp
            except ImportError:
                pass
            if hp is not None and "healpix_ipix" in grid_df.columns:
                nside = int(grid_df["healpix_nside"][0])
                for row in grid_df.iter_rows(named=True):
                    try:
                        ipix = int(row["healpix_ipix"])
                        boundary = hp.boundaries(nside, ipix, step=4)
                        x, y, z = boundary[1], boundary[0], boundary[2]
                        if np.all(z < -0.01):
                            continue
                        verts = np.column_stack([x, y, z])
                        _add_ring(verts)
                    except KeyError, IndexError, TypeError, ValueError:
                        continue

        elif grid_type == "fibonacci":
            voronoi = self.grid.voronoi
            if voronoi is not None and "voronoi_region" in grid_df.columns:
                for row in grid_df.iter_rows(named=True):
                    try:
                        region_indices = row["voronoi_region"]
                        if region_indices is None or len(region_indices) < 3:
                            continue
                        v = voronoi.vertices[region_indices]
                        if np.all(v[:, 2] < -0.01):
                            continue
                        verts = np.column_stack([v[:, 1], v[:, 0], v[:, 2]])
                        _add_ring(verts)
                    except KeyError, IndexError, TypeError, ValueError:
                        continue

        return go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line=dict(color="rgba(20,20,20,0.55)", width=2),
            hoverinfo="skip",
            showlegend=False,
            name="Cell boundaries",
        )

    def plot_hemisphere_scatter(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        marker_size: int | np.ndarray = 6,
        opacity: float = 0.8,
        width: int = 800,
        height: int = 600,
    ) -> go.Figure:
        """Create 3D scatter plot of cell centers.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        marker_size : int or np.ndarray, default 6
            Marker size (constant or per-point array)
        opacity : float, default 0.8
            Marker opacity
        width : int, default 800
            Figure width
        height : int, default 600
            Figure height

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive scatter plot

        """
        # Note: Now renders as mesh, not scatter points
        # Marker size parameter is ignored
        fig = self.plot_hemisphere_surface(
            data=data,
            title=title,
            colorscale=colorscale,
            opacity=opacity,
            width=width,
            height=height,
        )

        return fig

    def plot_cell_mesh(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        opacity: float = 0.7,
        show_edges: bool = True,
        width: int = 800,
        height: int = 600,
        nan_color: str = DEFAULT_NAN_COLOR,
    ) -> go.Figure:
        """Create 3D mesh plot showing cell boundaries.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        opacity : float, default 0.7
            Mesh opacity
        show_edges : bool, default True
            Show cell edges
        width : int, default 800
            Figure width
        height : int, default 600
            Figure height
        nan_color : str, default 'lightgray'
            Color of cells without data (NaN); not part of the color scale.

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive mesh plot

        Notes
        -----
        HTM grids are drawn as one trace per triangle. All other grids are
        drawn like :meth:`plot_hemisphere_surface` (one mesh of all cells),
        with ``show_edges`` as its ``show_wireframe``.

        """
        grid_type = self.grid.grid_type.lower()
        if grid_type != "htm":
            return self.plot_hemisphere_surface(
                data=data,
                title=title or "Hemisphere Mesh 3D",
                colorscale=colorscale,
                opacity=opacity,
                show_wireframe=show_edges,
                width=width,
                height=height,
                nan_color=nan_color,
            )

        traces = []

        # Prepare data
        if data is None:
            values = np.ones(self.grid.ncells) * 0.5
        else:
            values = data

        grid_df = self.grid.grid

        # Check if grid supports mesh rendering
        if "htm_vertex_0" in grid_df.columns:
            # HTM triangular mesh
            for idx, row in enumerate(grid_df.iter_rows(named=True)):
                try:
                    v0 = np.array(row["htm_vertex_0"], dtype=float)
                    v1 = np.array(row["htm_vertex_1"], dtype=float)
                    v2 = np.array(row["htm_vertex_2"], dtype=float)

                    vertices = np.array([v0, v1, v2])

                    # Check hemisphere
                    z_coords = vertices[:, 2]
                    if np.all(z_coords < 0):
                        continue

                    # Normalize color value; no data gets nan_color
                    if np.isnan(values[idx]):
                        color_rgb = nan_color
                    else:
                        span = np.nanmax(values) - np.nanmin(values)
                        color_val = (
                            (values[idx] - np.nanmin(values)) / span if span else 0.5
                        )
                        color_rgb = sample_colorscale(colorscale, [color_val])[0]

                    # Create triangle mesh; vertices are (north, east, up),
                    # the plot's x axis is east (as in the other 3D views)
                    trace = go.Mesh3d(
                        x=vertices[:, 1],
                        y=vertices[:, 0],
                        z=vertices[:, 2],
                        i=[0],
                        j=[1],
                        k=[2],
                        color=color_rgb,
                        opacity=opacity,
                        flatshading=True,
                        showscale=False,
                        hoverinfo="skip",
                    )
                    traces.append(trace)
                except KeyError, TypeError, ValueError:
                    continue
        else:
            raise ValueError(
                "HTM grid has no 'htm_vertex_0' column; cannot draw its "
                "cells. Build it with create_hemigrid('htm', ...)."
            )

        if show_edges and traces:
            traces.append(self._extract_wireframe_lines())

        # Add colorbar trace
        if values is not None and len(traces) > 0:
            dummy_trace = go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                marker=dict(
                    size=0.1,
                    color=[np.nanmin(values), np.nanmax(values)],
                    colorscale=colorscale,
                    colorbar=dict(title="Value"),
                ),
                showlegend=False,
                hoverinfo="skip",
            )
            traces.append(dummy_trace)

        fig = go.Figure(data=traces)

        # Update layout
        fig.update_layout(
            title=title or "Hemisphere Mesh 3D",
            scene=dict(
                aspectmode="data",
                # See plot_hemisphere_surface: visible=False fully hides
                # the native axis (line, ticks, title), not just the
                # background pane -- meaningless raw sin/cos tick values
                # would otherwise show alongside add_custom_axes().
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                zaxis=dict(visible=False),
            ),
            width=width,
            height=height,
            margin=dict(l=0, r=0, b=0, t=40),
        )

        return fig

    def add_spherical_overlays(
        self,
        fig: go.Figure,
        elevation_rings: list[int] | None = None,
        meridians_deg: list[int] | None = None,
        overlay_color: str = "lightgray",
        line_width: float = 1,
    ) -> go.Figure:
        """Add elevation rings and meridians to 3D plot.

        Parameters
        ----------
        fig : plotly.graph_objects.Figure
            Existing 3D figure to add overlays to
        elevation_rings : list of int, optional
            Elevation angles in degrees above the horizon (0 = horizon,
            90 = zenith). Default: [0, 15, 30, 45, 60, 75]
        meridians_deg : list of int, optional
            Meridian angles in degrees. Default: [0, 45, 90, 135, 180, 225, 270, 315]
        overlay_color : str, default 'lightgray'
            Color for overlay lines
        line_width : float, default 1
            Width of overlay lines

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Modified figure with overlays

        Raises
        ------
        ValueError
            If an elevation is outside [0, 90] degrees.

        """
        if elevation_rings is None:
            elevation_rings = [0, 15, 30, 45, 60, 75]
        if meridians_deg is None:
            meridians_deg = list(range(0, 360, 45))
        outside = [e for e in elevation_rings if not 0 <= e <= 90]
        if outside:
            msg = (
                f"elevation_rings must be elevations in [0, 90] degrees "
                f"(0 = horizon, 90 = zenith), got {outside}"
            )
            raise ValueError(msg)

        # Elevation rings: polar angle theta = 90 deg - elevation
        for elevation_deg in elevation_rings:
            theta = np.radians(90 - elevation_deg)
            phi = np.linspace(0, 2 * np.pi, 200)
            x = np.sin(theta) * np.sin(phi)
            y = np.sin(theta) * np.cos(phi)
            z = np.full_like(phi, np.cos(theta))
            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                    line=dict(color=overlay_color, width=line_width),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Meridians
        for phi_deg in meridians_deg:
            phi = np.radians(phi_deg)
            theta = np.linspace(0, np.pi / 2, 100)
            x = np.sin(theta) * np.sin(phi)
            y = np.sin(theta) * np.cos(phi)
            z = np.cos(theta)
            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                    line=dict(color=overlay_color, width=line_width),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        return fig

    def add_custom_axes(
        self,
        fig: go.Figure,
        axis_length: float = 1.2,
        axis_color: str = "black",
        show_labels: bool = True,
    ) -> go.Figure:
        """Add custom coordinate axes with labels.

        Parameters
        ----------
        fig : plotly.graph_objects.Figure
            Existing 3D figure
        axis_length : float, default 1.2
            Length of axis lines
        axis_color : str, default 'black'
            Color for axes
        show_labels : bool, default True
            Show axis labels (E, N, Z)

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Modified figure with custom axes

        """
        # Axis lines
        axes_lines = [
            dict(x=[0, axis_length], y=[0, 0], z=[0, 0]),  # East
            dict(x=[0, 0], y=[0, axis_length], z=[0, 0]),  # North
            dict(x=[0, 0], y=[0, 0], z=[0, axis_length]),  # Up
        ]

        for axis in axes_lines:
            fig.add_trace(
                go.Scatter3d(
                    x=axis["x"],
                    y=axis["y"],
                    z=axis["z"],
                    mode="lines",
                    line=dict(color=axis_color, width=6),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Arrowheads
        arrow_tip = axis_length + 0.05
        arrow_size = 0.1
        for pos, direction in zip(
            [[arrow_tip, 0, 0], [0, arrow_tip, 0], [0, 0, arrow_tip]],
            [[arrow_size, 0, 0], [0, arrow_size, 0], [0, 0, arrow_size]],
        ):
            fig.add_trace(
                go.Cone(
                    x=[pos[0]],
                    y=[pos[1]],
                    z=[pos[2]],
                    u=[direction[0]],
                    v=[direction[1]],
                    w=[direction[2]],
                    sizemode="absolute",
                    sizeref=arrow_size,
                    anchor="tip",
                    showscale=False,
                    colorscale=[[0, axis_color], [1, axis_color]],
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Labels
        if show_labels:
            label_offset = axis_length + 0.15
            for label in [
                dict(x=label_offset, y=0, z=0, text="E"),
                dict(x=0, y=label_offset, z=0, text="N"),
                dict(x=0, y=0, z=label_offset, text="Z"),
            ]:
                fig.add_trace(
                    go.Scatter3d(
                        x=[label["x"]],
                        y=[label["y"]],
                        z=[label["z"]],
                        mode="text",
                        text=[label["text"]],
                        textfont=dict(size=16, color=axis_color),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

        return fig


# =============================================================================
# Convenience Functions
# =============================================================================


def visualize_grid_3d(
    grid: HemiGrid,
    data: np.ndarray | None = None,
    title: str | None = None,
    colorscale: str = "Viridis",
    add_overlays: bool = False,
    add_axes: bool = False,
    **kwargs: Any,
) -> go.Figure:
    """Visualize hemispherical grid in 3D interactive plot.

    Convenience function providing simple interface to 3D visualization.

    Parameters
    ----------
    grid : HemiGrid
        Grid to visualize
    data : np.ndarray, optional
        Data values per cell
    title : str, optional
        Plot title
    colorscale : str, default 'Viridis'
        Plotly colorscale name
    add_overlays : bool, default False
        Add elevation rings and meridians
    add_axes : bool, default False
        Add custom coordinate axes
    **kwargs
        Additional parameters passed to plot_hemisphere_surface

    Returns
    -------
    fig : plotly.graph_objects.Figure
        Interactive 3D figure

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import visualize_grid_3d
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> fig = visualize_grid_3d(
    ...     grid,
    ...     data=vod_data,
    ...     title="VOD 3D",
    ...     add_overlays=True
    ... )
    >>> fig.show()

    """
    viz = HemisphereVisualizer3D(grid)
    fig = viz.plot_hemisphere_surface(
        data=data, title=title, colorscale=colorscale, **kwargs
    )

    if add_overlays:
        viz.add_spherical_overlays(fig)

    if add_axes:
        viz.add_custom_axes(fig)

    return fig
