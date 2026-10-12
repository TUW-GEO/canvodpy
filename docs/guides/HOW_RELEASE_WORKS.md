# How the release infrastructure works

This page documents the release chain, from commit message to PyPI upload.
The steps to follow are in [Releasing](../RELEASING.md); the rules behind
the versions are in [Versioning](../VERSIONING.md).

<div class="grid cards" markdown>

-   :fontawesome-solid-comment: &nbsp; **Conventional Commits**

    ---

    Structured commit messages (`feat`, `fix`, `docs` and others), checked by
    commitizen on every commit. They fill the changelogs.

    [:octicons-arrow-right-24: Details](#1-conventional-commits)

-   :fontawesome-solid-tag: &nbsp; **Versions per package**

    ---

    Each package has its own version, chosen by the maintainer;
    `canvodpy` pins every package exactly. `scripts/release.py` checks the
    choice and writes versions, pins, changelogs and `uv.lock`.

    [:octicons-arrow-right-24: Details](#2-versions-and-changelogs)

-   :fontawesome-brands-github: &nbsp; **GitHub Releases**

    ---

    The canvodpy tag starts a workflow that drafts a GitHub release from
    canvodpy's `CHANGELOG.md` section and waits for the maintainer.

    [:octicons-arrow-right-24: Details](#3-github-releases)

-   :fontawesome-solid-box-open: &nbsp; **PyPI Publishing**

    ---

    `publish_testpypi.yml` (canvodpy pre-release tags) and
    `publish_pypi.yml` (started by hand, never by a tag) publish the
    packages whose release tag points at the commit.

    [:octicons-arrow-right-24: Details](#4-pypi-publishing)

-   :fontawesome-solid-lock: &nbsp; **OIDC Authentication**

    ---

    Short-lived tokens from GitHub, no stored API keys.

    [:octicons-arrow-right-24: Details](#5-trusted-publishing-with-oidc)

</div>

---

## 1. Conventional commits

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

```
feat(readers): add RINEX 4.0 support
fix(vod): correct tau calculation
docs: update installation guide
```

The commit-msg hook (installed by `just hooks`, `.pre-commit-config.yaml`)
runs commitizen's check and rejects other messages (`fixed bug`, `WIP`).
The `[tool.commitizen]` section of the root `pyproject.toml` configures
only this check; commitizen does not bump versions here.

The types sort the changelog lines (`feat` $\rightarrow$ Feat, `fix` $\rightarrow$ Fix, `perf`,
`refactor`, everything else $\rightarrow$ Other; `type!:` $\rightarrow$ BREAKING CHANGES). They do
not decide the version: the maintainer does.

---

## 2. Versions and changelogs

`scripts/release.py`, through three recipes:

| Recipe | What it does |
|--------|--------------|
| `just release-status` | For each package: version, last release tag, and the commits since that tag that touched the package's folder |
| `just release canvod-store=1.1.0 canvodpy=1.1.0` | Runs the tests, checks the choice, writes the versions, canvodpy's pins, the changelogs and `uv.lock`, commits them on `release/v1.1.0` |
| `just tag-release` | On the merged commit on `main`: tags every package version without a tag; does not push |

**Checks before anything is written** (a refused release names every
problem and changes nothing):

1. canvodpy is part of the release (it pins every package).
2. Each version goes up and has no tag yet.
3. canvodpy's increment (patch, minor, major) is at least the largest
   increment of the packages released with it.
4. Every package that requires a released package (`canvod-config>=1.0.0,<2`)
   admits the new version; a major release needs the ranges widened by
   hand first.
5. The release files (`pyproject.toml` files, `uv.lock`, `CHANGELOG.md`
   files) have no uncommitted changes.

**Changelogs.** Every package has a `CHANGELOG.md` in its folder; canvodpy's
is the one at the repository root. A release inserts a section after the
`<!-- insertion marker -->` line of each released package, built from the
commits since its last tag that touched its folder (`git log <tag>..HEAD --
<folder>`). canvodpy's section lists its own commits and every pinned
package version, marking the new ones. The sections can be edited in the
release pull request.

**Tags.** `<package>-vX.Y.Z` for the packages (`canvod-store-v1.1.0`),
`vX.Y.Z` for canvodpy. A package without a tag of its own (before
per-package versions) counts from the last `vX.Y.Z` tag, when all packages
were released together. Versions are written as Python normalizes them, so
a pre-release is `1.1.0rc1`, tagged `v1.1.0rc1`.

---

## 3. GitHub releases

`.github/workflows/release.yml` runs when a canvodpy tag (`v*.*.*`) is
pushed. Package tags (`canvod-store-v1.1.0`) do not match and get no
release of their own, so Zenodo archives one version per canvodpy release.

1. Checks out the tagged commit.
2. Takes canvodpy's `CHANGELOG.md` section for the tag (from `## v1.1.0 (`
   to the next `## `) as the release notes; fails if there is none.
3. Creates a **draft** release (a pre-release for `a`, `b` and `rc`
   versions) and waits for the maintainer to publish it.

```
Maintainer                          GitHub Actions               GitHub
    | just release ..., PR, merge         |                           |
    | just tag-release, git push tags     |                           |
    |----------------------------------------------------------------->|
    |                                     | v1.1.0 pushed             |
    |                                     |<--------------------------|
    |                                     | notes from CHANGELOG.md   |
    |                                     | draft release             |
    |                                     |-------------------------->|
    | review the draft, "Publish release" |                           |
    |----------------------------------------------------------------->|
```

---

## 4. PyPI publishing

| Workflow | Runs on | Publishes to |
|----------|---------|--------------|
| `publish_testpypi.yml` | push of a canvodpy pre-release tag (`v*.*.*a*`, `b*`, `rc*`), or by hand | TestPyPI |
| `publish_pypi.yml` | by hand only: `gh workflow run publish_pypi.yml --ref v1.1.0` | PyPI |

Both check out the tagged commit with all tags and build exactly the
packages whose release tag points at that commit
(`scripts/release.py tagged`): for the `v1.1.0` example, canvodpy and
canvod-store, nothing else. Tagging and publishing to PyPI are separate
decisions: a tag is not a promise that PyPI has the version.

**PyPI** (Python Package Index) hosts wheels and source distributions;
**TestPyPI** is its sandbox. Uploads to PyPI are permanent: a version can
never be uploaded twice, so a broken release is fixed by the next patch
version. The one-time account and project setup is in
[PyPI Setup](PYPI_SETUP.md).

---

## 5. Trusted Publishing with OIDC

The workflows authenticate to (Test)PyPI with OpenID Connect instead of
stored API tokens:

1. GitHub issues the workflow run a short-lived token (JWT) saying which
   repository, workflow, and environment it is.
2. The workflow sends it to PyPI with the upload
   (`pypa/gh-action-pypi-publish`, permission `id-token: write`).
3. PyPI checks the signature and that repository, workflow, and environment
   match a trusted publisher configured for the project, then accepts the
   upload.

Each project on PyPI (every package is its own project) needs the trusted
publisher once:

```
Owner:             nfb2021
Repository name:   canvodpy
Workflow name:     publish_pypi.yml   (publish_testpypi.yml on TestPyPI)
Environment name:  pypi               (testpypi on TestPyPI)
```

The GitHub environments `pypi` and `testpypi` (Settings $\rightarrow$ Environments)
can require a reviewer and a wait timer before the upload runs.

**Why OIDC:** no secret to store or rotate, the token is valid for minutes
and only for this repository and workflow.

---

## Complete example

Releasing a fix in canvod-grids and a feature in canvod-store:

```bash
git switch main && git pull origin main
just release-status
# canvod-grids 1.0.0 (since canvod-grids-v1.0.0: 1 commits)
#     1a2b3c4 fix(grids): ...
# canvod-store 1.0.0 (since canvod-store-v1.0.0: 3 commits)
#     ...
just release canvod-grids=1.0.1 canvod-store=1.1.0 canvodpy=1.1.0
git push -u origin release/v1.1.0
gh pr create --title "bump: canvodpy 1.1.0 (canvod-grids 1.0.1, canvod-store 1.1.0)" --body "..."
# merged once CI passes, then on main:
git switch main && git pull origin main
just tag-release
git push origin v1.1.0 canvod-grids-v1.0.1 canvod-store-v1.1.0
# draft release v1.1.0 appears: review, publish
gh workflow run publish_pypi.yml --ref v1.1.0
```

Users then install `uv add canvodpy==1.1.0` (the whole tested mix) or
`uv add canvod-store==1.1.0` on its own.

---

## Troubleshooting

### Commit message rejected

`Commit message does not follow conventional commits format`: write
`type(scope): subject`, for example `git commit --amend -m "fix(vod): correct tau
calculation"`.

### Release refused

`just release` prints `Not released:` and one line per problem; nothing
was written. See [Releasing](../RELEASING.md#troubleshooting).

### Draft release missing

The tag must be a canvodpy tag (`v1.1.0`), and `CHANGELOG.md` must have a
section `## v1.1.0 (...)` on the tagged commit.

### PyPI workflow publishes nothing

`No package's release tag points at this commit`: run it with
`--ref <canvodpy tag>` after `just tag-release` and pushing the tags.

### OIDC upload failing

`The workflow is not configured for publishing`: check that the project on
PyPI has the trusted publisher described earlier (each package separately), with the
same workflow file and environment name, and that the workflow has
`id-token: write`.
