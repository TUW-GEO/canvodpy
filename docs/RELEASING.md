# Release process

!!! warning "Maintainers only"
    This guide is for repository maintainers with push access to the main branch.

---

## The four repositories

A release of canvodpy touches four repositories. This page is the one
checklist for all of them.

| Repository | What a release changes there |
|---|---|
| [canvodpy](https://github.com/TUW-GEO/canvodpy) | versions, changelogs, tags, GitHub release, PyPI, the docs site |
| [canvodpy-test-data](https://github.com/TUW-GEO/canvodpy-test-data) | a release of its own when its `main` has moved past its last tag (version, tag, GitHub release, Zenodo); canvodpy's pointer must be its current, tagged `main` |
| [canvodpy-demo](https://github.com/TUW-GEO/canvodpy-demo) | the canvodpy pins in the notebook headers, after PyPI has the release |
| [canvodpy-extensions](https://github.com/TUW-GEO/canvodpy-extensions) | its own releases, per package, after canvodpy's ([its release guide](https://github.com/TUW-GEO/canvodpy-extensions/blob/main/docs/releasing.md)) |

**Order.** canvodpy first, then the extensions that need it: an extension
is installed from PyPI with the canvodpy release it requires.

The steps fall in three phases. **Before**: everything can still be
changed in an ordinary pull request. **Release**: from the release
commit to PyPI; tags and PyPI uploads are public and stay. **After**: the
other repositories and the docs catch up with the release.

---

## Release types

Each package has its own version ([Versioning](VERSIONING.md)); choose the
increment of each package you release:

| Type | Version Bump | Example | When to use |
|------|-------------|---------|-------------|
| Patch | `1.1.X` | 1.1.0 $\rightarrow$ 1.1.1 | Bug fixes only, fully backwards compatible |
| Minor | `1.X.0` | 1.1.0 $\rightarrow$ 1.2.0 | New features or settings, deprecations, backwards compatible |
| Major | `X.0.0` | 1.4.0 $\rightarrow$ 2.0.0 | Breaking changes (removals, a new store format); requires an upgrade guide ([Upgrading to v1.0.0](guides/upgrading.md) is the one for v1.0.0), linked from the README, the docs landing page, the changelog, and the release notes |

canvodpy is part of every release, and its increment is at least the
largest of the packages released with it.

To test a release first, publish it as a pre-release (`1.0.0a1`,
`1.0.0b1`, `1.0.0rc1`); [Versioning](VERSIONING.md#pre-releases) explains
the stages and when to choose which. The steps below are the same.

The `Development Status` classifier in every `pyproject.toml` follows the
release: `4 - Beta` for a pre-release, `5 - Production/Stable` for a
stable release. The first stable release (`1.0.0`) changed it from
`4 - Beta` to `5 - Production/Stable` in all packages.

---

## Before

Each item is a pull request of its own, merged before the release commit.

- [ ] **Choose the packages and versions.**
      `just release-status` lists, per package, its version, its last
      release tag and the commits since that tag that touched its folder.
      Release a package when its commits matter to its users, at the
      increment they call for.
- [ ] **Test data.** canvodpy's pointer
      (`packages/canvod-readers/tests/test_data`) is the current `main` of
      canvodpy-test-data, and that commit has a tag. When the `main` of
      canvodpy-test-data has moved past its last tag, release the test
      data first:
      1. In canvodpy-test-data, a pull request sets the next version in
         `.zenodo.json` (`"version"`) and `CITATION.cff` (`version`,
         `date-released`): a minor version for changed or added data, a
         patch for metadata only. The concept DOI stays.
      2. After the merge, the user tags the merge commit `vX.Y.Z` and makes
         a GitHub release of it; its notes list what was added and
         changed. Zenodo archives the release as a new version of the
         record; check that the record has the new version.
      3. In canvodpy, a pull request moves the pointer to that commit. It
         may merge before the tag exists; `just release-check` fails
         until the tag is there.
- [ ] **Demo.** canvodpy's pointer (`demo`) is the current `main` of
      canvodpy-demo. Every notebook there pins the last release in its
      script header: `canvodpy==` and every `canvod-*==` at the versions
      canvodpy pinned in that release. The demo's CI installs them from
      PyPI, so the new release can't be pinned yet.
- [ ] **Release notebook** (minor and major releases). A marimo notebook
      that shows what is new and how to use it, next to the changelog:
      `release-notes/vX.Y.Z.py`, made from `release-notes/_template.py`.
    - It pins the release it describes (`"canvodpy==1.1.0"`).
    - One section per change that users notice: what it does, a link to
      its docs page, and the code or command that uses it. A cell runs on
      the demo data (`canvodpy.demo_data()`) where it can; otherwise it
      shows the code and says what it needs.
    - It doesn't have to run from top to bottom; CI checks its format only
      (`just check-release-notes`).
    - It is listed in the table in `release-notes/README.md`.
    - The draft release links it when it is in the tagged commit.
- [ ] **What's new.** [What's new](whats-new.md) describes the release
      and links the release notebook.
- [ ] **Banner** (minor and major releases). The banner on every docs page
      (`overrides/main.html`, block `announce`) names the release and links
      What's new.
- [ ] **Upgrade guide** (major releases), linked as described under
      [Release types](#release-types).
- [ ] **Deprecations** stay in every 1.x release; v2.0.0 removes them.
- [ ] **Checks.** `just check`, `just test` and `just test-network` pass;
      CI passed on `main`.
- [ ] **Release files clean.** The `pyproject.toml` files, `uv.lock`, the
      `CHANGELOG.md` files, `CITATION.cff`, `.zenodo.json` and
      `codemeta.json` have no uncommitted changes; `just release` commits
      only those files.
- [ ] **Maintainer.** `main` requires a pull request, and only
      maintainers can create release tags.

Then, on an up-to-date `main`:

```bash
git switch main
git pull origin main
git submodule update --init demo packages/canvod-readers/tests/test_data
just release-check 1.1.0
```

`just release-check` checks what a machine can check from this list and
writes nothing. It prints one line per check: ✓ passed, ⚠ a warning to
judge, ✗ failed. It exits 1 if any check failed. It checks:

- `HEAD` is `main` on GitHub, and CI passed on it: every check run on
  `HEAD` passed or was skipped, the optional ones too. CI runs
  `just check-release-notes`, so the release notebook's format is checked
  there.
- `just release` would accept the version: it goes up and has no tag yet,
  the branch `release/vX.Y.Z` doesn't exist, the citation files have their
  fields, the ranges between packages admit the versions, and the release
  files are clean.
- The increment is at least what the commits since the last release call
  for: a breaking change (`feat!:` or a `BREAKING CHANGE:` footer) a major,
  a feature or a deprecation a minor. A deprecation is a commit whose
  description starts with "deprecate" (`refactor(config): deprecate ...`);
  commits of the types `docs`, `test`, `ci`, `chore`, `build` and `style`
  change no behavior and never count as one.
- Both submodule pointers are their repository's `main`, and the
  test-data commit has a tag.
- Every demo notebook pins the last release, as above.
- For a minor or major release: the release notebook is on `HEAD`, pins
  the new version, and is linked from `release-notes/README.md` and
  `docs/whats-new.md` on `HEAD`; the docs banner names the release. ⚠ lists the pull requests since the last
  release, merged or squashed on GitHub, with a feature, fix or deprecation among
  their commits that the notebook doesn't name by number (`#123`):
  compare them with the notebook.

It doesn't judge whether the release notebook and What's new describe
every change users notice; that stays your call.

---

## Release

### 1. Create the release commit

```bash
just release canvod-store=1.1.0 canvod-grids=1.0.1 canvodpy=1.1.0
```

This command:

1. Runs all tests (`just test`)
2. Refuses the release, and says why, when canvodpy is missing, a version
   does not go up or is tagged already, canvodpy's increment is smaller
   than a package's, a package's range on another excludes the new
   version (or the current version of a package left out of the release),
   a citation file lacks its version or date field, a release
   file has uncommitted changes, or the branch `release/v1.1.0` exists
   already (locally, or on the remote as of your last `git fetch`)
3. Writes the new versions, canvodpy's `==` pins, a section in each
   released package's `CHANGELOG.md` (from the commits that touched its
   folder; canvodpy's lists the pinned versions), canvodpy's version and
   today's date in `CITATION.cff`, `.zenodo.json` and `codemeta.json`
   (Zenodo takes the version of the archived record from them), and
   `uv.lock`
4. Creates the branch `release/v1.1.0` (canvodpy's version) and commits
   exactly the release files:
   `bump: canvodpy 1.1.0 (canvod-store 1.1.0, canvod-grids 1.0.1)`

It creates no tag: the tags belong on the merged commit on `main` (step 3).

### 2. Review, pull request, merge

```bash
git show --stat     # the version files, uv.lock and CHANGELOG.md files, nothing else
```

The changelog sections are generated from commit subjects; edit them in
the release branch if a line needs it. `main` requires a pull request:

```bash
git push -u origin release/v1.1.0
gh pr create --title "bump: canvodpy 1.1.0 (canvod-store 1.1.0, canvod-grids 1.0.1)" --body "..."
```

Merge the PR once CI passes.

### 3. Tag the merged commit

A merge can give the release a different commit than the one on the
branch, so the tags are created only now, on `main`:

```bash
git switch main
git pull origin main
just tag-release
just push-release-tags
```

`just tag-release` creates an annotated tag for every package version that
has no tag yet; it does not push. `just push-release-tags` pushes the
release tags of the merged commit that GitHub doesn't have yet:

```bash
git push --no-follow-tags origin v1.1.0
git push --no-follow-tags origin canvod-store-v1.1.0 canvod-grids-v1.0.1
```

The canvodpy tag goes on its own, before the package tags. GitHub starts no
workflow for tags when
[more than three tags are pushed at once](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push),
so a canvodpy tag pushed together with the package tags gets no draft
release. The package tags start no workflow, so they can go in one push,
however many there are. `--no-follow-tags` keeps git from adding the other
annotated tags of the commit to the first push (`push.followTags`).

### 4. Publish the draft release

The `.github/workflows/release.yml` workflow detects the canvodpy tag
(`v1.1.0`) and creates a **draft** release whose notes are canvodpy's
`CHANGELOG.md` section, including the package versions, and a link that
opens the release notebook in molab. Package tags get no
GitHub release of their own. Review and publish at
[github.com/TUW-GEO/canvodpy/releases](https://github.com/TUW-GEO/canvodpy/releases).

Publishing the release starts `.github/workflows/deploy_docs.yml`, which
builds and deploys the docs site; Zenodo archives the release.

Pushing the tags does **not** publish to PyPI: tagging and PyPI
publishing are deliberately decoupled (see step 5).

### 5. Publish to PyPI (separate, manual, whenever you decide)

Not automatic. Trigger `publish_pypi.yml` on the canvodpy tag, either from
the
[Actions tab](https://github.com/TUW-GEO/canvodpy/actions/workflows/publish_pypi.yml)
(the Run workflow button; choose the tag) or:

```bash
gh workflow run publish_pypi.yml --ref v1.1.0
```

The run waits for approval: the `pypi` environment requires a reviewer.
Open the run in the Actions tab, choose **Review deployments**, tick
`pypi` and approve.

It first checks the locked dependencies against known vulnerabilities
(`just audit`) and stops if it finds one. Then it builds and uploads exactly
the packages whose release tag points at that
commit (`scripts/release.py tagged`), here canvodpy, canvod-store and
canvod-grids. You can create several releases before ever running this: a
tag existing is not a promise that PyPI has it.

### 6. The extensions

Once PyPI has canvodpy's release, release the extensions that need it,
each package on its own, following
[their release guide](https://github.com/TUW-GEO/canvodpy-extensions/blob/main/docs/releasing.md):
`just release <package> X.Y.Z` on a branch, a pull request, then
`just tag <package>` on `main` and `publish_pypi.yml` on the package's
tag. A minor or major release of an extension has its release notebook
`release-notes/<package>-vX.Y.Z.py` in the release pull request.

---

## After

Once PyPI has the release:

- [ ] **PyPI** shows every released version
      (`https://pypi.org/project/canvodpy/1.1.0/`).
- [ ] **GitHub release** is published and links the release notebook.
- [ ] **Docs site**: `deploy_docs.yml` ran on the published release and
      the site shows the new version (run it by hand from the Actions tab
      if not).
- [ ] **Demo headers**: a pull request in canvodpy-demo sets every
      notebook's script header to the release: `canvodpy==` and each
      `canvod-*==` at the version canvodpy pins. Change only the script
      header; a sentence such as "canvodpy v1.0.0 added ..." stays.
      Update the example in the comment of `.github/workflows/notebooks.yml`
      too. Merge it once the demo's CI passed against PyPI.
- [ ] **Demo pointer**: a pull request in canvodpy moves `demo` to that
      merged commit.
- [ ] **Install line**: the user guide (`docs/users/index.md`) shows the
      release in `uv tool install canvodpy==1.1.0 --with canvod-filemap==A.B.C`;
      users upgrade an installed tool with `uv tool upgrade canvodpy`.
- [ ] **Extensions** take the new versions in their docs and lock
      (their `canvodpy-dependency` guide).
- [ ] **Zenodo**: the record the release created has canvodpy's version
      ([Zenodo Setup](guides/ZENODO_SETUP.md)).
- [ ] **Issues**: watch for regressions.

---

## Troubleshooting

??? failure "Tests fail during release"
    Fix the failing tests on `main` before retrying `just release`.

??? failure "`just release-check` fails"
    Each ✗ line says what to fix. A pointer that is not its repository's
    `main`: move it in a pull request (`git -C demo switch main && git -C
    demo pull`, then commit `demo`). *The demo submodule lacks commit*:
    `git submodule update --init demo`. A demo notebook that pins another
    version: fix its script header in canvodpy-demo, then move the
    pointer. *is not main on GitHub*: `git switch main && git pull`.

??? failure "Not released"
    `just release` names every problem it found; nothing was changed.
    Typical ones:

    - *canvodpy pins every package*: add `canvodpy=X.Y.Z`.
    - *canvod-store makes a minor release, canvodpy only a patch*: raise
      canvodpy's version.
    - *canvod-grids requires canvod-store<2,>=1.0.0, which excludes
      canvod-store 2.0.0*: check canvod-grids against the new major version,
      widen its range in its own pull request, then release both.
    - *canvod-store requires canvod-utils<2,>=1.0.0, which excludes the
      current canvod-utils 0.4.0*: canvod-utils is left out of the release,
      but the new canvod-store needs a newer one. Add `canvod-utils=X.Y.Z`.
    - *Release files have uncommitted changes*: commit them in their own
      pull request, or discard them.
    - *The branch release/v1.1.0 exists already*: a branch of that name is
      left from earlier work (for v1.0.0, the integration branch
      `release/v1.0.0`). Delete it once it is merged, locally and on
      GitHub, then run `just release` again.

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
    [github.com/TUW-GEO/canvodpy/actions](https://github.com/TUW-GEO/canvodpy/actions),
    and that `CHANGELOG.md` has a section `## v1.1.0 (...)`.
    (PyPI publishing never triggers from a tag push at all; see step 5.)
    If no run started, the canvodpy tag was pushed in one push of more
    than three tags (step 3), for example by a `git push` without
    `--no-follow-tags`. Run the workflow by hand on the tag; it makes the
    same draft:

    ```bash
    gh workflow run release.yml -f tag=v1.1.0
    ```

??? failure "Tag is not allowed to deploy due to environment protection rules"
    The `pypi` environment accepts only tags of the form `v*.*.*`, the
    canvodpy tags. Run `publish_pypi.yml` on the canvodpy tag, never on a
    package tag such as `canvod-store-v1.1.0`: it publishes every package
    tagged on that commit.

??? failure "The dependency check finds a vulnerability"
    `just audit` names the package, the vulnerability and the version that
    fixes it. Raise the version in `uv.lock` (`uv lock --upgrade-package
    NAME`) in a pull request, and tag the release on the new commit. If the
    fixed release is less than a week old, `uv lock` doesn't take it yet
    (`exclude-newer` in `pyproject.toml`): add `NAME = false` to
    `exclude-newer-package` in `[tool.uv]` for the fix (and the same for
    any package that release needs in a version as new), and remove it
    once the release is a week old. If no
    fixed version exists and the vulnerability doesn't affect canVODpy, add
    `--ignore-vuln ID` to the `just audit` call of both workflows, with a
    comment saying why, and remove it once a fix is out.

??? failure "A new package fails its first upload"
    A package that is not on PyPI yet needs a pending publisher on PyPI
    (the repository, `publish_pypi.yml` and the `pypi` environment). PyPI
    allows only one pending publisher per repository, workflow and
    environment, so two new packages need two runs: add the first
    package's pending publisher and run the workflow, then the second's
    and run it again. Files already on PyPI are skipped
    (`uv publish --check-url`).
