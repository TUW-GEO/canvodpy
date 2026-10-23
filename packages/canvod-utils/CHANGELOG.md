# Changelog

<!-- insertion marker -->
## canvod-utils-v1.0.0 (2026-10-24)

### BREAKING CHANGES

- **cli**: one site per run; --update-to-latest replaces the default dates (379d4265)
- **config**: fetch settings and recipes from a link in every run, record no URL (112b91a5)
- **logging**: require the log folder and make the timing events complete (242d3516)

### Feat

- **cli**: one site per run; --update-to-latest replaces the default dates (379d4265)
- **config**: fetch settings and recipes from a link in every run, record no URL (112b91a5)
- **utils**: files from a pinned GitHub URL (canvod.utils.pinned) (2cf3d18e)
- **utils**: add a shared directory_size_bytes helper and reuse it (01b6d9fc)
- **store-metadata**: rules from the standards for metadata fields (#251) (73927342)
- **utils**: deprecate single arguments with deprecated_argument (13314723)
- **plugins**: readers and VOD calculators from installed packages (0200885b)

### Fix

- **utils**: a new Site or Airflow task is a new run; other links record their host (4913f39d)
- **utils**: one fetch per run across processes; a link is recorded only as the file name of a raw file link or as its host, never in full (01305cf1)
- **utils**: walk a folder's size without failing on files that vanish (c7a6a396)
- **utils**: add a random part to run IDs, so runs on two machines differ (#377) (4d501d4b)
- **types**: clear the type checker findings in code, scripts and tests (238e7368)
- **logging**: require the log folder and make the timing events complete (242d3516)

### Refactor

- **utils**: drop the unused software attributes (2e54f9d1)
- one file hash for all readers (0e35ce40)
- **logging**: shared run context in canvod-utils, structlog loggers (c13eced7)
- **utils**: emit deprecations as FutureWarning (df32e70f)
- **utils**: move deprecation decorator to canvod-utils (a0be4d3f)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- **utils**: run folders are removed when the process ends; each Airflow task reads the link again (c1a23595)
- **utils**: drop the sentence on when the system empties the cache (65a1d27e)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- made-up settings in every test, never the user's own file (e7e0b3ba)
- made-up people, sites and positions in all tests (51376b3f)
- US spellings and no em dashes in the store metadata, settings and store CLI texts (1a8c7242)
- made-up people and sites in canvod.utils.testing (035dc7a5)
- install with uv only, no pip examples (5e35cde8)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- verify utils, store-metadata, ops, grids and readers pages against the code (05b4aa23)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
