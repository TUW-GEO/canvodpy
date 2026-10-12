# canvod-viz

Publication-quality and interactive visualization for GNSS VOD hemispher

ical data.

## Features

### 2D Visualization (matplotlib)
- **Publication-quality polar plots** with full control over styling
- **Multiple grid type support**: equal-area, equal-angle, HTM, geodesic, Fibonacci
- **Flexible colormaps** and styling options
- **High-resolution export** for papers and presentations

### 3D Visualization (plotly)
- **Interactive hemisphere plots** with rotation, zoom, pan
- **Scatter and mesh rendering** options
- **HTML export** for sharing and presentations
- **Hover information** for data exploration

### Unified API
- **Single interface** for both 2D and 3D visualizations
- **Consistent styling** across rendering backends
- **Quick comparison plots** side-by-side
- **Publication and interactive presets**

## Installation

```bash
# From workspace root
uv pip install canvod-viz

# Or install in development mode
cd packages/canvod-viz
uv pip install -e .
```

## Quick Start

### 2D Polar Visualization

```python
from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer2D
import numpy as np

# Create grid
grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)

# Generate sample data
data = np.random.rand(grid.ncells)

# Create visualizer
viz = HemisphereVisualizer2D(grid)

# Plot
fig, ax = viz.plot_grid_patches(
    data=data,
    title="VOD Distribution",
    cmap='viridis',
    save_path="vod_2d.png",
    dpi=300
)
```

### 3D Interactive Visualization

```python
from canvod.viz import HemisphereVisualizer3D

# Create visualizer
viz3d = HemisphereVisualizer3D(grid)

# Create interactive plot
fig = viz3d.plot_hemisphere_surface(
    data=data,
    title="Interactive VOD Explorer",
    colorscale='Plasma',
    opacity=0.8
)

# Display in browser
fig.show()

# Or save as HTML
fig.write_html("vod_3d.html")
```

### Unified API

```python
from canvod.viz import HemisphereVisualizer

# Single visualizer for both 2D and 3D
viz = HemisphereVisualizer(grid)

# Create 2D plot
fig_2d, ax_2d = viz.plot_2d(
    data=data,
    title="2D Polar View",
    save_path="polar.png"
)

# Create 3D plot
fig_3d = viz.plot_3d(
    data=data,
    title="3D Interactive View"
)
fig_3d.show()
```

## Advanced Usage

### Custom Styling

```python
from canvod.viz import PolarPlotStyle, create_publication_style

# Create custom 2D style
custom_style = PolarPlotStyle(
    cmap='plasma',
    edgecolor='darkgray',
    linewidth=0.3,
    figsize=(12, 12),
    dpi=600,
    colorbar_label='VOD',
    show_degree_labels=True,
    theta_labels=[0, 15, 30, 45, 60, 75, 90]
)

fig, ax = viz.plot_2d(data=data, style=custom_style)
```

### Publication-Ready Figures

```python
# Use preset publication style
fig, ax = viz.create_publication_figure(
    data=data,
    title="VOD Distribution Over ExampleSite Site",
    save_path="paper_figure_3.png",
    dpi=600,
    colorbar_label='VOD'
)
```

### Interactive Explorer

```python
# Create interactive explorer with dark theme
fig = viz.create_interactive_explorer(
    data=data,
    title="VOD Data Explorer",
    dark_mode=True,
    save_html="explorer.html"
)
```

### Side-by-Side Comparison

```python
# Create both 2D and 3D for comparison
(fig_2d, ax_2d), fig_3d = viz.create_comparison_plot(
    data=data,
    title_2d="2D Polar Projection",
    title_3d="3D Hemisphere View",
    save_2d="comparison_2d.png",
    save_3d="comparison_3d.html"
)
```

### Mesh Visualization

```python
# Show cell boundaries in 3D
fig_mesh = viz.plot_3d_mesh(
    data=data,
    title="VOD Mesh View",
    opacity=0.7,
    show_edges=True
)
fig_mesh.show()
```

## Styling Presets

### Publication Style

Optimized for papers and reports:
- High DPI (300-600)
- Clean white background
- Thin grid lines
- Sans-serif fonts
- Conservative colors

```python
from canvod.viz import create_publication_style

pub_style = create_publication_style()
viz.set_style(pub_style)
fig, ax = viz.plot_2d(data=data)
```

### Interactive Style

Optimized for screen viewing and exploration:
- Dark mode option
- Vibrant colors
- Larger markers
- Interactive hover
- HTML export

```python
from canvod.viz import create_interactive_style

int_style = create_interactive_style(dark_mode=True)
viz.set_style(int_style)
fig = viz.plot_3d(data=data)
```

## Supported Grid Types

- **Equal Area**: Latitude bands with equal solid angle
- **Equal Angle**: Regular θ/φ spacing
- **HTM**: Hierarchical Triangular Mesh
- **Geodesic**: Subdivided icosahedron
- **Fibonacci**: Spiral point distribution

## API Reference

### HemisphereVisualizer2D

2D matplotlib visualizer for publication-quality plots.

**Key Methods:**
- `plot_grid_patches()`: Main plotting method
- `_extract_grid_patches()`: Convert grid to 2D polygons
- `_apply_polar_styling()`: Apply axis styling

### HemisphereVisualizer3D

3D plotly visualizer for interactive exploration.

**Key Methods:**
- `plot_hemisphere_surface()`: 3D scatter/surface plot
- `plot_hemisphere_scatter()`: 3D scatter plot
- `plot_cell_mesh()`: 3D mesh with cell boundaries

### HemisphereVisualizer

Unified visualizer combining 2D and 3D.

**Key Methods:**
- `plot_2d()`: Create 2D plot
- `plot_3d()`: Create 3D plot
- `plot_3d_mesh()`: Create 3D mesh
- `create_publication_figure()`: Publication preset
- `create_interactive_explorer()`: Interactive preset
- `create_comparison_plot()`: Side-by-side views
- `set_style()`: Update unified styling

### PolarPlotStyle

Configuration for 2D matplotlib plots.

**Key Parameters:**
- `cmap`: Colormap name
- `edgecolor`: Cell edge color
- `linewidth`: Edge width
- `figsize`: Figure size (width, height)
- `dpi`: Resolution
- `colorbar_label`: Colorbar label text
- `show_grid`: Display polar grid
- `theta_labels`: Elevation angle labels

### PlotStyle

Unified styling for both 2D and 3D.

**Key Parameters:**
- `colormap/colorscale`: Colors for 2D/3D
- `dark_mode`: Use dark theme
- `font_family/font_size`: Typography
- `opacity`: 3D transparency
- `edge_linewidth`: Cell edge width

**Methods:**
- `to_polar_style()`: Convert to 2D style
- `to_plotly_layout()`: Convert to 3D layout

## Documentation

[Full documentation](https://canvodpy.eu/packages/viz/overview/)

## Examples

See `docs/` for Jupyter notebook examples:
- Basic 2D visualization
- Interactive 3D exploration
- Publication figure creation
- Custom styling
- Multi-panel comparisons

## Development

### Running Tests

```bash
cd packages/canvod-viz
uv run pytest
```

### Type Checking

```bash
uv run ty check .
```

### Building Documentation

```bash
cd docs
myst build --html
```

## Dependencies

- `matplotlib>=3.8.0`: 2D plotting
- `plotly>=5.18.0`: 3D interactive plots
- `numpy>=1.26.0`: Array operations
- `canvod-grids>=0.1.0`: Grid structures

## License

Apache License 2.0

## Author & Affiliation

**Nicolas François Bader**
Climate and Environmental Remote Sensing Research Unit (CLIMERS)
Department of Geodesy and Geoinformation
TU Wien (Vienna University of Technology)

Email: support@canvodpy.eu
Web: [https://www.tuwien.at/en/mg/geo/climers](https://www.tuwien.at/en/mg/geo/climers)

## Citation

If you use this package in your research, please cite:

```bibtex
@software{canvod_viz,
  title = {canvod-viz: Visualization Tools for GNSS-T Analysis},
  author = {Bader, Nicolas F.},
  year = {2026},
  institution = {TU Wien},
  url = {https://github.com/nfb2021/canvodpy}
}
```

## Related Packages

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem:
- [`canvod-readers`](https://pypi.org/project/canvod-readers/): GNSS data readers (RINEX/SBF)
- [`canvod-auxiliary`](https://pypi.org/project/canvod-auxiliary/): Ephemeris augmentation
- [`canvod-grids`](https://pypi.org/project/canvod-grids/): Equal-area hemisphere grids
- [`canvod-vod`](https://pypi.org/project/canvod-vod/): VOD calculations
- [`canvod-store`](https://pypi.org/project/canvod-store/): Icechunk storage
- [`canvodpy`](https://pypi.org/project/canvodpy/): Umbrella package
