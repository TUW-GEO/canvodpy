# canvod-viz

## Purpose

The `canvod-viz` package provides 2D and 3D hemispheric visualization for GNSS-T grids, SNR data, and VOD results. It wraps Matplotlib (publication-quality polar plots) and Plotly (interactive 3D hemispheres) behind a unified API.

---

## Components

<div class="grid cards" markdown>

-   :fontawesome-solid-circle-half-stroke: &nbsp; **HemisphereVisualizer**

    ---

    Unified entry point combining both 2D and 3D backends.
    Swap between publication and interactive modes with one method call.

-   :fontawesome-solid-chart-area: &nbsp; **HemisphereVisualizer2D**

    ---

    Matplotlib polar projection plots. Patch-based rendering of grid cells.
    Publication-quality output at configurable DPI.

-   :fontawesome-solid-cube: &nbsp; **HemisphereVisualizer3D**

    ---

    Plotly interactive 3D hemispheres. Pan, zoom, rotate in the browser.
    One-call HTML export for sharing.

-   :fontawesome-solid-circle-dot: &nbsp; **Tissot Indicatrix**

    ---

    `add_tissot_indicatrix` overlays angular distortion circles on 2D
    plots to evaluate grid cell shape fidelity.

</div>

---

## Usage

=== "Unified API (recommended)"

    ```python
    from canvod.grids import create_hemigrid
    from canvod.viz import HemisphereVisualizer

    grid = create_hemigrid("equal_area", angular_resolution=10.0)
    viz = HemisphereVisualizer(grid)

    # Publication-quality 2D
    fig_2d, ax_2d = viz.plot_2d(data=vod_data, title="VOD Distribution")

    # Interactive 3D
    fig_3d = viz.plot_3d(data=vod_data, title="Interactive VOD")
    fig_3d.show()
    ```

=== "Convenience functions"

    ```python
    from canvod.viz import visualize_grid, visualize_grid_3d, add_tissot_indicatrix

    fig, ax = visualize_grid(grid, data=vod_data, cmap="viridis")
    add_tissot_indicatrix(ax, grid, n_sample=5)

    fig_3d = visualize_grid_3d(grid, data=vod_data)
    ```

=== "Publication output"

    ```python
    viz = HemisphereVisualizer(grid)
    viz.set_style(create_publication_style())

    fig, ax = viz.create_publication_figure(
        data=vod_data,
        title="VOD Distribution",
        save_path="figure_3.png",
        dpi=600,
    )
    ```

=== "Interactive export"

    ```python
    viz.set_style(create_interactive_style(dark_mode=True))

    fig = viz.create_interactive_explorer(
        data=vod_data,
        dark_mode=True,
        save_html="explorer.html",
    )
    ```

=== "Side-by-side comparison"

    ```python
    (fig_2d, ax_2d), fig_3d = viz.create_comparison_plot(data=vod_data)
    ```

!!! note "Cells without data"
    Cells without data (NaN) are not part of the color scale: 2D plots
    leave them white, the 3D views draw them in `nan_color` (default
    `"lightgray"`), so they never look like the minimum value.
    `plot_3d_mesh` draws HTM grids one triangle at a time and every other
    grid like `plot_3d`.

`add_spherical_overlays(fig, elevation_rings=...)` takes elevation
angles in degrees (0 = horizon, 90 = zenith); the default draws rings at 0,
15, 30, 45, 60, and 75 degrees.

---

## Styling

| Style factory | Use case |
| ------------- | -------- |
| `create_publication_style()` | Print-ready figures, configurable DPI, white background |
| `create_interactive_style()` | Browser-ready Plotly, dark mode option |
| `create_rse_style()` | Remote Sensing of Environment journal guidelines |

Each returns a `PlotStyle`, passed to `viz.set_style()`; `PlotStyle.to_polar_style()` gives the `PolarPlotStyle` the 2D functions take.

### RSE journal style

Publication-quality styling matching *Remote Sensing of Environment* guidelines,
with Arial or Helvetica fonts, 300 DPI, inward ticks, colorblind-friendly palette (Wong, 2011).

=== "Context manager"

    ```python
    from canvod.viz import rse_context

    with rse_context():
        fig, ax = plt.subplots()
        ax.plot(x, y)
    ```

=== "Decorator"

    ```python
    from canvod.viz import rse_style


    @rse_style
    def make_figure():
        fig, ax = plt.subplots()
        ax.plot(x, y)
        return fig, [ax]
    ```

=== "Global apply"

    ```python
    from canvod.viz import apply_rse_style

    apply_rse_style()  # modifies plt.rcParams globally
    ```

### Colorscale

Colormaps converted between Matplotlib and Plotly:

```python
from canvod.viz import Colorscale

cs = Colorscale.from_matplotlib("viridis", n_colors=64)
plotly_cs = cs.to_plotly()  # [(0.0, 'rgb(...)'), ...]
mpl_cmap = cs.to_matplotlib()  # LinearSegmentedColormap

cs2 = Colorscale.from_colors(["#0072B2", "#D55E00", "#009E73"])
```

---

## Interactive grid exploration

The `demo/15_grid_exploration.py` marimo notebook shows interactive
exploration of per-cell VOD on the hemispheric grid, with synthetic data
(real per-cell time series come from
`canvod.store.AnalysisStorage.load_percell_timeseries()`):

- **3D view**: Plotly Scatter3d with click-to-select cells (anywidget)
- **2D view**: canvas polar projection with hover tooltips (anywidget)
- **Reactive stats**: selected cells display in a table with mean, std, count, and coverage
- **Time series**: per-cell VOD time series plotted for selected cells

```bash
just open-notebook 15_grid_exploration.py
```

---

## Interactive selectors in notebooks

`canvod.viz.widgets` provides two interactive hemisphere selectors for
marimo (and Jupyter) notebooks, built on anywidget. Click the cells of a
hemisphere grid to select them; hover a cell for its info. The selectors
need the optional extra:

```bash
pip install "canvod-viz[widgets]"
```

```bash
uv add "canvod-viz[widgets]"
```

Example (the 3D selector from `demo/15_grid_exploration.py`):

```python
import marimo as mo
from canvod.viz.widgets import HemisphereSelector3D

hemisphere_3d = mo.ui.anywidget(
    HemisphereSelector3D(
        cell_centers_x=cell_x.tolist(),
        cell_centers_y=cell_y.tolist(),
        cell_centers_z=cell_z.tolist(),
        cell_values=values.tolist(),
        cell_labels=labels,
        colorscale="Viridis",
        marker_size=6,
    )
)
mo.output.replace(hemisphere_3d)
```

`HemisphereSelector2D` takes `cell_theta`, `cell_phi`, `cell_values` and
`cell_labels` instead. Both expose `selected_cell_ids` (the indices of the
selected cells) and `hovered_cell_id`.

---

## Dependencies

!!! info "Backends"

    - **Matplotlib** (2D) and **Plotly** (3D), installed with `canvod-viz`
    - **canvod-grids**: grid geometry, installed with `canvod-viz`
    - **anywidget**: only for the interactive hemisphere selectors in the
      marimo notebooks; installed only with the optional extra
      `widgets` (`pip install "canvod-viz[widgets]"`), not by default
