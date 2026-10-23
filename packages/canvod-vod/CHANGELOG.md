# Changelog

<!-- insertion marker -->
## canvod-vod-v1.0.0 (2026-10-24)

### Feat

- **store**: pad day blocks to whole chunks, so every cadence is stored (#376) (3145f514)
- **store-metadata**: record who changes metadata, geodesy store type, description required (d1a029e5)
- **store-metadata**: check stores against CF, ACDD and zarr conventions (#208) (d569afff)
- **utils**: deprecate single arguments with deprecated_argument (13314723)
- **plugins**: readers and VOD calculators from installed packages (0200885b)
- **ops**: apply processing.preprocessing in every run, if set (A12) (8705b9f6)

### Fix

- **vod**: from_icechunkstore requires canopy_group and sky_group (aab1918b)
- **vod**: run the all-NaN delta SNR check for lazy inputs too (71fd8bfe)

### Refactor

- **logging**: shared run context in canvod-utils, structlog loggers (c13eced7)
- **utils**: emit deprecations as FutureWarning (df32e70f)
- **vod**: make VodComputer the single VOD implementation (cea3bf83)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- **deps-dev**: bump the dev tools and fix the new ty findings (779768f1)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- install with uv only, no pip examples (5e35cde8)
- **release**: a version per package, chosen by the maintainer (6376257c)
- call the store of receiver data the GNSS store (d54bd124)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- remove the last references to gnssvodpy (390ad3bc)
- **vod**: format the README code example (4c51faf1)
