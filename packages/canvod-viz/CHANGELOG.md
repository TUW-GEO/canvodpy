# Changelog

<!-- insertion marker -->
## canvod-viz-v1.0.0 (2026-10-24)

### Feat

- **viz**: interactive hemisphere selectors as canvod.viz.widgets (48a45cf7)

### Fix

- **viz**: plot_3d_mesh draws every grid, elevation_rings are elevations (9867d836)
- **viz**: draw 3D cells without data in their own color (3b2e7d62)

### Other

- **deps-dev**: update uv-build requirement (278467a6)
- packages require each other at >=1.0.0 (a8f39f0f)
- point repository URLs to TUW-GEO (3c5dd855)
- **release**: 1.0.0 is stable (d82eaf28)
- uniform PyPI metadata; every package ships LICENSE and NOTICE (#189) (9306e8f5)
- one README structure for every package; PyPI and Zenodo texts (#362) (86a98643)
- require uv_build 0.13, the uv version the workspace requires (c928b27f)
- **viz**: the hemisphere selectors and their install extra (b3fd8ab4)
- host documentation at canvodpy.eu instead of GitHub Pages default domain (e3e444c7)
- describe reader detection correctly, suggest uv add in error messages (e56d109c)
- install with uv only, no pip examples (5e35cde8)
- **release**: a version per package, chosen by the maintainer (6376257c)
- pin the packages canvodpy installs, read versions from the install (da448cf6)
- agent instructions as AGENTS.md, task guides, checks, code graph (720298cb)
- format Python code examples in package READMEs and CLAUDE.md files (82f11191)
