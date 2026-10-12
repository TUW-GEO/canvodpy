# canvod-viz

## Purpose

The `canvod-viz` package provides 2D and 3D hemispheric visualization for GNSS-T grids, SNR data, and VOD results. It wraps matplotlib (publication-quality polar plots) and plotly (interactive 3D hemispheres) behind a unified API.

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

    `add_tissot_indicatrix` — overlay angular distortion circles on 2D
    plots to evaluate grid cell shape fidelity.

</div>

---

## Usage

=== "Unified API (recommended)"

    ```python
    from canvod.grids import create_hemigrid
    from canvod.viz import HemisphereVisualizer

    grid = create_hemigrid("equal_area", angular_resolution=10.0)
    viz  = HemisphereVisualizer(grid)

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

---

## Styling

| Style factory | Use case |
| ------------- | -------- |
| `create_publication_style()` | Print-ready figures, configurable DPI, white background |
| `create_interactive_style()` | Browser-ready Plotly, dark mode option |
| `create_rse_style()` | Remote Sensing of Environment journal guidelines |

Both return a `PlotStyle` / `PolarPlotStyle` object passed to `viz.set_style()`.

### RSE Journal Style

Publication-quality styling matching *Remote Sensing of Environment* guidelines:
Arial/Helvetica fonts, 300 DPI, inward ticks, colorblind-friendly palette (Wong, 2011).

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

Cross-framework colormap conversion between matplotlib, Plotly, and palettable:

```python
from canvod.viz import Colorscale

cs = Colorscale.from_matplotlib("viridis", n_colors=64)
plotly_cs = cs.to_plotly()     # [(0.0, 'rgb(...)'), ...]
mpl_cmap  = cs.to_matplotlib() # LinearSegmentedColormap

cs2 = Colorscale.from_colors(["#0072B2", "#D55E00", "#009E73"])
```

---

## Interactive Grid Exploration

The `demo/15_grid_exploration.py` marimo notebook provides interactive
exploration of per-cell VOD data on the hemispheric grid:

- **3D view** — Plotly Scatter3d with click-to-select cells (anywidget)
- **2D view** — Canvas polar projection with hover tooltips (anywidget)
- **Reactive stats** — selected cells display in a table with mean, std, count, coverage
- **Timeseries** — per-cell VOD timeseries plotted for selected cells

```bash
uv run marimo edit demo/15_grid_exploration.py
```

---

## Dependencies

!!! info "Optional backends"

    - **matplotlib** — required for `HemisphereVisualizer2D` and all 2D functions
    - **plotly** — required for `HemisphereVisualizer3D` and all 3D functions
    - **anywidget** — required for interactive hemisphere selectors in marimo notebooks
    - **canvod-grids** — always required for grid geometry

    Neither backend is a hard dependency of `canvod-viz` itself; import errors are
    raised only when the corresponding visualizer is instantiated.

---

!!! example "Try it"
    [14 · Visualization](../../notebooks/_build/14_visualization.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/14_visualization.py)
