---
name: release
description: Release canvodpy and chosen packages (each package has its own version) - versions, changelogs, PR, tags, GitHub Release, PyPI. Use only when the user asks to release.
disable-model-invocation: true
---

# Release canvodpy

Each package has its own version and tag `<package>-vX.Y.Z`; the umbrella
`canvodpy` pins every package exactly, is part of every release and keeps
the tag `vX.Y.Z` (ADR 0010). The long form, with troubleshooting, is
`docs/RELEASING.md`. Tags, GitHub Releases and PyPI uploads are public and
permanent: the user chooses the packages and versions; confirm them before
preparing the release, again before tagging, and again before publishing
to PyPI.

## Before

- Submodule pointers (`demo`, `packages/canvod-readers/tests/test_data`)
  point at the commits meant for this release.
- canvod-filemap is taken from a tag or commit of canvodpy-extensions, not
  a branch (root `pyproject.toml`, see the `extensions-dependency` guide).
- Deprecated code stays in every 1.x release; v2.0.0 removes it.
- `just check` and `just test` pass.
- The release files (`pyproject.toml` files, `uv.lock`, the `CHANGELOG.md`
  files, `CITATION.cff`, `.zenodo.json`, `codemeta.json`) have no
  uncommitted changes; `just release` refuses otherwise and
  commits only those files.

## Steps

1. `just release-status` lists, per package, the commits since its last
   tag. Show it to the user; the user chooses the packages and versions.
2. `just release <package>=X.Y.Z ... canvodpy=X.Y.Z`. It runs the tests,
   checks the choice (canvodpy included, its increment at least the
   largest, ranges between packages admit the new versions), writes the
   versions, canvodpy's pins, the changelogs, canvodpy's version and the
   date in the citation files (Zenodo takes the version from them) and
   `uv.lock`, and commits
   them on the new branch `release/vX.Y.Z` (canvodpy's version); no tag.
   Push that branch and open a PR. The user merges it; an agent never
   merges (`CODING_STANDARDS.md`, Git and GitHub).
3. On the merged `main`, the user runs `just tag-release` and pushes the
   tags it names; an agent never creates or pushes release tags. GitHub
   Actions drafts the GitHub Release of the canvodpy tag; the user
   publishes it.
4. PyPI is a separate, manual step the user triggers:
   `gh workflow run publish_pypi.yml --ref vX.Y.Z`. It publishes the
   packages whose release tag points at that commit.
5. Afterwards canvodpy-extensions takes the new versions from PyPI (their
   `canvodpy-dependency` guide).
