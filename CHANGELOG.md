# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## v1.0.0 (2026-10-24)

### BREAKING CHANGES

- **cli**: one site per run; --update-to-latest replaces the default dates (379d4265)
- **config**: fetch settings and recipes from a link in every run, record no URL (112b91a5)
- **run**: a run lists the folders of the days it processes (#353) (a4b6bc06)
- **store**: grids and analysis results are stored by canvod-store (029a0a72)
- **logging**: require the log folder and make the timing events complete (242d3516)
- install canvod-filemap through the workspace group "filemap" (8e059da9)

### Feat

- **cli**: one site per run; --update-to-latest replaces the default dates (379d4265)
- **config**: fetch settings and recipes from a link in every run, record no URL (112b91a5)
- **reference**: pin the reference stores built at bd2e6c7b (48e2d898)
- **config**: -c takes the pinned URL of a settings file (cc8720b8)
- **reference**: pin the stores built by 4648e776 from test data f0764c4 (5fc4fec2)
- **reference**: the stores record their site position, links and license (ba87f531)
- **demo**: the run history with the example machine, from test data f0764c45 (c201b8d2)
- **demo**: demo_data("stores") downloads the GNSS and VOD store of the RINEX day (24a74b41)
- **store-metadata**: processing.metadata.record_machine leaves the computer out of commits (0e1576ec)
- **store-metadata**: a run refuses a naming recipe that differs from the store's (611743b3)
- **naming**: accept a naming recipe from a pinned URL (f28657c0)
- **reference**: pack the reference stores into zips and check against the published ones (#325) (3d63271c)
- **cli**: canvodpy store migrate SITE moves a site's stores in one go (#456) (0e20298a)
- **store**: name the GNSS store folder gnss and check store folder names (#456) (bcf46880)
- **run**: log a commit conflict lost on every try as store_conflict_lost (2710ac33)
- **run**: log the skipped files of stored days in one commit (aa5b72bb)
- **vod**: log the worker memory peak of each VOD task (08bda392)
- **diagnostics**: split a unit of days and retitle the stage axes (46ed09ed)
- **diagnostics**: key the store size by data day and record the walk time (8e03bab6)
- **diagnostics**: chart the store size, a time-per-day line and a stage median (019826c0)
- **demo**: publish the example run history on Hugging Face (caddb63b)
- **dashboard**: example run history, its tests and demo_data kind (1d3fdd54)
- **run**: time the planning of a day and its read-back for VOD (19e23095)
- **dashboard**: canvodpy colors, log time axis, folded run details (97caf12a)
- **dashboard**: download the data behind the run page and the comparison (793dac82)
- **run**: warn about incomplete receiver-days and say why VOD is skipped (#387) (d32a9af6)
- **run**: a run without dates resumes the receiver-days with new files of the last 30 days (#386) (04e17f16)
- **canvodpy**: the memory budget sizes workers and days per batch (#278) (465ce857)
- **run**: a run lists the folders of the days it processes (#353) (a4b6bc06)
- **canvodpy**: read the next batch while VOD of the one before is computed (#277) (bd07bbef)
- **cli**: canvodpy store migrate-layout and its just recipe (#279) (db14da7d)
- runs and VOD refuse stores written by appending; rewrite_group refuses day blocks (#279) (ed9ea9b3)
- **store**: maintenance on a store on S3 is a dry run only (#357) (498f8962)
- **store**: pad day blocks to whole chunks, so every cadence is stored (#376) (3145f514)
- **store**: VOD store in day blocks, one commit per day (#276) (#366) (c4a30b17)
- **store-metadata**: content settings of the VOD store (#355) (d6646c06)
- **store**: stop when a file covers epochs a file with another hash already filled (#351) (#372) (5446deeb)
- **cli**: config init --from-store writes the settings of a store (#356) (89377b32)
- **store**: runs write stores on S3 (#350) (#369) (01f244db)
- **store-metadata**: content settings, set when a store is created and matched by every run (#363) (bd5b49aa)
- **run-history**: let a run's start and end time be fixed (549a9663)
- **dashboard**: total the comparison by run wall time (954a9256)
- **dashboard**: compare runs by label (47b70308)
- **dashboard**: add interactive charts to the run page (97313b87)
- **dashboard**: keep the chosen run across refreshes and label UTC (d6e6f11f)
- **dashboard**: read the run history and show a site overview and run page (77e8a58d)
- **config**: canvodpy config explain, setup help, settings reference and a chunks page (#337) (a9f0ccb0)
- **orchestrator**: write a day's files in parallel forks (6aebd055)
- **run**: file index so a run lists only recent folders (#299) (355e4ee4)
- **run-history**: record resource samples during a run (#298) (2020aed7)
- **orchestrator**: grow a batch's day blocks in one commit before reading (8b1bdda9)
- **demo**: download the demo data from Hugging Face, checked by sha256 (32746d4f)
- **demo**: the Zenodo URLs, and downloads that resume (bbd2551b)
- **canvodpy**: stage timings in the run history (da566e6e)
- **canvodpy**: every run records itself in the run history (88bd0d04)
- **canvodpy**: run history module (ADR 0018) (2b34a4c7)
- **cli**: say which receiver's files a run is finding (7ba4cef7)
- **demo**: canvodpy.demo_data() downloads and unpacks the demo day (a4273cea)
- **store**: write new GNSS stores as day blocks with serial writes (1b6a63db)
- **cli**: canvodpy run --write-catalog writes the STAC catalog after the run (ee5ad6ae)
- **store-metadata**: releases tag every store and write releases/<tag>/ (21371620)
- **store-metadata**: refuse undescribable stores and non-SPDX licenses (#245) (0cdb55a3)
- **api**: Site names its store paths (6c73c320)
- **store-metadata**: write the STAC catalog of the GNSS stores at the data root (6c395d0e)
- **store**: opening a store never creates it (71b7a888)
- **store-metadata**: store description per site; publisher and license required (76084d7c)
- **store-metadata**: record who changes metadata, geodesy store type, description required (d1a029e5)
- **store-metadata**: migrated stores pass the standards checks, VOD attributes replaced (963987f8)
- **store-metadata**: check stores against CF, ACDD and zarr conventions (#208) (d569afff)
- **config,store-metadata**: optional receiver and antenna details per receiver (72b95ac2)
- **store-metadata**: amend a store's description, with a reason (824aa5b0)
- **store-metadata**: migrate stores written before repository metadata (03afe2f6)
- **store-metadata**: read any snapshot as it was, history from the commit log (905dcc21)
- **store-metadata**: writers give a new store its metadata first and refuse unlisted receivers (be26b339)
- **store-metadata**: give a new store its id, UUID and naming authority in the repository metadata (8ec0608e)
- **plugins**: readers and VOD calculators from installed packages (0200885b)
- **run**: check preprocessing against the stores before processing (e693932d)
- **ops**: integer variables take the first, last or middle value of a bin (e650e2f2)
- **ops**: record the version of every package that ran the preprocessing (67c4737f)
- record the preprocessing in the store log books, stop runs on a mismatch (00258166)
- **workflows**: process_day and check_day run the code of canvodpy run (18f70c35)
- **orchestrator**: warn about files a run does not process (d99ce2ef)
- **ops**: apply processing.preprocessing in every run, if set (A12) (8705b9f6)
- **functional**: deprecate the single-step functions (fc3b2fe8)
- **preflight**: keep only the naming convention, deprecate mapping and validation (b2d9ea0f)
- **workflows**: Airflow tasks find files with the discovery of canvodpy run (f1878cb1)
- **discovery**: read naming recipes per site through canvod-filemap (17088448)
- **config**: show identity, sampling check and unprocessed file types in the data check (88586009)
- **cli**: one configuration directory lookup and --config-dir on every command (452cd923)
- **config**: check receiver data in `canvodpy config validate` (9c0f852d)
- **discovery**: one overlap check on canonical names for discovery and batch writes (8bea03a1)
- **discovery**: find each file's day from its name in any folder layout (a2df1e15)
- **pipeline**: check recipe identities and warn on sampling mismatch (9e570cf3)
- **store-metadata**: fill coverage and summaries from the store (93c45b07)

### Fix

- **release**: check the ranges against packages left out of a release (3ccc892b)
- **release**: refuse up front when the release branch exists (7a8c8d2a)
- **cli**: --update-to-latest starts on the earliest last stored day (0ba39ce8)
- **utils**: a new Site or Airflow task is a new run; other links record their host (4913f39d)
- **utils**: one fetch per run across processes; a link is recorded only as the file name of a raw file link or as its host, never in full (01305cf1)
- **cli**: name the --config-dir values <path|url> and <path> (24d6e685)
- **demo**: the demo stores in a folder of their own, apart from the check's (e6e90bed)
- **dashboard**: made-up core counts, memory and disks for the example run history (cace5247)
- **cli**: --update-recipe refuses a receiver the store lacks and the VOD store (6f71cee6)
- **reference**: name a store file that can't be searched; zips the same on every system (59c71e8b)
- **store**: refuse to add a receiver whose recipe is not found; show the recipe sha256 (cffc8143)
- **cli**: config validate takes --config after the command, as run does (dcf018c5)
- **cli**: store migrate errors name its own command and --gnss-set/--vod-set (#456) (5e6c43fb)
- **cli**: store migrate passes each --set value to its step and names stores it only moves (#456) (b1542e44)
- **cli**: store migrate reruns pass migrated stores and plan the VOD hash from state (#456) (0c7be153)
- **readers**: the NMEA reader gives the receiver position from the GGA fixes (#451) (399947f1)
- **run**: make the lost-conflict hint true for every step (1351e58c)
- **run**: name this run's file path in a skipped row (8a9a733d)
- **run**: test stored days against the log-book rows around them (da0debea)
- **run**: keep retrying a Windows sharing violation (2069d5ed)
- **run**: don't retry store errors that last (ada05b3c)
- **run**: retry a unit's commit and its VOD after a transient store error (271365d5)
- **vod**: name the days of the VOD growth commit as YYYYDOY (06747403)
- **diagnostics**: free-disk tooltip in UTC, VOD unit log in YYYYDOY (1c31dc02)
- **dashboard**: key VOD days as YYYYDOY, date axes and tooltips (2657c06f)
- **run**: the overlap check stops growing with the log book (#425) (84ffb454)
- **run**: review of units: one largest_task, log book read once per group, measured held factor, at most four days prepared at once, days_per_batch warns once (#425) (8767afef)
- **run**: a forked day records its writing time once, not once per receiver (#423) (1694b821)
- **dashboard**: log time axis bars start at a valid X2/Y2 datum (86a4eb04)
- **store**: deprecated paths record the reader's own source_format (#328) (5bf53ab5)
- **tests**: tests use a temporary run.pid, never the user's (#401) (c267fd0e)
- **dashboard**: dark theme, color-blind-safe colors, grouped bars (834ee0e7)
- **store-metadata**: migrate canVODpy 0.x stores so runs can write to them again (ddb87154)
- **store**: name file hashes in the overlap error; GNSS/VOD in store titles (ea998a83)
- **run**: size each run from the asked days per batch; record the sized workers (#278) (b1742de5)
- **store**: S3 maintenance tests open plain sessions; no --execute hint on S3 (#357) (939f8f5c)
- **store**: name the CLI S3 maintenance test file uniquely (#357) (f9e261ce)
- **store-metadata**: refuse missing VOD content-settings hashes and record calculator parameters (#355) (74531f21)
- **utils**: add a random part to run IDs, so runs on two machines differ (#377) (4d501d4b)
- **store-metadata**: refuse an S3 store whose name looks like the site (#356) (89e9d841)
- **store-metadata**: initializing from a store handles a Windows path and refuses a wrong store layout (#356) (3301a9f5)
- **store**: a write empties only its own earlier slots, never another file's (f1c95d1d)
- **cli**: migrate-metadata takes the store location of an S3 store (#370) (900c3662)
- **store**: a GNSS file written again keeps nothing of its earlier write (8acfae8b)
- **dashboard**: sort time per stage by time and label time per day (7edff18c)
- **vod**: check preprocessing for every day before the store metadata (#276) (fef73e54)
- **dashboard**: pass --no-sandbox to marimo (3d4dc840)
- **canvodpy**: read the auxiliary store as stored, without decoding durations (#345) (d5286efe)
- **store**: try a commit that lost a conflict up to five times (#343) (325e9ae3)
- **run-history**: runs started together open a new run history (147df7e4)
- **orchestrator**: record late file failures; wait for the writer on errors (8fe0c408)
- **run**: exit code 3 when a receiver-day fails (#334) (905e04dd)
- **store**: number an existing group's chunks by its stored epoch chunk (de095be9)
- **orchestrator**: retry a store conflict once, without the backoff (a7f040ad)
- **run-history**: do not record check_day runs (c874c39c)
- **orchestrator**: record the reader's own source_format in the GNSS store (d2c6d4c8)
- **cli**: build the message line from the Path; assert it via a dry-run (6699e551)
- **orchestrator**: one filemap check for check_receivers and the warm-up (a5741e85)
- **orchestrator**: say which receiver's files a run finds before scanning them (f1ec285e)
- **orchestrator**: take the sampling of should_skip_day from the files (2b870a83)
- **store-metadata**: refuse stores without data; fixed dimension order (0c2ad258)
- **canvodpy**: a first run on a new site no longer fails before it writes (852ebcad)
- **store-metadata**: every write path gives a store its metadata first (bf7a03ca)
- **store-metadata**: a store without repository metadata takes no data (552e2581)
- **cli**: migrate-metadata takes the settings' naming authority for an invalid one (6e6496ab)
- **store-metadata**: amend a field under an unset section instead of crashing (53106d9b)
- **release**: write the release version into the citation files (ff8ecc7a)
- **store-metadata**: naming authority from the settings, no stray Icechunk warnings (5c642427)
- **store**: commits to a store wait for each other, also across processes (304d71a8)
- **factories**: register every grid builder with GridFactory (e5c7f184)
- **factories**: AugmentationFactory.register takes replace= (09f8ef10)
- VOD metadata and string-coordinate failures raise, register() refuses taken names (13ad2d9f)
- **canvodpy**: write failures stop the run, settings are passed down (6dfbaf10)
- **config**: settings texts name unsafe_append and no development notes (d937b811)
- **cli**: vod and vod-reconcile accept only installed VOD calculators (9163912a)
- **types**: clear the type checker findings in code, scripts and tests (238e7368)
- **logging**: require the log folder and make the timing events complete (242d3516)
- **logging**: file logging follows the configuration of the run (b1d94663)
- every stored epoch is GPS time (6e26041e)
- **orchestrator**: SingleReceiverProcessor.process() names its replacement (06a5fa6e)
- **store**: refuse an append whose sid labels differ from the group's (45e0eee5)
- aggregate_glonass_fdma reaches the readers, the SID padding and the orbit data (ac914453)
- **discovery**: compressed files never selected and reported apart (5cdb8048)
- **auxiliary**: registry checked against the servers, final/rapid only, several samplings per product (61031fa4)
- **config**: reject unknown chunk-strategy keys, suggest the closest key (d1a7129c)
- **config**: deprecate vod_store_strategy, VOD log book records skip (b025e031)
- **store**: overwrite keeps sbf_obs and other metadata datasets (46019e6f)
- **store**: add grid cells to stored data without losing the log book (33425a1a)
- **store**: never drop commits when promoting a temporary branch (6a1a9813)
- **store**: rebase out-of-date sessions on commit (5e34c39c)
- **store**: keep stored times correct whatever the sampling of later writes (f0039bd4)
- keep all sid coordinates in the preprocessing, aggregate without polars (5ed522e1)
- warn when the GNSS store metadata write fails (7ead6115)
- SBF epochs in GPS time; reject canopy and reference of different formats (1514daa6)
- **grids**: assign each observation to the cell that contains it (5250cc92)
- **readers,orchestrator**: epoch completeness check finds missing epochs (aea4c37d)
- **orchestrator**: reader_format auto knows RINEX 2 and NMEA, refuses mixed days (71347a07)
- FluentWorkflow and DataDirMatcher no longer depend on removed filemap code (97fd0e84)
- **workflows**: process_day fails on an empty day, cleanup deprecated (e20e33df)
- **orchestrator**: reference geometry from its own canopy's file, by start time (dcddeeff)
- **readers**: stop reading the settings file in RINEX to_ds (d59df2e1)
- **store**: store sbf_obs with its observations, never replace earlier days (75c574c6)
- **orchestrator**: build pipeline task tuples by parameter name (c03fb465)
- type annotations for receiver days and zarr store members (bcc3422b)
- **pipeline**: schedule days by the run's file discovery; undeprecate PairDataDirMatcher (75958456)
- **discovery**: process only canonical names unless a recipe is configured (d9a7620c)
- **pipeline**: store history counts files per action, not files seen (63b908a4)
- **pipeline**: shared file discovery, complete log-book rows, ordered overwrite (c5671d9e)
- **vod**: derive reference store group names from one place, not seven (dec7996e)
- **readers**: eliminate canvod-readers <-> canvod-auxiliary import cycle (b1d1c127)
- **cli**: remove broken stats CLI subcommand (c2bbb714)

### Perf

- **run**: estimate the main process per reader, so an SBF day fits (#452) (688492b1)
- **run**: skip stored days before reading them (75d35d49)
- **run**: grow a unit's day blocks before the next unit's Phase 1 (27cdad49)
- **run**: a run chains the VOD phase after each unit, without read-back (#427) (f39691cf)
- **vod**: compute VOD in the worker pool, one commit per unit (#426) (14108e95)
- **run**: a run works in units of days, committed once per unit (#425) (d474f5f9)
- **store**: a run reads each group's log book whole once, then only new rows (#421) (32d5ba2f)
- **orchestrator**: read a group's day blocks once per write, not per file (622a4eda)
- **discovery**: sort the files of a day by time (905eb89c)
- **discovery**: parse each file name once (52f33532)

### Refactor

- **store**: deprecate the append path, use day-block writes (#280) (7e9f8a8a)
- **cli**: one helper for the messages while finding files (6409cdd5)
- **grids**: one table of grid builders for create_hemigrid and GridFactory (0e9c3a71)
- **store**: grids and analysis results are stored by canvod-store (029a0a72)
- **resources**: deprecate the resource settings that have no effect (ce2b3488)
- **auxiliary**: deprecate the augmentation framework (d7f5b483)
- remove gnssvodpy leftovers, store version from canvod-store (5426a37a)
- **logging**: shared run context in canvod-utils, structlog loggers (c13eced7)
- **orchestrator**: one worker implementation for reference fan-out (A7e) (9d5768e2)
- **grids**: remove Hampel filtering (A7c) (c4583bae)
- **interpolation**: one epoch grid rule for all paths (A10, part 2) (5e82f27c)
- **interpolation**: one interpolator module (A10, part 1) (12d0239c)
- one SBF broadcast geometry path, ephemeris-based angles only (a43f7dae)
- **orchestrator**: remove the unused naming-block file mapping of the processor (c38c68ac)
- **api**: Pipeline.calculate_vod delegates to site.vod and is deprecated (d388ca52)
- **utils**: emit deprecations as FutureWarning (df32e70f)
- reword deprecation warnings to a single policy wording (57c2fdb1)
- **vod**: make VodComputer the single VOD implementation (cea3bf83)
- **utils**: move deprecation decorator to canvod-utils (a0be4d3f)

### Other

- fix three tests that fail in a full local run (6c648633)
- **deps-dev**: update uv-build requirement (278467a6)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- **store**: write the recipes as bytes so their sha256 matches on Windows (6e9b2a01)
- assert the refetch instead of printing it; drop an unused name (4beea06d)
- two Site objects in one process with a recipe link (895ee251)
- **deps**: take canvod-filemap from canvodpy-extensions #83 (2e1b1c4b)
- **cli**: strip color codes before reading the settings URL errors (4b03d038)
- **deps**: ty 0.0.90; silence its submit() findings in the pipeline (84ba05b2)
- neutral examples for the naming authority, network shares and a run-history decision (6fba3bfa)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- **run**: describe the VOD phase chained after each unit (#427) (e6aa9b08)
- **diagnostics**: cover the data-day key, no-walk stop and unit split (eab7a5f3)
- **diagnostics**: cover store sizes, the stage median and the line axis (34682490)
- **run**: describe units of days; hide the deprecated --days-per-batch (#425) (220351e9)
- **run**: units commit once, a day without orbits fails alone, units store what days store (#425) (fd642806)
- **run**: count the writing records by their calls, not the captured log (#423) (e2ed3a20)
- **test-data**: move to the test data with the example run history (443ed202)
- **canvodpy**: orchestrators built without __init__ set _workers (#278) (2a4fa184)
- **run**: compare the resume window with the local date, as the run does (#386) (58a4357f)
- **cli**: quote the chunk settings key in the migrate-layout help (#353) (a92c15eb)
- receiver checks fail when processing starts, not at creation (#353) (3c2c9e76)
- the run-ahead test no longer needs rescan (#353) (b54edb3f)
- **s3**: the S3 job no longer checks out test data (#367) (f94a0046)
- **canvodpy**: the compliance tests read groups through load_group (#367) (c3a7489f)
- **canvodpy**: end-to-end runs take orbits and clocks from the test data (#367) (112c68b0)
- **tests**: check out the test data again, so the end-to-end tests run (#367) (6ade5b11)
- **store**: two runs write one S3 store at the same time (#358) (#374) (c8c3b766)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- **canvodpy**: drop unused runtime dependencies; declare direct imports (#348) (df493896)
- remove empty file equal_area from the repository root (#347) (c9fefd13)
- **dashboard**: check the comparison, not only the export (241ba479)
- **dashboard**: seed labeled and heterogeneous runs (e591bb76)
- **vod**: VOD of two days is written in two commits (#276) (8a38e42a)
- **dashboard**: give the newest run resource samples for the charts (deebd6d3)
- **dashboard**: export without a sandbox and take the log folder from --logs-dir (d95294c1)
- **dashboard**: export the dashboard with and without runs (55de65a6)
- Refuse a first run when a new store's settings are missing (#342) (39fdb506)
- **canvodpy**: the forked-day end-to-end test rescans the data folders (#344) (3535d196)
- **orchestrator**: failed forked days count for the exit code (#334) (b2b60468)
- **orchestrator**: forked day on the test data, and two runs on one store (960e51bb)
- **run**: close the log handler's run history before deleting it (63519534)
- **run**: help test of --rescan ignores ANSI codes (9b3fd6ce)
- **cli**: cache the slow scan so the test fails when a scan precedes the message (b73c24d2)
- **canvodpy**: give mocked settings a log folder for the run history (193b8c10)
- **canvodpy**: declare psutil (821a9ffd)
- **discovery**: pin the results of a directory scan (ec6388d9)
- expect the rules check in the store compliance test (50874092)
- describe the STAC catalog of all stores, not a per-store STAC output (5149040c)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- made-up settings in every test, never the user's own file (e7e0b3ba)
- made-up people, sites and positions in all tests (51376b3f)
- US spellings and no em dashes in the store metadata, settings and store CLI texts (1a8c7242)
- US spellings in comments and docstrings, no em dashes in messages (7a48b9a3)
- made-up people and sites in canvod.utils.testing (035dc7a5)
- comments and docstrings no longer point to development notes (c3ad428a)
- **cli**: help texts in plain words, without Vale errors on the reference page (3a281189)
- **cli**: command-line reference page written from the --help texts (5b815645)
- describe reader detection correctly, suggest uv add in error messages (e56d109c)
- install with uv only, no pip examples (5e35cde8)
- take the notebooks out of the docs site and fix every dead link (4a61c53e)
- **pipeline**: describe the default loky path as it runs (064a8832)
- call the store of receiver data the GNSS store (d54bd124)
- name canvod-settings.yaml instead of the old split config files (ecdd8d54)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- install canvod-filemap through the workspace group "filemap" (8e059da9)
- list native Windows as supported (c08a80b6)
- state that macOS support is Apple silicon only (14789780)
- **cli**: strip ANSI codes before checking --config-dir in help text (5b8b6b36)
- **config**: run the config tests against canvod-settings.yaml (5f784847)

### Packages

- canvod-auxiliary ==1.0.0
- canvod-config ==1.0.0
- canvod-grids ==1.0.0
- canvod-ops ==1.0.0
- canvod-preflight ==1.0.0
- canvod-readers ==1.0.0
- canvod-store ==1.0.0
- canvod-store-metadata ==1.0.0
- canvod-utils ==1.0.0
- canvod-viz ==1.0.0
- canvod-vod ==1.0.0

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
