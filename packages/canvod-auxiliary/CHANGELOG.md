# Changelog

<!-- insertion marker -->
## canvod-auxiliary-v1.1.0 (2026-11-07)

### Feat

- **auxiliary**: keep the Hermite orbit interpolation as sp3_interpolation: hermite (df576f1c6)
- **canvodpy**: cache the broadcast orbits in the shared aux cache (#573) (97dc86155)
- **auxiliary**: broadcast SBAS orbits from RINEX navigation files (9ade2ec55)
- **auxiliary**: broadcast orbits of GLONASS from RINEX navigation files (#569) (4cfd7f523)
- **auxiliary**: broadcast orbits of Galileo, BeiDou and QZSS from RINEX navigation files (68f242a44)
- **auxiliary**: GPS broadcast orbits through the Hermite path (19b72b949)
- **cli**: banner and colours that follow the terminal (78880e7cc)

### Fix

- **auxiliary**: interpolate orbits with a polynomial of degree 10 (#563) (bcb6b808b)
- **canvodpy**: cache the orbits once per satellite in the shared aux cache (#573) (6960d1996)
- **canvodpy**: review of the broadcast ephemeris of RINEX files (84dd8b9cf)
- **auxiliary**: read JPL and IAC clock files, from_file reads its product (ccc35aed3)

### Perf

- **auxiliary**: parse each CLK epoch once and fill the array at once (#433) (ac4d3394f)
- **auxiliary**: interpolate each distinct orbit and clock column once (#433) (acf0cbbf0)

### Refactor

- rename _preprocess_aux_data_with_hermite, remove stray test_mwe.py (0dc4254c8)
- **config**: deprecate ephemeris source final, use precise (e98cc5541)

### Other

- **auxiliary**: a strategy's result carries no per-column coordinates (#433) (e12e89d04)
- **auxiliary**: cite DO-229D for the SBAS time-out (1992e82d7)
- **auxiliary**: name DO-229C Table A-25 for the SBAS validity, rewrap nav docstrings (3ef19003b)
- **auxiliary**: stop the equator test from rejecting its own examples (6f6660ac2)
- **auxiliary**: fit interval wording; rewrap the broadcast docs paragraph (0496676e2)
- broadcast ephemeris from RINEX navigation files (ea71a785f)
- **auxiliary**: clearer failures of the network tests (ec1d0baa0)
- **auxiliary**: network tests of the registry products, downloads and a downloading run (d974ff04c)
- end the authors line with the licence (bbc0dd886)
- name the authors without a copyright claim (709349710)
- restore the Apache placeholder in the LICENSE appendix (dcf035fd7)
- drop the copyright line and symbol (9035910a7)

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
