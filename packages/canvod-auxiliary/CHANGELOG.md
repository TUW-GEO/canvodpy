# Changelog

<!-- insertion marker -->
## canvod-auxiliary-v1.0.0 (2026-10-24)

### Feat

- **store-metadata**: each day has its own cadence in the snapshot summary (9fef8e25)
- **store-metadata**: check stores against CF, ACDD and zarr conventions (#208) (d569afff)
- **utils**: deprecate single arguments with deprecated_argument (13314723)

### Fix

- **auxiliary**: give downloaded files the mode of a new file, not mkstemp's 0600 (#462) (bbd9ffd2)
- **auxiliary**: download each file to its own temp file and turn CLK off by default (#462) (84b0edce)
- **readers**: the NMEA reader gives the receiver position from the GGA fixes (#451) (399947f1)
- **auxiliary**: product downloads log through structlog instead of printing (#398) (772ab7e0)
- **readers,auxiliary**: write only CF standard names (9ef9b27f)
- **canvodpy**: write failures stop the run, settings are passed down (6dfbaf10)
- **auxiliary**: declare rich as a dependency (10f25953)
- every stored epoch is GPS time (6e26041e)
- **auxiliary**: join orbits and clocks with the neighboring days (bf3b8da2)
- aggregate_glonass_fdma reaches the readers, the SID padding and the orbit data (ac914453)
- **auxiliary**: registry checked against the servers, final/rapid only, several samplings per product (61031fa4)
- **auxiliary**: read the CLK clock bias in seconds (608b9f9e)
- **readers**: eliminate canvod-readers <-> canvod-auxiliary import cycle (b1d1c127)
- **auxiliary**: wire ClockConfig.window_size into jump detection (c4a0d81e)

### Refactor

- **auxiliary**: deprecate the augmentation framework (d7f5b483)
- **auxiliary**: import pipeline and augmentation unconditionally (76a98111)
- remove gnssvodpy leftovers, store version from canvod-store (5426a37a)
- **logging**: shared run context in canvod-utils, structlog loggers (c13eced7)
- **interpolation**: one epoch grid rule for all paths (A10, part 2) (5e82f27c)
- one SBF broadcast geometry path, ephemeris-based angles only (a43f7dae)

### Other

- fix three tests that fail in a full local run (6c648633)
- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- **deps-dev**: bump the dev tools and fix the new ty findings (779768f1)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- made-up people, sites and positions in all tests (51376b3f)
- US spellings in comments and docstrings, no em dashes in messages (7a48b9a3)
- drop em dashes from the docs and the SBF source attributes, US spelling (40c29e20)
- comments and docstrings no longer point to development notes (c3ad428a)
- install with uv only, no pip examples (5e35cde8)
- **release**: a version per package, chosen by the maintainer (6376257c)
- **auxiliary**: day join on the real CODE files of the neighboring days (7a6bbcb8)
- name canvod-settings.yaml instead of the old split config files (ecdd8d54)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- format Python code examples in package READMEs and CLAUDE.md files (82f11191)
- **auxiliary**: correct the server strategy comment in products.toml (0e0334b9)
- **auxiliary**: delete shadowed, unreachable interpolation.py (2655373e)
