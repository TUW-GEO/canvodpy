# canvodpy — Claude Code Instructions

## Skills — auto-apply when relevant

Apply all skills automatically whenever their domain is relevant — do not
wait to be asked.

### Core skills (installed)

| Skill | Apply when | Install |
|---|---|---|
| `xarray` | Working with `xarray.Dataset` / `DataArray`, coordinates, dims, attrs | `npx skills add tondevrel/scientific-agent-skills@xarray -g -y` |
| `zarr-python` | Working with Zarr stores, chunking, encoding | `npx skills add davila7/claude-code-templates@zarr-python -g -y` |
| `icechunk` | Working with Icechunk stores, versioned storage, branching | `just install-skills` (bundled at `.claude/skills/icechunk/`) |
| `pydantic` | Working with Pydantic models, validators, `BaseModel` | `npx skills add bobmatnyc/claude-mpm-skills@pydantic -g -y` |
| `python-testing-patterns` | Writing or reviewing `pytest` tests | `npx skills add wshobson/agents@python-testing-patterns -g -y` |
| `uv-package-manager` | Running `uv`, editing `pyproject.toml`, managing deps | `npx skills add wshobson/agents@uv-package-manager -g -y` |
| `marimo-notebook` | Writing/editing marimo notebooks (`.py` marimo files) | `npx skills add marimo-team/skills@marimo-notebook -g -y` |
| `beautiful-mermaid` | Rendering Mermaid diagrams to SVG/PNG from `.mmd` sources | `npx skills add intellectronica/agent-skills@beautiful-mermaid -g -y` |
| `mermaid-diagrams` | Creating software diagrams (architecture, flows, ERDs) | `npx skills add softaworks/agent-toolkit@mermaid-diagrams -g -y` |
| `scientific-writing` | Writing scientific manuscripts (IMRAD structure, citations) | `npx skills add davila7/claude-code-templates@scientific-writing -g -y` |
| `docs-as-code` | Documentation pipeline automation, MkDocs/Zensical workflows | Custom (contact maintainer) |
| `context-mode` | Large command outputs, log analysis, data processing | MCP plugin (see context-mode docs) |
| `notebooklm` | Generating podcasts, reports, quizzes from project sources | `pip install notebooklm-py && notebooklm skill install` |
| `simplify` | Reviewing changed code for reuse, quality, and efficiency | Built-in Claude Code skill |
| `find-skills` | Discovering and installing new skills | `npx skills add vercel-labs/skills@find-skills -g -y` |
| `agent-browser` | Browser automation for testing and scraping | `npx skills add vercel-labs/agent-browser@agent-browser -g -y` |
| `airflow` | Airflow best practices, operators, patterns (Astronomer) | `npx skills add astronomer/agents@airflow -g -y` |
| `airflow-dag-patterns` | DAG design patterns, TaskFlow API, dynamic DAGs, testing | `npx skills add wshobson/agents@airflow-dag-patterns -g -y` |

## Scientific context — GNSS-T and Vegetation Optical Depth

> This section provides the domain knowledge needed to work on this codebase.
> Read it before making changes to scientific logic.

### What is GNSS Transmissometry (GNSS-T)?

GNSS-T is a remote sensing technique that uses existing GNSS satellite signals
(L-band microwaves) to estimate vegetation properties. As signals travel from
a satellite to a ground-based receiver, they are scattered and absorbed by the
vegetation canopy.

The experimental setup uses **two receivers**:
- **Reference receiver** — placed in the open or above the canopy (unobstructed)
- **Canopy receiver** — placed underneath the vegetation

By comparing the **Signal-to-Noise Ratio (SNR)** at both locations for the same
satellite, the system calculates **transmittance (T)** — the ratio of signal
power reaching the below-canopy receiver vs. the unobstructed reference.

### What is VOD?

**Vegetation Optical Depth (VOD)** quantifies canopy signal attenuation using
the Tau-Omega Radiative Transfer Model:

    VOD = -ln(T) · cos(θ)

where T is transmittance and θ is the polar angle. VOD is a proxy for
**vegetation biomass and fuel moisture content**. Unlike optical sensors (NDVI),
L-band signals penetrate the entire canopy — invaluable for monitoring forest
health, carbon stocks, and drought stress.

### Key domain concepts for developers

| Concept | What it means | In the code |
|---|---|---|
| **SNR** | Signal-to-Noise Ratio (dB-Hz), the primary observable | SBF: 0.25 dB quantization; RINEX: ~0.001 dB |
| **SID** | Signal ID: `SV\|Band\|Code` (e.g. `G01\|L1\|C`) | Unique key identifying satellite + frequency + tracking code |
| **PRN** | Satellite identifier (e.g. `G01`) | Used by external tools; canvodpy uses SID internally |
| **Polar angle (θ)** | Angle from vertical to satellite (0°=overhead, 90°=horizon) | Used in VOD formula; internally prefer polar angle over elevation |
| **Azimuth (φ)** | Compass direction to satellite (0°=N, 90°=E) | Used for hemispheric gridding |
| **Ephemeris** | Satellite orbital data for position computation | Agency final (SP3/CLK, ~3 cm, 12-18 day latency) or broadcast (~1-2 m, real-time) |
| **Constellations** | GPS (G), Galileo (E), GLONASS (R), BeiDou (C) | System prefix in SID string |
| **Fresnel zone** | Elliptical signal footprint on canopy/ground | Determines spatial sensitivity of each observation |
| **Epoch** | Timestamp of a GNSS observation | GPS Time → UTC conversion with leap-second offset |
| **ECEF** | Earth-Centered Earth-Fixed coordinates | Satellite positions before conversion to receiver-relative spherical |

### Processing pipeline

```
RINEX/SBF files → Reader → xarray.Dataset(epoch, sid)
    → Ephemeris augmentation (SP3/CLK or broadcast)
    → Coordinate transform (ECEF → spherical: r, θ, φ)
    → Hemispheric gridding (EqualArea grid cells)
    → VOD retrieval (align canopy & reference by epoch+SID)
    → Icechunk/Zarr store (versioned, cloud-native)
```

## Project architecture

### Monorepo packages

| Package | Namespace | Role |
|---|---|---|
| `canvod-readers` | `canvod.readers` | RINEX v2/v3 and SBF binary readers → `xarray.Dataset` |
| `canvod-store` | `canvod.store` | Icechunk/Zarr storage layer (`MyIcechunkStore`) |
| `canvod-store-metadata` | `canvod.store_metadata` | Rich DataCite/ACDD/STAC metadata (11 sections, ~90 fields) |
| `canvod-vod` | `canvod.vod` | VOD retrieval algorithms |
| `canvod-grids` | `canvod.grids` | Spatial grid operations (EqualArea hemigrid) |
| `canvod-auxiliary` | `canvod.auxiliary` | Ephemeris, troposphere, auxiliary data pipeline |
| `canvod-config` | `canvod.config` | Configuration management: YAML loading, Pydantic validation |
| `canvod-utils` | `canvod.utils` | Date/time utilities, processing diagnostics |
| `canvod-viz` | `canvod.viz` | Visualization and store viewer |
| `canvod-ops` | `canvod.ops` | Operational pipeline (streaming, monitoring) |
| `canvod-preflight` | `canvod.preflight` | Naming convention parsing and pre-pipeline data directory validation |
| `canvodpy` | `canvodpy` | Orchestrator, API levels (L1-L4), VodComputer |

Optional, published as separate packages in
[canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions) (not
part of this monorepo's workspace):

| Package | Namespace | Role |
|---|---|---|
| `canvod-filemap` | `canvod.filemap` | Virtual renaming for non-canonical receiver filenames (recipe-based) |
| `canvod-airflow` | `canvod.airflow` | Airflow DAG definitions for canvodpy pipelines |

### API levels

Two supported surfaces, plus the CLI on top of one of them. The rest are
deprecated (`DeprecationWarning` on use) — kept working, no longer taught.

| Level | Style | Entry point | Use case | Status |
|---|---|---|---|---|
| CLI | Command-line | `canvodpy run --site ... --start ... --end ...` | Running the pipeline — recommended | Active |
| L3 | Site pipeline (OOP) | `Site(site).pipeline()` | Python-native configured pipeline runs — what the CLI wraps | Active |
| L4 | Functional | `canvodpy.functional.*` | Component-level scripting/analysis; also used by Airflow (stateless) | Active |
| L1 | Convenience | `process_date()`, `calculate_vod()`, `preview_processing()` | Superseded by `Site(site).pipeline()` | Deprecated |
| L2 | Fluent | `FluentWorkflow().read().augment().grid().vod()` | Superseded by `Site.pipeline()` / functional | Deprecated |
| — | `VODWorkflow` | `VODWorkflow(site=...)` | Broken augmentation step (no-op) — do not use | Deprecated |

### Data contracts

- **All datasets**: dimensions `(epoch, sid)`, attribute `"File Hash"` required
- **SID format**: `SV|Band|Code` (e.g. `G01|L1|C`)
- **Naming convention**: `{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`
- **Store guardrails**: three-layer dedup (hash match, temporal overlap, intra-batch overlap)

## Tooling

| Tool | Command | Purpose |
|---|---|---|
| `uv` | `uv sync`, `uv run` | Package manager, workspace orchestration, virtual env |
| `ruff` | `uv run ruff check`, `uv run ruff format` | Linting and formatting (replaces flake8/black/isort) |
| `ty` | `uv run ty check` | Type checking (Astral's type checker) |
| `pytest` | `uv run pytest` | Test runner; `-m "not integration"` for fast suite |
| `beautiful-mermaid` | `npx beautiful-mermaid render ...` | Render `.mmd` diagrams to SVG/PNG |
| `Zensical` | `uv run zensical build` | Rust+Python MkDocs Material wrapper for docs |
| `commitizen` | pre-commit hook | Enforces conventional commit messages |
| `pre-commit` | auto on `git commit` | Runs ruff, trim whitespace, large file check, private key detection |

### Common commands

```bash
# Pipeline execution (CLI, recommended — see "Running-the-pipeline rule" below)
uv run canvodpy run --site rosalia --start 2025087 --end 2025100   # Full RINEX ingest + inline VOD
uv run canvodpy vod --site rosalia --analysis VOD_lower_antenna --start 2025087 --end 2025087
                                          # VOD ONLY, straight from an existing RINEX store —
                                          # skips RINEX ingest entirely. Use this to isolate/
                                          # reproduce a VOD-store write issue without re-running
                                          # ingest. --analysis is a site.vod_analyses key (list
                                          # them: `python -c "from canvodpy.api import Site;
                                          # print(list(Site('rosalia').vod_analyses))"`).
                                          # Omit --start/--end for the full available range.
uv run canvodpy vod-reconcile --site rosalia --analysis VOD_lower_antenna
                                          # Dry-run report of RINEX-ingested-but-VOD-missing
                                          # dates (a run that crashed after RINEX succeeded but
                                          # before VOD wrote never gets silently revisited by
                                          # `canvodpy run`, which only resumes from the RINEX
                                          # store's latest date). Add --execute to backfill.

# Quality & testing
uv sync                                  # Install all workspace deps
just check                               # Lint + format (all packages) — fast, always passes
just check-types                         # Type check with ty (informational, allowed to fail)
just test                                # Run all tests
just test-all-packages                   # Run tests per package (avoids namespace collisions)
just test-package canvod-readers         # Test a single package
uv run pytest -m "not integration"       # Skip integration tests (fast)

# Documentation & notebooks
just docs                                # Preview documentation locally
just notebooks                           # List available marimo notebooks
just open-notebook grids_overview.py     # Edit a notebook interactively

# Store metadata
just metadata-show <store_path>          # Full metadata report for a store
just metadata-validate <store_path>      # Validate against FAIR/DataCite/ACDD/STAC

# Configuration
just config-validate                     # Validate sites.yaml
just config-check-data <site>            # Pre-flight naming convention check

# Dependencies
just deps-all                            # Generate all dependency graphs
just deps-cross                          # Cross-package dependency graph
```

## Conventions

- Monorepo managed with `uv` workspaces — all packages share one `.venv` at root
- Pydantic models use `frozen=False` with `@cached_property` for lazy computation
- Config: Pydantic models in `canvod.utils.config.models` (centralized, ~900 lines)
- Commits: conventional commits enforced by commitizen (`feat:`, `fix:`, `chore:`, etc.)
- Generated files: do NOT commit `*.png`, `*.svg` (except `docs/assets/logo.svg`),
  `*.lcov`, `*.db`, `node_modules/`, `package.json`, `package-lock.json`

## Code quality philosophy

**Goal:** Catch bugs without annoying scientists.

### What's enforced (blocks commits & PRs)
- **Linting** (ruff) — undefined names, unused imports, actual bugs
- **Formatting** (ruff) — auto-fixes, no cognitive load
- **Type checking** (ty) — blocks on `git push` (local hook) and in CI
  (`type_consistency` job); currently zero diagnostics. No budget/ratchet —
  either it's clean or it isn't. Two files (`canvod-store/store.py`,
  `canvod-store/grid_adapters/grid_storage.py`) have a `[[tool.ty.overrides]]`
  block in `pyproject.toml` suppressing specific rules where third-party
  zarr/icechunk stubs are too weak to be worth fighting.
- **Security** — no private keys, no large files in Git
- **Commit messages** — conventional commits for automated changelog

Run `just check-types` to run ty locally before pushing. Real diagnostics get
fixed or given a targeted `# ty: ignore[<rule>]` with a one-line reason — see
`docs/guides/DEVELOPMENT.md` for the convention. Focus on correctness tests
over type bureaucracy when the two are in tension.

### Test code exemptions
Tests can use `assert`, magic numbers, and intentionally weird patterns
to test edge cases (see `pyproject.toml:90` for ruff exemptions).

## Guardrails — what NOT to change without understanding

> These areas involve scientific correctness or data integrity. Do not modify
> them without understanding the underlying science.

- **VOD formula** (`canvod-vod`) — Tau-Omega radiative transfer model
- **Coordinate transforms** (`canvod-auxiliary`) — ECEF ↔ spherical, deg/rad conversions
- **Store dedup logic** (`canvod-store`) — hash + temporal overlap + intra-batch guards
- **Naming convention parser** (`canvod-preflight`) — IGS/RINEX standard
- **Ephemeris interpolation** (`canvod-auxiliary`) — Hermite spline on SP3 data
- **SID construction** (`canvod-readers`) — must match across readers and store

After changes to any of the above, run:
```bash
uv run pytest -m "not integration"          # Fast unit tests across all packages
```

## Diagram rendering

Use **[lukilabs/beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid)** for
rendering Mermaid diagrams to SVG/PNG. Source files live in `docs/diagrams/` (`.mmd`).
Do not commit generated images (`*.png`, `*.svg` except `docs/assets/logo.svg`),
`node_modules/`, or `package*.json`.

## 3D visualization conventions (non-negotiable)

Every 3D hemisphere plot built with `canvod.viz.HemisphereVisualizer3D` (or the
`visualize_grid_3d()` convenience function) must always include:

1. **Cell boundary wireframes** — `plot_hemisphere_surface(..., show_wireframe=True)`.
   Without this the underlying `Mesh3d` has no visible edges between cells at all,
   even with distinct per-cell colours — you cannot judge cell density or shape.
2. **The E/N/Up reference axes** — `HemisphereVisualizer3D.add_custom_axes(fig)`,
   with the native Plotly x/y/z axes fully **disabled** (`visible=False` on
   each scene axis — not just `showbackground=False`, which only hides the
   background pane and leaves the native axis line, ticks, and raw
   sin/cos-projected tick values/title rendering right alongside the custom
   labels). Fixed 2026-07-20 in both `plot_hemisphere_surface` and
   `plot_cell_mesh`. `add_custom_axes()` then draws artificial but
   native-looking labelled E/N/Up axis lines in the native axes' place.
   Without disabling the native ones, a 3D hemisphere plot shows two
   conflicting, overlapping axis systems at once.
3. **Elevation rings and meridians** — `HemisphereVisualizer3D.add_spherical_overlays(fig)`,
   for the same reason: an angular reference grid, since there's no native
   equivalent to polar-plot gridlines in a bare 3D scene.

A 3D plot missing any of these three is not acceptable for this project —
treat it the same as a plot with no axis labels. See
`demo/16_grid_3d_gallery.py` for the reference pattern (a small
`add_reference_frame(fig, viz)` helper wrapping (2) and (3), called on every
figure right after `plot_hemisphere_surface(..., show_wireframe=True)`).

`show_wireframe` was a declared-but-unwired no-op parameter in
`plot_hemisphere_surface` until 2026-07-20 — cell boundaries were silently
never drawn regardless of its value. Fixed via a new
`HemisphereVisualizer3D._extract_wireframe_lines()` helper (one
`Scatter3d` line trace per figure, None-separated per-cell perimeter loops,
mirroring each grid type's own `_render_*_cells` vertex-extraction logic).
If you touch `plot_hemisphere_surface` or add a new grid type's render path,
keep this helper's per-grid-type branches in sync.

## Key documentation — breadcrumb trail

When you need deeper context than this file provides, read these docs **in order**.
Each document cross-references the next, building from high-level architecture down
to package-specific details.

1. `docs/guides/ai-development.md` — **start here**: Claude Code setup, skills, workflows
2. `docs/architecture.md` — system architecture and data flow
3. `docs/principles.md` — design principles and philosophy
4. `docs/guides/api-levels.md` — CLI, `Site.pipeline()`, and the functional API explained
5. `docs/guides/getting-started.md` — setup and first run
6. `docs/findings/` — scientific comparison results and findings
7. `docs/packages/*/overview.md` — per-package deep dives

**Onboarding rule:** If a user asks you to explain the project, walk them through
this trail. If you encounter an unfamiliar package or concept, follow the trail
to the relevant `overview.md` before answering.

**Running-the-pipeline rule:** If a user asks to run, process, or ingest data
(not analyze/visualize existing results), recommend the CLI
(`uv run python -m canvodpy.cli.run --site ... --start ... --end ...`) first —
it resumes automatically from the last processed date when `--start` is
omitted. Use `Site(site).pipeline()` only when the user needs Python-native
scripting (looping over sites, embedding in a notebook). Do not suggest
`FluentWorkflow`, the flat `process_date()`/`calculate_vod()` functions, or
`VODWorkflow` — all three are deprecated (see `docs/guides/api-levels.md`).
For analysis/visualization of already-ingested data, `canvodpy.functional` and
the viz/analysis packages remain the recommended Python surface.

## AI-assisted development

This project uses **Claude Code** as a development and maintenance tool.
The AI agent is configured with:

- **`CLAUDE.md`** (this file) — project-specific instructions, architecture context,
  and scientific domain knowledge loaded into every conversation
- **15+ Claude Code skills** — domain-specific knowledge packs for xarray, Zarr,
  Pydantic, pytest, uv, marimo, Mermaid, and scientific writing (see skills table above)
- **Persistent memory** — cross-session recall of project decisions, conventions,
  and known issues (stored in `.claude/` directory)

New contributors: Claude Code can explain any part of the codebase, run the test
suite, generate diagrams, and help navigate the monorepo. Start with
`claude` in the repo root — it will automatically load this context.

### Session discipline

- **Always `cd` into the repo root before launching** — Claude Code reads the
  current directory for context; launching from home means no project awareness.
- **Prefer short, focused sessions** over marathon ones. When switching to an
  unrelated task, start fresh with `/clear`.
- **Watch for context window degradation**: signs are Claude re-reading files it
  already examined, or suggesting changes you already rejected. Use `/compact`
  to summarise conversation history and reclaim context space.
