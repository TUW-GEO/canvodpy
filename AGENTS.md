# canvodpy: instructions for coding agents

canvodpy computes vegetation optical depth (VOD) from GNSS signals: a
receiver below a canopy and a reference receiver with open sky
(GNSS-Transmissometry, GNSS-T). It reads receiver files (RINEX, SBF),
adds satellite geometry, assigns hemisphere grid cells, computes VOD and
keeps everything in versioned Icechunk stores. Its users are scientists.

`CLAUDE.md` files only import this file; edit `AGENTS.md`. Every package
has its own `AGENTS.md`: read it before changing that package.

## Scientific context

Read before changing scientific logic.

- **GNSS-T.** The same satellite signal (L-band) is received below the
  canopy and at the reference. The canopy weakens it; the ratio of the
  signal-to-noise ratios (SNR) gives the transmissivity T.
- **VOD** (zeroth-order tau-omega model): `VOD = -ln(T) · cos(θ)`, θ the
  polar angle of the satellite (0 = overhead, 90° = horizon). VOD tracks
  vegetation water content and biomass. L-band passes through the whole
  canopy, unlike optical indices.

| Concept | Meaning | In the code |
|---|---|---|
| SNR | Signal-to-noise ratio, dB-Hz, the observable VOD uses | data variable `SNR`; SBF quantizes to 0.25 dB |
| SID | Signal ID `SV\|band\|code`, e.g. `G01\|L1\|C` | dimension `sid`; one satellite has many SIDs |
| θ, φ | Polar angle and azimuth of the satellite, seen from the receiver | `theta`, `phi`, radians; the code prefers polar angle over elevation |
| Ephemeris | Satellite orbits: agency final products (SP3/CLK) or the receiver's broadcast navigation data (SBF) | canvod-auxiliary |
| Epoch | Observation time; each reader records its time scale | coordinate `epoch`, `epoch.attrs["time_system"]` |
| Hemisphere grid | Cells of the sky seen from the receiver; equal-area is the default | canvod-grids |

## Project architecture

Processing chain, one receiver-day at a time:

```
files (RINEX/SBF) -> reader -> Dataset(epoch, sid)
  -> satellite geometry (SP3/CLK or broadcast) -> theta, phi
  -> optional preprocessing (only if set in the settings)
  -> GNSS store (Icechunk) -> VOD (canopy vs reference) -> VOD store
```

| Package | Import | Role | Read first |
|---|---|---|---|
| canvodpy | `canvodpy` | CLI, `Site`/`Pipeline`, orchestrator, Airflow tasks, VOD computation | `canvodpy/AGENTS.md` |
| canvod-readers | `canvod.readers` | RINEX v2/v3, SBF, NMEA readers; the dataset contracts | `packages/canvod-readers/AGENTS.md` |
| canvod-auxiliary | `canvod.auxiliary` | Ephemerides, clocks, interpolation, receiver position, θ/φ | `packages/canvod-auxiliary/AGENTS.md` |
| canvod-grids | `canvod.grids` | Hemisphere grids, cell assignment, grid analysis | `packages/canvod-grids/AGENTS.md` |
| canvod-ops | `canvod.ops` | Optional preprocessing (temporal aggregation, grid assignment) | `packages/canvod-ops/AGENTS.md` |
| canvod-vod | `canvod.vod` | VOD calculators | `packages/canvod-vod/AGENTS.md` |
| canvod-store | `canvod.store` | Icechunk stores: writes, dedup, maintenance | `packages/canvod-store/AGENTS.md` |
| canvod-store-metadata | `canvod.store_metadata` | DataCite/ACDD metadata of a store; the STAC catalog and releases of all stores | `packages/canvod-store-metadata/AGENTS.md` |
| canvod-config | `canvod.config` | Settings models and the settings file loader | `packages/canvod-config/AGENTS.md` |
| canvod-preflight | `canvod.preflight` | The canonical file name convention | `packages/canvod-preflight/AGENTS.md` |
| canvod-utils | `canvod.utils` | Dates, file hashes, deprecation decorator, logging context | `packages/canvod-utils/AGENTS.md` |
| canvod-viz | `canvod.viz` | 2D/3D hemisphere plots | `packages/canvod-viz/AGENTS.md` |

All packages share one `.venv` at the root (uv workspace). `canvod` is a
namespace package: the `canvod` folder under each `src` has no init
module. Lower packages never import `canvodpy`
(`canvodpy/tests/test_package_boundaries.py` checks this).

### Entry points: one way to process data

| Entry point | Where | Status |
|---|---|---|
| CLI: `canvodpy run --site ... --start ... --end ...` | `canvodpy/src/canvodpy/cli/run.py` | recommended |
| Python: `Site(site).pipeline()` | `canvodpy/src/canvodpy/api.py` | same code as the CLI |
| Airflow: `check_day`, `process_day` | `canvodpy/src/canvodpy/workflows/tasks.py` | same code as the CLI, called by canvod-airflow |

All three find files through `canvodpy/src/canvodpy/orchestrator/discovery.py`
and compute VOD with `VodComputer` (`canvodpy/src/canvodpy/vod_computer.py`).
Deprecated, still working until v2.0.0, never recommended: `FluentWorkflow`,
`process_date()`/`calculate_vod()`/`preview_processing()`, `VODWorkflow`,
`canvodpy.functional`, the per-format Airflow tasks. Each one's warning
names its replacement; the docs leave them out.

### Data contracts

The code is the truth; don't copy the constants into new code.

- Observation datasets: `validate_dataset` in
  `packages/canvod-readers/src/canvod/readers/base.py` (dims `(epoch, sid)`,
  required coordinates, `SNR`, attribute `"File Hash"`).
- VOD datasets: `validate_vod_dataset` in the same file (`VOD`, `theta`,
  `phi` in radians); the VOD store refuses anything else.
- File names: `CanVODFilename` in
  `packages/canvod-preflight/src/canvod/preflight/convention.py`, e.g.
  `ROSA01TUW_R_20250010000_15M_05S_AA.rnx`. Other names need a naming
  recipe (canvod-filemap).

### canvodpy-extensions

Optional packages in a separate repository
(<https://github.com/nfb2021/canvodpy-extensions>), GitHub-only:
canvod-filemap (naming recipes), canvod-airflow (DAGs), canvod-adapters
(exchange with other GNSS-T programs). canvodpy installs canvod-filemap as
the workspace dependency group `filemap` (`uv sync --group filemap`).
The extensions import canvodpy's contracts and `canvodpy.workflows.tasks`.
Before renaming or changing anything public, search the extensions for it
and plan their change too; their agent instructions are
[`AGENTS.md`](https://github.com/nfb2021/canvodpy-extensions/blob/main/AGENTS.md). See the `extensions-dependency` guide.

## Task guides

Step-by-step guides for recurring tasks. Claude Code loads them as skills;
other agents read the files directly.

| Task | Guide |
|---|---|
| Run the pipeline, or help a user run it | `.claude/skills/run-pipeline/SKILL.md` |
| Add a reader for a new file format | `.claude/skills/add-reader/SKILL.md` |
| Add a GNSS constellation | `.claude/skills/add-constellation/SKILL.md` |
| Deprecate code | `.claude/skills/deprecate/SKILL.md` |
| Write to, repair or maintain a store safely | `.claude/skills/store-safety/SKILL.md` |
| Icechunk 2 API (sessions, fork/merge, maintenance) | `.claude/skills/icechunk/SKILL.md` |
| Change what canvodpy takes from canvodpy-extensions | `.claude/skills/extensions-dependency/SKILL.md` |
| Release canvodpy | `.claude/skills/release/SKILL.md` |

## Development workflow

Work on a branch, never on `main`; every change reaches `main` through a
pull request. An agent may push its branch and open the pull request, but
never merges, never pushes `main` or tags, never force-pushes and never
bypasses a check (`CODING_STANDARDS.md`, Git and GitHub; enforced for
Claude Code by `scripts/agent_git_guard.py`). Read `CODING_STANDARDS.md`
before writing code: its rules and its checklist apply to every change,
and `/mattpocock-skills:code-review` checks against them. Read the
`AGENTS.md` of every package you change, and the task guide if one fits.

Changes go through the shared agent workflow (the mattpocock-skills
plugin, `just agent-skills`; `docs/guides/ai-development.md`). Claude
Code calls plugin skills only by their full name:

| Situation | Start with |
|---|---|
| An idea or a change to design | `/mattpocock-skills:grill-with-docs`: interview until every decision is settled; records terms in `GLOSSARY.md` and decisions in `docs/adr/` |
| A change too big for one session | `/mattpocock-skills:to-spec`, then `/mattpocock-skills:to-tickets` (GitHub issues), then `/mattpocock-skills:implement` per ticket |
| A change that fits one session | `/mattpocock-skills:implement` (test first with `/mattpocock-skills:tdd`, then `/mattpocock-skills:code-review`) |
| Something is broken | `/mattpocock-skills:diagnosing-bugs`: a command that shows the bug before any theory |
| Not sure | `/mattpocock-skills:ask-matt` |

Running on real data or writing to a production store needs the
maintainers' go-ahead first.

## Commands

```bash
just sync                             # all packages, one .venv, git hooks
just agent-skills                     # the agent workflow plugin (Claude Code)
uv sync --group filemap               # plus canvod-filemap (naming recipes)
just check                            # ruff lint + format, ty, agent docs
just test-fast                        # tests without the integration marker
just test                             # all tests
just test-package canvod-readers      # one package
just docs                             # preview the docs site
just docs-lint                        # language check of the docs (Vale)
just docs-lint-changed                # Vale on the pages changed since origin/main
just docs-links                       # link check of the built docs (lychee)
just doctor                           # version, environment, settings found
just config-validate                  # check the settings file
```

Pre-commit runs ruff, `uv lock`, whitespace checks and the agent docs
check; commitizen checks the commit message; the pre-push hook runs ty. CI runs lint, format, ty and
the agent docs check (`.github/workflows/code_quality.yml`), Vale on the
changed docs pages and the link check of the built site
(`.github/workflows/docs_quality.yml`), and the tests on Linux, macOS and
Windows (`.github/workflows/test_platforms.yml`). A pull request that
changes behavior without docs to match is declined (`CODING_STANDARDS.md`).

## Finding code: the code graph

A graph of the code (graphify, built from the syntax tree, local and free)
answers structural questions faster and more completely than grep.

| Question | Command |
|---|---|
| What calls, imports or subclasses `NAME`; what does a change to it affect? | `just graph-affected NAME` |
| What does `NAME` connect to, in both directions? | `just graph-explain NAME` |
| How does `A` reach `B`? | `just graph-path A B` (caller first) |

- **Use it before changing code**: before renaming, deprecating or
  changing the behavior of anything, list its callers with
  `just graph-affected`. Before writing new code, look for an existing
  implementation (`graph-explain` on the nearest name you know), so no
  second one appears.
- **Verify what it says.** Edges marked `EXTRACTED` come from the syntax
  tree; `INFERRED` edges are guesses. Read the code before relying on one.
  For finding code by words, grep is better.
- **Freshness**: git hooks rebuild it in the background after every
  commit, merge and checkout (`.graphify/build.log`). After larger edits
  that are not committed yet (renames, moves, deletions), run `just graph`
  (about 10 s) before using it again. If the graph is missing, run
  `just graph`.
- It covers this repository only; search canvodpy-extensions separately.

## Rules

The rules every change follows (free tools only, explicit over implicit,
one implementation per job, composition over inheritance, deprecate don't
delete, optional processing stays optional, write for scientists) are in
`CODING_STANDARDS.md`, with their reasons in `docs/adr/`.

## Guardrails

Scientific correctness and data integrity. Understand the science before
changing these, and run `just test-fast` afterwards.

- VOD formula: `packages/canvod-vod/src/canvod/vod/calculator.py`
- Coordinate transforms and ephemeris interpolation:
  `packages/canvod-auxiliary/src/canvod/auxiliary/position/`,
  `packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/`
- Epoch grid: 00:00 plus multiples of the sampling interval
  (`packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/day_grid.py`)
- SID construction: must match across readers and stores
  (`packages/canvod-readers/src/canvod/readers/builder.py`)
- Store dedup and write strategies: `packages/canvod-store/AGENTS.md`
- File name convention: `packages/canvod-preflight/src/canvod/preflight/convention.py`

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues of nfb2021/canvodpy (`gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the root. See `docs/agents/domain.md`.

## Key documentation: the breadcrumb trail

For more context than this file gives, read in this order:

1. `GLOSSARY.md`: the project's words
2. `docs/adr/index.md`: the decisions and why they were made
3. `docs/architecture.md`: packages, layers, the processing flow
4. `docs/principles.md`: design principles, the file name convention
5. `docs/guides/api-levels.md`: CLI and `Site.pipeline()`
6. `docs/guides/configuration.md`: the settings file
7. `docs/guides/contributor-setup.md`: setup and a first run
8. `docs/packages/naming/overview.md`: which files a run processes, naming recipes
9. `docs/guides/extensions.md`: the optional packages
10. `docs/packages/`: one folder per package, start at its overview page

When a user asks to explain the project, walk them through this trail.
Before answering about an unfamiliar package, read its `AGENTS.md` and
its overview page under `docs/packages/`. `docs/guides/ai-development.md` explains this setup to
people.

## Keeping these files useful

- Write what an agent cannot see quickly in the code: decisions,
  invariants, traps, where things live. Don't list functions or restate
  docstrings; point at the file that holds the truth.
- Name the `just` recipe whenever one does the job, not the raw command
  behind it: agents and users must run the same thing and get the same
  result. If no recipe fits a recurring task, add one rather than
  documenting a command.
- Every path and `just` recipe named in `AGENTS.md` files and the guides
  must exist: `just check-agent-docs` verifies this (pre-commit and CI).
  Write paths in canvodpy-extensions as `extensions:<path>`; they are
  checked at the locked canvod-filemap commit when a canvodpy-extensions
  checkout is next to this repository (or at `$CANVODPY_EXTENSIONS_REPO`),
  and always in CI.
- When a change makes a statement here wrong, fix it in the same PR.
