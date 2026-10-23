# canvod-viz

2D (matplotlib) and 3D (plotly) plots of hemisphere grids and gridded VOD.

## Where things live

| Path (under `src/canvod/viz/`) | What |
|---|---|
| `visualizer.py` | `HemisphereVisualizer`: one object for 2D and 3D plots of a grid |
| `hemisphere_2d.py` | Polar plots |
| `hemisphere_3d.py` | `HemisphereVisualizer3D`: surface, wireframe, overlays, axes |
| `styles.py` | Plot styles (publication, interactive) |
| `widgets/` | `HemisphereSelector2D` and 3D (anywidget), optional extra `widgets`; JS and CSS next to them |

Background: `docs/packages/viz/overview.md`.

## Every 3D hemisphere plot has all three

1. **Cell boundaries**: `plot_hemisphere_surface(..., show_wireframe=True)`
   (the default). Without them cells can't be told apart.
2. **E/N/Up axes**: `add_custom_axes(fig)`, with plotly's own scene axes
   switched off (`visible=False`), so only one set of axes shows.
3. **Elevation rings and meridians**: `add_spherical_overlays(fig)`.

A 3D plot without these is incomplete, like a plot without axis labels.
The demo's 3D grid gallery notebook shows the pattern. When adding a grid
type's 3D rendering, add its branch to `_extract_wireframe_lines` too.

## Tests

```bash
just test-package canvod-viz
```
