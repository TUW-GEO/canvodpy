# canvod-grids

Hemisphere grids (cells of the sky seen from the receiver), assignment of
observations to cells, and analysis on gridded VOD.

## Where things live

| Path (under `src/canvod/grids/`) | What |
|---|---|
| `__init__.py` | `create_hemigrid`: build a grid by type and resolution |
| `core/` | `GridData`, `BaseGridBuilder` ABC, grid types |
| `grids_impl/` | One builder per grid type (equal-area is the default for GNSS-T) |
| `operations.py` | `add_cell_ids_to_ds_fast`: the one cell assignment |
| `aggregation.py`, `analysis/` | Per-cell aggregation and VOD analysis |

Background: `docs/packages/grids/overview.md`.

## Invariants

- **One cell assignment**: `add_cell_ids_to_ds_fast` (the cell that
  contains the observation, per grid type in `_internal/cell_lookup.py`;
  float64, NaN outside the grid). Never the nearest cell center: near a
  corner it belongs to a neighboring cell. `GridAssignment` in canvod-ops calls it. Its other
  variants are deprecated; don't add a new one.
- Outlier filtering (Hampel and similar) was removed on purpose; it does
  not belong in canvodpy.
- canvod-grids does not import canvod-store. Storing grids and analysis
  results lives in canvod-store (`store_grid`, `load_grid`,
  `AnalysisStorage`); the names of the same functions here are deprecated
  wrappers.

## Tests

```bash
just test-package canvod-grids
```

The HEALPix grid needs `healpy`, which is in this package's `optional`
dependency group (no Windows wheels); without it those cases skip.
