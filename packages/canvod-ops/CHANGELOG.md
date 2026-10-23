# Changelog

<!-- insertion marker -->
## canvod-ops-v1.0.0 (2026-10-24)

### Feat

- **store**: opening a store never creates it (71b7a888)
- **run**: check preprocessing against the stores before processing (e693932d)
- **ops**: integer variables take the first, last or middle value of a bin (e650e2f2)
- **ops**: record the version of every package that ran the preprocessing (67c4737f)
- record the preprocessing in the store log books, stop runs on a mismatch (00258166)
- **ops**: apply processing.preprocessing in every run, if set (A12) (8705b9f6)

### Fix

- **readers**: keep the fill value outside the LLI and SSI valid ranges (99c506cd)
- **store-metadata**: a store without repository metadata takes no data (552e2581)
- every stored epoch is GPS time (6e26041e)
- **store**: add grid cells to stored data without losing the log book (33425a1a)
- keep all sid coordinates in the preprocessing, aggregate without polars (5ed522e1)

### Refactor

- **grids**: one cell assignment implementation, as used by runs (A7b) (69651bd8)
- **config**: deprecate processing.preprocessing (A12) (c4a08ac4)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- made-up settings in every test, never the user's own file (e7e0b3ba)
- US spellings in comments and docstrings, no em dashes in messages (7a48b9a3)
- **ops**: canvod-store is a development dependency of canvod-ops (ef0daec8)
- install with uv only, no pip examples (5e35cde8)
- **release**: a version per package, chosen by the maintainer (6376257c)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
