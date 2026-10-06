---
name: release
description: Release canvodpy (all packages share one version) - changelog, version bump, PR, tag, GitHub Release, PyPI. Use only when the user asks to release.
disable-model-invocation: true
---

# Release canvodpy

All packages of this repository carry the same version and are released
together under the tag `v<version>`. The long form, with troubleshooting,
is `docs/RELEASING.md`. Tags, GitHub Releases and PyPI uploads are public
and permanent: confirm the version with the user before tagging and again
before publishing to PyPI.

## Before

- Submodule pointers (`demo`, `packages/canvod-readers/tests/test_data`)
  point at the commits meant for this release.
- canvod-filemap is taken from a tag or commit of canvodpy-extensions, not
  a branch (root `pyproject.toml`, see the `extensions-dependency` guide).
- Deprecated code stays in every 1.x release; v2.0.0 removes it.
- `just check` and `just test` pass.
- The release files (`pyproject.toml` files, `uv.lock`, `CHANGELOG.md`)
  have no uncommitted changes; `just release` refuses otherwise and commits
  only those files.

## Steps

1. `just release X.Y.Z`. It runs the tests, bumps every package (`just
   bump`: version files, `CHANGELOG.md`, `uv.lock`) and commits exactly
   those files on the new branch `release/vX.Y.Z`; it creates no tag.
   Push that branch and open a PR for the commit. The user merges it; an
   agent never merges (`CODING_STANDARDS.md`, Git and GitHub).
2. On the merged `main`, the user creates the annotated tag `vX.Y.Z` and
   pushes it; an agent never pushes tags. GitHub Actions drafts the
   GitHub Release; the user publishes it.
3. PyPI is a separate, manual step the user triggers:
   `gh workflow run publish_pypi.yml --ref vX.Y.Z -f version=X.Y.Z`.
4. Afterwards canvodpy-extensions takes the new version from PyPI (their
   `canvodpy-dependency` guide).
