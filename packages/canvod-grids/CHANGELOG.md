# Changelog

<!-- insertion marker -->
## canvod-grids-v1.0.0 (2026-10-24)

### BREAKING CHANGES

- **store**: grids and analysis results are stored by canvod-store (029a0a72)

### Feat

- **store-metadata**: check stores against CF, ACDD and zarr conventions (#208) (d569afff)
- **utils**: deprecate single arguments with deprecated_argument (13314723)

### Fix

- **grids**: equal_area cutoff_theta trims the horizon only (59dd8f92)
- **grids**: end equirectangular sectors exactly at 2*pi (8fcd7289)
- **store**: add grid cells to stored data without losing the log book (33425a1a)
- **store**: rebase out-of-date sessions on commit (5e34c39c)
- **grids**: assign each observation to the cell that contains it (5250cc92)
- **grids**: drop deprecated data_var in workflow cell assignment (A7b) (c860ec09)

### Refactor

- **grids**: one table of grid builders for create_hemigrid and GridFactory (0e9c3a71)
- **store**: grids and analysis results are stored by canvod-store (029a0a72)
- remove gnssvodpy leftovers, store version from canvod-store (5426a37a)
- **logging**: shared run context in canvod-utils, structlog loggers (c13eced7)
- **grids**: remove Hampel filtering (A7c) (c4583bae)
- **grids**: one cell assignment implementation, as used by runs (A7b) (69651bd8)
- reword deprecation warnings to a single policy wording (57c2fdb1)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- US spellings and no em dashes in the store metadata, settings and store CLI texts (1a8c7242)
- US spellings in comments and docstrings, no em dashes in messages (7a48b9a3)
- drop em dashes from the docs and the SBF source attributes, US spelling (40c29e20)
- describe reader detection correctly, suggest uv add in error messages (e56d109c)
- install with uv only, no pip examples (5e35cde8)
- **release**: a version per package, chosen by the maintainer (6376257c)
- **grids**: correct solid angle and cell counts in equal-angle and equirectangular docstrings (8e360770)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- format Python code examples in package READMEs and CLAUDE.md files (82f11191)
