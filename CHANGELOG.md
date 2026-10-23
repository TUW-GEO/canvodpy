# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## v0.4.0 (2026-09-02, never published)

Tagged, but never published to PyPI or Zenodo. Its changes first appear
in v1.0.0; users of canvodpy come from 0.3.0.

### Feat

- **store-metadata**: add public in-memory STAC Collection export
- **store**: add create_branch, dark-mode ancestry graph, v1 ops_log fallback
- **orchestrator,store**: cross-group fork/merge batch writes for skip/unsafe_append
- **store,config**: expose repo-info rewrite tuning knobs in IcechunkConfig
- **store**: scheduled manifest compaction via `maintain-due`
- **store**: scheduled Icechunk maintenance via `canvodpy store maintain-due`
- **store,auxiliary**: add network-wide shared aux cache with fingerprinting
- **orchestrator**: dedupe reference-receiver re-parsing across paired canopies
- **cli**: add vod-reconcile command for RINEX-ingested-but-VOD-missing dates
- **scripts**: unattended continuous py-spy profiling for overnight runs
- **perf**: additive instrumentation for write-side degradation over long backfills
- **cli**: add pipeline warm-up notice before per-day progress (§33)
- **dashboard**: auto-refresh + site/model-aware trend charts
- **vod**: multi-model VOD store hierarchy, dedup guardrail, rich metadata (§29)
- **cli**: run --dashboard flag + Nordic styling for perf dashboard
- **cli**: add --host/--port to canvodpy dashboard
- **logging**: two-track logging, crash handling, stage_timer, perf dashboard
- **auxiliary**: make CLK clock-correction fetching optional (default on)
- **store-metadata**: detect and record config drift on repeat ingests
- **dev**: add just recipes for doctor, wizard, and store inspection
- **cli**: add --version flag to canvodpy
- **store**: add canvodpy store CLI (list/info/log)
- **cli**: add canvodpy doctor for environment/config diagnostics
- **cli**: add --interactive wizard to canvodpy config init
- **config**: add StorageConfig.rollup_store_name + get_rollup_store_path
- **config**: implement 'just naming-init' — was a documented dead end
- **config**: add 'just config-delete' + document overlay/base-file merge semantics
- **dev**: default drought analyses to the vegetated season, not the whole record
- **dev**: add --start/--end to drought-diff scripts, restricting fit + residual to the same window
- **dev**: add --stat std to residual hemiplot, showing temporal variability
- **dev**: add spatial (per-cell) residual hemiplot
- **dev**: add side-by-side VOD hemisphere plot for both antennas
- **dev**: isolate drought signal via robust regression instead of naive difference
- **dev**: reduce default smoothing to 7 days, add drought difference plot
- **dev**: add step-by-step grid-assignment tracer for the VOD_upper_antenna anomaly
- **dev**: show raw daily points under the smoothed line in VOD comparison plot
- **dev**: add VOD group diagnostic to find why an antenna's timeseries is all-NaN
- **dev**: add matplotlib comparison plot for Galileo VOD, both antennas
- **grids**: add stat parameter to compute_percell_timeseries; fix multi-process logging race
- **cli**: add --ephemeris-source and --vod-calculator flags to canvodpy run
- **cli**: multi-site canvodpy run + per-(site,receiver) progress display
- **cli,api**: deprecate L1/L2/VODWorkflow, add canvodpy run subcommand, make canvod-filemap optional
- **utils**: auto-derive vod_analyses in SiteConfig from paired_canopies
- **orchestrator**: annotate icechunk commits with batch metadata
- **cli**: Rich Live TUI dashboard with PlainReporter / RichReporter
- **preflight**: add canvod-preflight package with convention validation and CLI
- **sids**: bundle default 277-SID preset and wire as package default
- **store**: add get_ops_log / print_ops_log wrapping icechunk v2 ops_log

### Fix

- wire store_description and references fields into metadata collection
- reject implausible receiver positions (ECEFPosition guard rail)
- **ci**: exclude Markdown and demo/ from ruff format's directory walk
- **ty**: resolve zero-diagnostics gate after upgrading past a yanked polars release
- **store**: resolve canvod-utils version via importlib.metadata, not a pyproject.toml walk
- **orchestrator**: use module-level TypeVar to fix CodeQL false positive on _windowed_completions
- **security**: discover dashboard port on its target host, not all interfaces
- **security**: resolve CodeQL incomplete URL sanitization and regex range findings
- **types**: resolve 12 ty diagnostics surfaced by the ty 0.0.44->0.0.62 bump
- **deps**: relock uv.lock to match pyproject.toml dependency floors
- **workspace**: drop stale canvod-naming folder, add missing canvod-config/canvod-preflight
- **config**: correct ty exclude key from [tool.ty] extend-exclude to [tool.ty.src] exclude
- **readers**: correct GLONASS aggregate G1/G2 center frequency bug
- **cli**: make canvodpy run --dry-run respect --start/--end
- **readers**: populate SBF's SSI observable instead of leaving it dead
- **orchestrator**: stop aux day_start from shifting back a day for SBF sites
- **viz**: make the healpy optional-import ty fix environment-independent
- **orchestrator**: stop silent theta/phi corruption from uninitialized memory
- **viz**: silence a ty false-positive on the optional healpy import fallback
- **viz**: replace broken Tissot ellipse approximation with exact 3D circle
- **grids**: add correctness tests for all 7 grid types, fix 3 bugs found
- **auxiliary,orchestrator**: reset SID accumulators per file, fix self-contained integration test
- **readers,audit,preflight,cli**: resolve remaining ty diagnostics from the ty 0.0.62 bump
- **orchestrator**: resolve ty diagnostics surfaced by the ty 0.0.62 bump
- **store**: correctly detect nested VOD group paths; add cross-group VOD batch writes
- **config**: ty-ignore the intentional dynamic cache_clear/cache_info shim
- **config**: load_config() cache blind to CANVOD_CONFIG_FILE/CANVOD_CONFIG_DIR env var changes
- **utils**: commit sanitize_directory module referenced by store.py/processor.py
- **dev**: avoid dashboard port collision across sweep chunk sizes
- **orchestrator**: retry Phase-1 aux-cache prep once before dropping a date
- **grids,viz**: fix 7 correctness bugs across grid builders and 3D viz
- **orchestrator**: isolate VOD writes in a dedicated subprocess
- **store**: apply chunk_strategies config as write-time encoding
- **orchestrator,store**: opt-in settle gap before batch's first VOD write
- **store**: preserve sibling zarr async config keys when scoping concurrency
- **store**: opt-in cap on zarr async chunk-write concurrency
- **orchestrator**: interleave windowed task submission across receivers and dates
- **orchestrator**: correct unverified incident claim in store-retry backoff comment
- **logging**: render exception tracebacks into error/json log sinks
- **orchestrator**: raise loky idle-worker timeout to survive batch prep gaps
- **orchestrator**: retry VOD-store writes, extract shared retry helper
- **orchestrator**: catch icechunk.IcechunkError, retry transient store I/O
- **dashboard**: merge rotated log backups, widen retention and refresh options
- **deps**: pin canvodpy-extensions git sources to v0.1.0 tag
- **config**: remove noisy "no sites configured" warning on standalone use
- **ci**: fold canvod-config and canvod-preflight into the test/release/publish machinery
- **types**: resolve all 7 ty diagnostics blocking the pre-push hook
- **deps**: relock canvod-adapters/canvod-filemap against merged extensions main
- **readers**: add missing pymap3d dep; remove(utils): dead diagnostics chain
- **tests**: CI-safe test isolation, ESA ephemeris mirror, scrub example site name
- **store,config**: rename gnss_store to rinex_store, correct chunk-size default
- **cli**: fail fast when a recipe-configured receiver lacks canvod-filemap
- **config**: actionable validation errors, no raw Pydantic tracebacks
- **config**: bundle templates as package data, default to XDG config dir
- **cli**: use canvodpy (not canvod) consistently in messages and docs
- **config**: remove stale gnss_store_expire_days from canvod-settings.yaml.example
- **grids**: satisfy ty — time_start/time_end are already Timestamps after floor()
- **grids**: compute_percell_timeseries() silently dropped all data when first epoch wasn't period-aligned
- **dev**: make inspect_vod_group.py lazy — it was materializing the full store
- **dev**: handle all-NaN antenna series gracefully in VOD comparison plot
- **store**: rechunk_group() actually changes chunk size, preserves metadata
- **cli**: advance the Overall progress bar's completed count in on_day_start
- **grids**: use canvod-grids' own logger instead of a non-existent canvodpy import
- **cli**: disable duplicate Rich Live display in canvodpy run
- **orchestrator**: stringify YYYYDOY before passing to icechunk commit metadata
- **deps**: point canvod-filemap at git source, not a local sibling path
- **cli**: resolve ty type errors in deprecation decorator
- **utils**: reject placeholder sentinels in MetadataConfig and StorageConfig
- **store**: replace bare StopIteration with clear ValueError on empty sites
- **readers**: fall back gracefully in get_global_attrs() without config
- **cli**: fall back to rich.console.Group for rich < 12.0
- **cli,orchestrator**: resolve ty errors from dashboard and commit metadata
- **readers**: guard SBF DeltaLS=-128 DNU sentinel in ReceiverTime blocks
- **store**: clear xarray encoding in-place in rechunk_group
- **store**: remove per-batch GC, fix chunk key mismatch, drop expire_days config
- **config**: correct template field names and remove .env myth
- **preflight**: cast receiver_type Literal for ty type checker in CLI
- **config**: update missed batch_hours callsite in timing_diagnostics_script
- **store-metadata**: detect icechunk v2 store layout in scan_stores
- **store**: suppress icechunk noise, fix config leakage, standalone support
- **ci**: resolve post-PR#109 failures — stale lockfile and ty upgrade errors
- **ci**: force Node.js 24 in deploy_docs to suppress peaceiris deprecation warning

### Refactor

- **store**: rename append strategy to unsafe_append
- **store**: complete rinex_store -> gnss_store rename
- **audit**: extract gnssvod adapter logic into canvod-adapters
- **config**: split models.py into a package, add naming/recipe guard
- **cli**: port run command to native Typer
- remove Airflow DAGs, now available as canvod-airflow extension
- **config**: extract canvod-config package from canvod-utils
- remove canvod-virtualiconvname, port tests to canvod-preflight
- **dev**: rebuild VOD hemiplot with canvod-viz instead of manual scatter
- **cli**: move the whole CLI into canvodpy, canvod-utils back to a pure library
- rename canvod-filemap (was canvod-virtualiconvname), unify config to canvod-settings.yaml
- **config**: config system hardening + icechunk v2 alignment
- **config**: Tier B modernisation — batch unit, field renames, pydantic-settings, credentials
- **config**: modernize config system — Tier A safety + Tier B cleanup
- **store**: replace plot_commit_graph with repo.ancestry_graph wrapper

### Perf

- **orchestrator**: remove hardcoded 4-date cap on Phase 1 prep concurrency
- **orchestrator**: stop resolving full manifests just to check variable names
- **store**: default gnss_store chunking to per-file; add rechunk sweep tooling
- **orchestrator**: instrument uninstrumented batch-write timing gaps
- **store**: single-load dedup check, windowed writes, retention capability
- **dev**: batch inspect_vod_group.py's reductions into one dask.compute() call
- **pipeline**: parallel Wave A/B receiver processing + Fable fixes
- **pipeline**: V1/V3 optimisations, per-phase timing, VOD store, planning docs
- **config**: cache load_config() to eliminate repeated YAML reads
- **sbf-reader**: eliminate pint hot-path overhead in MeasEpoch decode
- **benchmark**: add lazy padding (Step 2) — defer pad_to_global_sid to write boundary
- **benchmark**: wire SNR-only + 277-SID config; add --days flag

## v0.3.0 (2026-04-30)

### Feat

- **readers**: Implementation of stripped RINEX 3.05 reader
- **readers**: Implementation of NMEA reader
- **readers**: Register NMEA reader in ReaderFactory
- **reader**: add NMEA standard document (large file, 1MB, ignoring hooks)
- **readers**: Implementation for NMEA v4.* incl. test, and format reference file
- **readers**: Add tests for rinex 2.11 and a data standard description
- Implementing reader for RINEX 2.11
- Implementing reader for RINEX 2.11, add test_data

### Fix

- **ci**: remove taiki-e/install-action to fix BASH_FUNC_ injection false positive
- **store**: bump canvod-store to 0.2.3 — add missing canvod-utils/vod/auxiliary/readers deps                                  \canvod.utils is imported eagerly at module load time but was absent from the 0.2.2 PyPI release dependencies. Files: packages/canvod-store/pyproject.toml
- **grids**: bump canvod-grids to 0.2.3 — add missing structlog dep
- **readers**: move keep_data_vars filter after store_raw_observables in to_ds_and_auxiliary
- **speedrun**: decode_timedelta=False on zarr open; subpkg header >=0.2.3; fix SP3/CLK paths
- **demo**: verify 00_convenience_speedrun — bump readers/auxiliary/vod to 0.2.3
- **orchestrator**: add consolidated=False + datetime64 epoch fix in VodComputer
- **quality**: resolve CodeQL error-severity code scanning alerts
- **utils**: replace tomli with built-in tomllib
- **ci**: regenerate uv.lock for Dependabot PRs before uv sync --locked
- **ci**: make Dependabot PRs work without lockfile race condition
- **ci**: re-run failed checks after uv.lock update to resolve race condition
- **ci**: pass GITHUB_TOKEN to howfairis to avoid rate limit 403
- **ci**: remove stale just installer from lock_file job
- **types**: resolve all ty diagnostics and enforce type checking
- **deps**: declare remaining missing inter-package dependencies
- **deps**: declare missing inter-package dependencies
- **deps**: add missing structlog dependency to 5 packages
- **readers**: use importlib.metadata for version lookup in get_version_from_pyproject()
- **readers**: remove unnecessary files
- **readers**: delete useless file
- **readers**: remove unnecessary config files
- **readers**: rename rinex2-files
- **readers**: find rinex2 files
- **docs**: use VODnet badge with embedded logo in docs/index.md

## v0.2.2 (2026-04-07)

## v0.2.1 (2026-04-07)

### Fix

- restore fair-software badge to 5/5 green (PyPI registry check now passes)
- **ci**: add PyPI badge to README and update fair-software badge to 4/5

## [0.2.0](https://github.com/TUW-GEO/canvodpy/releases/tag/v0.2.0) - 2026-04-06

<small>[Compare with 0.1.0](https://github.com/TUW-GEO/canvodpy/compare/0.1.0...v0.2.0)</small>

### Features

- First public release — removes pre-release access restriction.
- Add `canvod-store-metadata`, `canvod-virtualiconvname`, `canvod-ops`, `canvod-audit` to PyPI publish workflows (previously unpublished packages).
- Enrich Zenodo and CITATION.cff metadata: aligned titles/dates, added `related_identifiers` for `canvodpy-test-data` and `canvodpy-demo` sub-repos, extended keyword list.

### Bug Fixes

- Fix PyPI publish workflow: `uv build` in sub-directories was writing wheels to per-package `dist/` instead of the root `dist/` consumed by `gh-action-pypi-publish`.
- Add missing Dependabot labels (`dependencies`, `ci`, `python`) to repository.

### Chores

- Bump all package versions `0.1.0` → `0.2.0`.
- Remove confidential pre-release CAUTION banner from README.

## [0.1.0](https://github.com/TUW-GEO/canvodpy/releases/tag/0.1.0) - 2026-02-04

<small>[Compare with first commit](https://github.com/TUW-GEO/canvodpy/compare/96138d31f317198083a65199572cd23366b8b9b3...0.1.0)</small>

### Features

- Re-enable code_quality.yml workflow with Phase 1 rules ([d60a953](https://github.com/TUW-GEO/canvodpy/commit/d60a95343b90a985701cf4f8db36bcc697269485) by Nicolas Bader).

### Bug Fixes

- Update deprecated ruff config in package pyproject.toml files ([1c757a6](https://github.com/TUW-GEO/canvodpy/commit/1c757a690328fefb6477b181d0ca7c111c1179d6) by Nicolas Bader).
- Convert test_config_from_anywhere to proper pytest test ([db47b8a](https://github.com/TUW-GEO/canvodpy/commit/db47b8ae15624a365dcc1267d6b4c3707178a5c3) by Nicolas Bader). Result: Test collection works in CI, tests skip properly
- Measure coverage for all packages, not just umbrella ([b0046f4](https://github.com/TUW-GEO/canvodpy/commit/b0046f4ac18ad97136c1843baa00fe6ce76f7af8) by Nicolas Bader). Expected coverage: ~63% overall, - High: canvod-store (70%), canvod-grids (75%), - Medium: canvod-vod (75%), canvod-auxiliary (60%), - Lower: canvod-viz (36%), canvod-utils (79%)
- Remove obsolete test_configuration.py from workflow ([f5c1727](https://github.com/TUW-GEO/canvodpy/commit/f5c1727ce94717cfe4308a3ff1bac785a574d74e) by Nicolas Bader).
- Fix CI failures - pint ApplicationRegistry and sys.exit ([3120d30](https://github.com/TUW-GEO/canvodpy/commit/3120d30390e7cec9426576fcd3809b98751a7cc0) by Nicolas Bader).
