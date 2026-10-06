# Release Process

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
- [ ] The release files (`pyproject.toml` files, `uv.lock`, `CHANGELOG.md`)
      have no uncommitted changes; `just release` refuses otherwise. Other
      changes in the working tree stay out of the release commit.

---

## Release Types

| Type | Version Bump | Example | When to use |
|------|-------------|---------|-------------|
| Patch | `0.1.X` | 0.1.0 → 0.1.1 | Bug fixes only, fully backwards compatible |
| Minor | `0.X.0` | 0.1.0 → 0.2.0 | New features, backwards compatible |
| Major | `X.0.0` | 0.9.0 → 1.0.0 | Breaking changes — requires migration guide |

---

## Step-by-Step

### 1. Prepare

```bash
git checkout main
git pull origin main
just test && just check
```

### 2. Create the release

```bash
just release 0.2.0
```

This command:

1. Runs all tests (`just test`)
2. Bumps the version of all packages (`just bump`: `cz bump --files-only`,
   which also writes the new section of `CHANGELOG.md`, then `uv lock`)
3. Creates the branch `release/v0.2.0` and commits exactly the release
   files: `bump: version X.Y.Z → 0.2.0`

It creates no tag: the tag belongs on the merged commit on `main` (step 5).

### 3. Review

```bash
git show --stat     # the version files, uv.lock and CHANGELOG.md, nothing else
```

### 4. Open a PR for the release commit

`main` requires a PR. Push the branch and open one:

```bash
git push -u origin release/v0.2.0
gh pr create --title "bump: version X.Y.Z → 0.2.0" --body "..."
```

Merge the PR once CI passes.

### 5. Tag the merged commit

A merge can give the release a different commit than the one on the
branch, so the tag is created only now, on `main`:

```bash
git switch main
git pull origin main
git tag -a "v0.2.0" -m "Release v0.2.0"
git push origin v0.2.0
```

### 6. Publish GitHub Release

The `.github/workflows/release.yml` workflow detects the new tag and creates a **draft** release. Review and publish at [github.com/nfb2021/canvodpy/releases](https://github.com/nfb2021/canvodpy/releases).

Pushing the tag does **not** publish to PyPI — tagging/versioning and PyPI
publishing are deliberately decoupled (see step 7).

### 7. Publish to PyPI (separate, manual, whenever you decide)

Not automatic. Trigger `publish_pypi.yml` explicitly, either from the
[Actions tab](https://github.com/nfb2021/canvodpy/actions/workflows/publish_pypi.yml)
("Run workflow", choosing the tag/ref to build from) or:

```bash
gh workflow run publish_pypi.yml --ref v0.2.0 -f version=0.2.0
```

You can create several tags/GitHub releases before ever running this — a
tag existing is not a promise that PyPI has it.

### 8. Post-release

- Monitor issues for regressions
- Create a Zenodo snapshot for DOI ([Zenodo Setup](guides/ZENODO_SETUP.md))
- Update citation information if needed

---

## Troubleshooting

??? failure "Tests fail during release"
    Fix the failing tests on `main` before retrying `just release`.

??? failure "Release files have uncommitted changes"
    `just release` refuses when a `pyproject.toml`, `uv.lock` or
    `CHANGELOG.md` already has changes, so they cannot slip into the
    release commit. Commit them in their own pull request, or discard them.

??? failure "Version bump fails"
    Use an explicit `X.Y.Z` format (no `v` prefix):
    ```bash
    just release 0.2.0    # correct
    just release v0.2.0   # wrong
    ```

??? failure "Tag already exists"
    A pushed release tag is not moved: release the next patch version
    instead. A tag that exists only locally can be deleted with
    `git tag -d v0.2.0`.

??? failure "Draft release did not appear"
    Verify the tag matches the pattern `v*.*.*` at
    [github.com/nfb2021/canvodpy/actions](https://github.com/nfb2021/canvodpy/actions).
    (PyPI publishing never triggers from a tag push at all — see step 6.)

---

## Manual Release (Fallback)

```bash
just changelog v0.2.0
```

Then create a release manually at [github.com/nfb2021/canvodpy/releases/new](https://github.com/nfb2021/canvodpy/releases/new).
