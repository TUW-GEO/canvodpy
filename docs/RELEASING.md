# Release process

!!! warning "Maintainers only"
    This guide is for repository maintainers with push access to the main branch.

---

## Prerequisites

Before starting a release:

- [ ] All CI checks passing on `main`
- [ ] `main` branch is stable
- [ ] All changes committed and pushed
- [ ] You are a maintainer: `main` requires a PR (step 4), and only
      maintainers can create release tags (step 5)
- [ ] The release files (`pyproject.toml` files, `uv.lock`, the
      `CHANGELOG.md` files, `CITATION.cff`, `.zenodo.json`,
      `codemeta.json`) have no uncommitted changes; `just release`
      refuses otherwise. Other changes in the working tree stay out of the
      release commit.

---

## Release types

Each package has its own version ([Versioning](VERSIONING.md)); choose the
increment of each package you release:

| Type | Version Bump | Example | When to use |
|------|-------------|---------|-------------|
| Patch | `1.1.X` | 1.1.0 $\rightarrow$ 1.1.1 | Bug fixes only, fully backwards compatible |
| Minor | `1.X.0` | 1.1.0 $\rightarrow$ 1.2.0 | New features, backwards compatible |
| Major | `X.0.0` | 1.4.0 $\rightarrow$ 2.0.0 | Breaking changes; requires a migration guide |

canvodpy is part of every release, and its increment is at least the
largest of the packages released with it.

To test a release first, publish it as a pre-release (`1.0.0a1`,
`1.0.0b1`, `1.0.0rc1`); [Versioning](VERSIONING.md#pre-releases) explains
the stages and when to choose which. The steps below are the same.

---

## Step-by-step

### 1. Prepare

```bash
git checkout main
git pull origin main
just test && just check
```

### 2. Choose the packages and versions

```bash
just release-status
```

For each package: its version, its last release tag, and the commits since
that tag that touched the package's folder. Release a package when its
commits matter to its users, at the increment they call for.

### 3. Create the release

```bash
just release canvod-store=1.1.0 canvod-grids=1.0.1 canvodpy=1.1.0
```

This command:

1. Runs all tests (`just test`)
2. Refuses the release, and says why, when canvodpy is missing, a version
   does not go up or is tagged already, canvodpy's increment is smaller
   than a package's, a package's range on another excludes the new
   version, a citation file lacks its version or date field, or a release
   file has uncommitted changes
3. Writes the new versions, canvodpy's `==` pins, a section in each
   released package's `CHANGELOG.md` (from the commits that touched its
   folder; canvodpy's lists the pinned versions), canvodpy's version and
   today's date in `CITATION.cff`, `.zenodo.json` and `codemeta.json`
   (Zenodo takes the version of the archived record from them), and
   `uv.lock`
4. Creates the branch `release/v1.1.0` (canvodpy's version) and commits
   exactly the release files:
   `bump: canvodpy 1.1.0 (canvod-store 1.1.0, canvod-grids 1.0.1)`

It creates no tag: the tags belong on the merged commit on `main` (step 6).

### 4. Review

```bash
git show --stat     # the version files, uv.lock and CHANGELOG.md files, nothing else
```

The changelog sections are generated from commit subjects; edit them in
the release branch if a line needs it.

### 5. Open a PR for the release commit

`main` requires a PR. Push the branch and open one:

```bash
git push -u origin release/v1.1.0
gh pr create --title "bump: canvodpy 1.1.0 (canvod-store 1.1.0, canvod-grids 1.0.1)" --body "..."
```

Merge the PR once CI passes.

### 6. Tag the merged commit

A merge can give the release a different commit than the one on the
branch, so the tags are created only now, on `main`:

```bash
git switch main
git pull origin main
just tag-release
git push origin v1.1.0 canvod-store-v1.1.0 canvod-grids-v1.0.1
```

`just tag-release` creates an annotated tag for every package version that
has no tag yet, and prints the push command; it does not push.

### 7. Publish GitHub release

The `.github/workflows/release.yml` workflow detects the canvodpy tag
(`v1.1.0`) and creates a **draft** release whose notes are canvodpy's
`CHANGELOG.md` section, including the package versions. Package tags get no
GitHub release of their own. Review and publish at
[github.com/nfb2021/canvodpy/releases](https://github.com/nfb2021/canvodpy/releases).

Pushing the tags does **not** publish to PyPI: tagging and PyPI
publishing are deliberately decoupled (see step 8).

### 8. Publish to PyPI (separate, manual, whenever you decide)

Not automatic. Trigger `publish_pypi.yml` on the canvodpy tag, either from
the
[Actions tab](https://github.com/nfb2021/canvodpy/actions/workflows/publish_pypi.yml)
(the Run workflow button; choose the tag) or:

```bash
gh workflow run publish_pypi.yml --ref v1.1.0
```

It builds and uploads exactly the packages whose release tag points at that
commit (`scripts/release.py tagged`), here canvodpy, canvod-store and
canvod-grids. You can create several releases before ever running this: a
tag existing is not a promise that PyPI has it.

### 9. Post-release

- Monitor issues for regressions
- Check the Zenodo record the release created: its version must be
  canvodpy's ([Zenodo Setup](guides/ZENODO_SETUP.md))

---

## Troubleshooting

??? failure "Tests fail during release"
    Fix the failing tests on `main` before retrying `just release`.

??? failure "Not released"
    `just release` names every problem it found; nothing was changed.
    Typical ones:

    - *canvodpy pins every package*: add `canvodpy=X.Y.Z`.
    - *canvod-store makes a minor release, canvodpy only a patch*: raise
      canvodpy's version.
    - *canvod-grids requires canvod-store<2,>=1.0.0, which excludes
      canvod-store 2.0.0*: check canvod-grids against the new major version,
      widen its range in its own pull request, then release both.
    - *Release files have uncommitted changes*: commit them in their own
      pull request, or discard them.

??? failure "Version is not a version"
    Use `NAME=X.Y.Z` with an explicit version (no `v` prefix):
    ```bash
    just release canvodpy=1.1.0    # correct
    just release canvodpy=v1.1.0   # wrong
    ```

??? failure "Tag already exists"
    A pushed release tag is not moved: release the next patch version
    instead. A tag that exists only locally can be deleted with
    `git tag -d v1.1.0`.

??? failure "Draft release did not appear"
    Verify the canvodpy tag matches the pattern `v*.*.*` at
    [github.com/nfb2021/canvodpy/actions](https://github.com/nfb2021/canvodpy/actions),
    and that `CHANGELOG.md` has a section `## v1.1.0 (...)`.
    (PyPI publishing never triggers from a tag push at all; see step 7.)
