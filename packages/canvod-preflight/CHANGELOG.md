# Changelog

<!-- insertion marker -->
## canvod-preflight-v1.0.0 (2026-10-24)

### Feat

- **plugins**: readers and VOD calculators from installed packages (0200885b)
- **preflight**: keep only the naming convention, deprecate mapping and validation (b2d9ea0f)
- **discovery**: one overlap check on canonical names for discovery and batch writes (8bea03a1)

### Fix

- **preflight**: find_overlaps raises TypeError instead of assert (b5b512c7)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- **naming**: examples from the test persona; the diagram's content and format fields (9b9d02c8)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- link the extensions at extensions.canvodpy.eu; fix the preflight docs URL (c0da5336)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- made-up people, sites and positions in all tests (51376b3f)
- US spellings in comments and docstrings, no em dashes in messages (7a48b9a3)
- **release**: a version per package, chosen by the maintainer (6376257c)
- name canvod-settings.yaml instead of the old split config files (ecdd8d54)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- **preflight**: parse UBX and NMEA canonical names (66c0732e)
