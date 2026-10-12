#!/usr/bin/env bash
# Export the demo/ marimo notebooks for embedding in the docs site.
#
# All notebooks export via `marimo export html`: a real Python execution
# against real test data at build time, frozen into static HTML with the
# source code included by default (--include-code is marimo's default).
#
# `marimo export html-wasm` (live, in-browser via Pyodide) was tried first
# but rejected: its default "run" mode hides code entirely (app-mode UX),
# and neither `--show-code` nor `--mode edit` fit -- code is the whole
# point of these notebooks, and duplicating it into markdown text to force
# visibility would make the notebooks clunky to maintain. Static HTML
# already shows code, so there is no live/static split to make here.
#
# See dev/notebook_docs_integration_plan.md for the full writeup.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$REPO_ROOT/demo"
OUT_DIR="$REPO_ROOT/docs/notebooks/_build"

NOTEBOOKS=(
    01_cli_pipeline
    02_configuration
    03_convenience_speedrun
    04_naming_convention
    05_rinex_reading
    06_sbf_reading
    07_satellite_catalog
    08_ephemeris_coordinates
    09_hemispheric_grids
    10_vod_retrieval
    14_visualization
    15_grid_exploration
    16_grid_3d_gallery
    17_api_overview
    18_site_pipeline
    19_workflow_single_day
    20_workflow_batch_processing
)

# The store notebooks and the plugins notebook need canvodpy code that is
# not on main yet (`canvodpy run --config-dir`,
# `validate_all(..., recommended=...)`, `ComponentFactory.register(...,
# replace=...)`, `canvod.utils.plugins`, all from PR #191): `marimo export
# html` fails on them until it is merged.
# Then move them back into NOTEBOOKS above, and give them `_build/` links in
# docs/notebooks/index.md.
SKIPPED_NOTEBOOKS=(
    11_icechunk_store
    12_store_metadata
    13_workflow_store_operations
    21_plugins
)

mkdir -p "$OUT_DIR"
cd "$DEMO_DIR"

# Notebooks run with `demo/` as cwd, a separate git submodule -- the
# monorepo-root autodetection in canvod.config.get_default_config_dir()
# can't see past that boundary, so bare `load_config()` calls would
# otherwise fall through to the XDG default and fail on machines with no
# global ~/.config/canvodpy/canvod-settings.yaml. Point it at the real one.
export CANVOD_CONFIG_DIR="$REPO_ROOT/config"

echo "== Static HTML exports, code included (${#NOTEBOOKS[@]}) =="
for nb in "${NOTEBOOKS[@]}"; do
    echo "-- $nb"
    uv run --project "$REPO_ROOT" marimo export html "${nb}.py" -o "$OUT_DIR/${nb}.html"
done

echo "== Skipped (need PR #191, see comment above) =="
for nb in "${SKIPPED_NOTEBOOKS[@]}"; do
    echo "-- $nb (not exported)"
done

echo "Done. Output in $OUT_DIR"
