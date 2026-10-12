# PyPI publishing setup

This monorepo publishes **8 separate packages** to PyPI:

**Individual packages:**
1. `canvod-readers` - GNSS data readers
2. `canvod-auxiliary` - Auxiliary data handling
3. `canvod-grids` - Grid operations
4. `canvod-store` - Storage backends
5. `canvod-utils` - Utility functions
6. `canvod-viz` - Visualization tools
7. `canvod-vod` - VOD calculation

**Umbrella package:**
8. `canvodpy` - Depends on the 7 packages listed first

**User experience:**
```bash
uv add canvodpy  # Gets all packages automatically
```

<div class="grid cards" markdown>

-   :fontawesome-solid-flask: &nbsp; **Phase 1, TestPyPI** *(Done)*

    ---

    Account created · First manual upload · OIDC trusted publishers configured.
    Beta/alpha releases publish here automatically.

-   :fontawesome-solid-box-open: &nbsp; **Phase 2, real PyPI** *(Active)*

    ---

    Production account · Environment protection · Stable releases only.
    `uv add canvodpy` serves users from here.

</div>

---

## Quick commands

```bash
# Build all packages locally
just build-all

# Manual publish to TestPyPI (requires credentials)
just publish-testpypi

# Manual publish to PyPI (requires credentials)
just publish-pypi

# Automated publish (canvodpy pre-release tag) - triggers publish_testpypi.yml
# for the packages whose release tag points at that commit
just tag-release && git push origin v1.1.0rc1 canvod-store-v1.1.0rc1

# Production publish - started by hand on the canvodpy tag, never by a tag push
gh workflow run publish_pypi.yml --ref v1.1.0
```

---

## Phase 1, TestPyPI setup (completed)

### Step 1. Create a TestPyPI account (done)

Already done. Account created at https://test.pypi.org

### Step 2. Publish once by hand (done)

Already completed with `twine upload --repository testpypi dist/*`

All 8 packages published:
- https://test.pypi.org/project/canvod-readers/
- https://test.pypi.org/project/canvod-auxiliary/
- https://test.pypi.org/project/canvod-grids/
- https://test.pypi.org/project/canvod-store/
- https://test.pypi.org/project/canvod-utils/
- https://test.pypi.org/project/canvod-viz/
- https://test.pypi.org/project/canvod-vod/
- https://test.pypi.org/project/canvodpy/

### Step 3. Set up OIDC publishing (done)

**3.1. Create the GitHub environment**

1. Go to: https://github.com/nfb2021/canvodpy/settings/environments
2. Click "New environment"
3. Name: `testpypi`
4. Save

**3.2. Register trusted publishers (for each of the 8 packages)**

For each package, go to its publishing settings:
- https://test.pypi.org/manage/project/canvod-readers/settings/publishing/
- https://test.pypi.org/manage/project/canvod-auxiliary/settings/publishing/
- https://test.pypi.org/manage/project/canvod-grids/settings/publishing/
- https://test.pypi.org/manage/project/canvod-store/settings/publishing/
- https://test.pypi.org/manage/project/canvod-utils/settings/publishing/
- https://test.pypi.org/manage/project/canvod-viz/settings/publishing/
- https://test.pypi.org/manage/project/canvod-vod/settings/publishing/
- https://test.pypi.org/manage/project/canvodpy/settings/publishing/

On each page:
1. Click "Add a new publisher"
2. Select "GitHub"
3. Fill in:
   - Owner: `nfb2021`
   - Repository: `canvodpy`
   - Workflow: `publish_testpypi.yml`
   - Environment: `testpypi`
4. Click "Add"

**3.3. Test OIDC publishing**

```bash
git tag -a v0.1.0b1 -m "Test OIDC"
git push origin v0.1.0b1
cd /path/to/canvodpy
uv build
```

**Upload manually (first time only):**
```bash
uvx twine upload --repository testpypi dist/*
```

**When prompted:**
```
username: your_testpypi_username
password: your_testpypi_password
```

**Success looks like:**
```
Uploading canvodpy-0.1.0-py3-none-any.whl
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Verify it's there:**
- Go to: https://test.pypi.org/project/canvodpy/

### Step 3. Configure OIDC on TestPyPI

1. **Go to project settings:**
   - https://test.pypi.org/manage/project/canvodpy/settings/publishing/

2. **Scroll to "Publishing"**

3. **Click "Add a new publisher"**

4. **Fill in the form:**
   ```
   PyPI project name:     canvodpy
   Owner:                 nfb2021
   Repository name:       canvodpy
   Workflow name:         publish_testpypi.yml
   Environment name:      test-release
   ```

5. **Click "Add"**

6. **You should see:**
   ```
   ✓ Trusted publisher added

   Publisher:
   - Repository: nfb2021/canvodpy
   - Workflow: publish_testpypi.yml
   - Environment: test-release
   ```

### Step 4. Create the GitHub environment

1. **Go to your repository:**
   - https://github.com/nfb2021/canvodpy

2. **Settings $\rightarrow$ Environments**

3. **New environment:**
   - Name: `test-release`
   - Click "Configure environment"

4. **Add protection rules (optional):**
   - Required reviewers: yourself
   - Wait timer: 0 minutes (it's just testing)

5. **Save**

### Step 5. Create the TestPyPI workflow

Create: `.github/workflows/publish_testpypi.yml`

```yaml
name: Publish to TestPyPI

on:
  release:
    types: [published]

  # Manual trigger for testing
  workflow_dispatch:

permissions:
  id-token: write  # REQUIRED for OIDC
  contents: read

jobs:
  publish-testpypi:
    name: Upload to TestPyPI
    runs-on: ubuntu-latest
    environment: test-release

    # Only run if tag contains 'beta' or 'alpha' (for testing)
    if: contains(github.ref, 'beta') || contains(github.ref, 'alpha')

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.9.27"

      - name: Set up Python
        run: uv python install 3.14

      - name: Build package
        run: uv build

      - name: Publish to TestPyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/
          print-hash: true
```

### Step 6. Test the workflow

**Create a beta release:**
```bash
just release canvodpy=0.1.0b1   # release commit on release/v0.1.0b1: open a PR, merge it
# then, on the merged main:
just tag-release && git push origin v0.1.0b1
```

**Publish the draft release:**
1. Go to: https://github.com/nfb2021/canvodpy/releases
2. Find draft for `v0.1.0b1`
3. Click "Publish release"

**Watch the workflow:**
1. Go to: https://github.com/nfb2021/canvodpy/actions
2. See "Publish to TestPyPI" running
3. Wait ~2-3 minutes
4. Should say "✓ Complete"

**Verify upload:**
- https://test.pypi.org/project/canvodpy/
- Should see version 0.1.0b1

**Test installation:**
```bash
# Install from TestPyPI into a throwaway environment and print the version
# (dependencies come from PyPI)
uv run --isolated --no-project --with canvodpy \
  --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
  python -c "import canvodpy; print(canvodpy.__version__)"
# Should print: 0.1.0b1

# Clean up
deactivate
rm -rf test-env
```

**If it works, you are ready for real PyPI.**

---

## Phase 2, PyPI setup

### Step 7. Create a PyPI account

1. Go to: https://pypi.org/account/register/
2. Fill in details (can use same email as TestPyPI)
3. Verify email
4. **Enable 2FA** (PyPI requires it for trusted publishers!)

### Step 8. Reserve the package name on PyPI

!!! warning "Package names are permanent"
    Once a package is uploaded to PyPI, the name is reserved forever.
    You cannot delete it or reuse its version numbers. Double-check everything before uploading.

```bash
# Build fresh
cd /path/to/canvodpy
rm -rf dist/
uv build

# Upload to REAL PyPI
uvx twine upload dist/*
```

**When prompted:**
```
username: your_pypi_username
password: your_pypi_password
```

**Verify:**
- https://pypi.org/project/canvodpy/

### Step 9. Configure OIDC on PyPI

**Exactly same as TestPyPI:**

1. **Go to:**
   - https://pypi.org/manage/project/canvodpy/settings/publishing/

2. **Add publisher:**
   ```
   PyPI project name:     canvodpy
   Owner:                 nfb2021
   Repository name:       canvodpy
   Workflow name:         publish_pypi.yml
   Environment name:      release
   ```

3. **Click "Add"**

### Step 10. Create the production GitHub environment

!!! tip "Enable 2FA first"
    PyPI requires 2FA to add trusted publishers. Enable it at [pypi.org/manage/account/](https://pypi.org/manage/account/) before proceeding.

1. **Settings $\rightarrow$ Environments $\rightarrow$ New**
2. **Name:** `release`
3. **Protection rules (IMPORTANT!):**
   - Required reviewers: all maintainers
   - Wait timer: 5 minutes (think before publishing)
4. **Save**

### Step 11. Create the production workflow

Create: `.github/workflows/publish_pypi.yml`

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

permissions:
  id-token: write
  contents: read

jobs:
  publish-pypi:
    name: Upload to PyPI
    runs-on: ubuntu-latest
    environment: release

    # Skip beta/alpha releases for production PyPI
    if: "!contains(github.ref, 'beta') && !contains(github.ref, 'alpha')"

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.9.27"

      - name: Set up Python
        run: uv python install 3.14

      - name: Build package
        run: uv build

      - name: Check package
        run: |
          uvx twine check dist/*
          ls -lh dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          print-hash: true
```

### Step 12. First production release

**When ready for v0.1.0:**

```bash
# Create release (all packages at once for the first release)
just release canvodpy=0.1.0 canvod-readers=0.1.0 ...   # open a PR, merge it
# then, on the merged main:
just tag-release && git push origin v0.1.0 canvod-readers-v0.1.0 ...
```

**Publish:**
1. Go to releases
2. Find draft v0.1.0
3. **Review carefully.**
4. Click "Publish release"
5. Start the PyPI workflow: `gh workflow run publish_pypi.yml --ref v0.1.0`
6. Approve the workflow when prompted
7. Wait 5 minutes (your wait timer)
8. The packages tagged at that commit are published to PyPI.

**Verify:**
```bash
uv run --isolated --no-project --with canvodpy \
  python -c "import canvodpy; print(canvodpy.__version__)"
# Should print: 0.1.0
```

**Your package is now on PyPI.**

---

## Summary

=== "Beta / test releases"

    ```bash
    just release canvod-store=1.1.0rc1 canvodpy=1.1.0rc1   # then PR, merge, and on main:
    just tag-release && git push origin v1.1.0rc1 canvod-store-v1.1.0rc1
    # → publishes the tagged packages to TestPyPI automatically
    ```

=== "Stable releases"

    ```bash
    just release canvod-store=1.1.0 canvodpy=1.1.0   # then PR, merge, and on main:
    just tag-release && git push origin v1.1.0 canvod-store-v1.1.0
    gh workflow run publish_pypi.yml --ref v1.1.0
    # → publishes the tagged packages to real PyPI (after environment approval)
    ```

=== "User installation"

    ```bash
    uv add canvodpy          # latest stable
    uv add canvodpy==0.2.0   # specific version
    ```

---

## Good practice

!!! tip "Test on TestPyPI first"
    Use `-beta.X` or `-alpha.X` version suffixes to publish to TestPyPI.
    Verify that the TestPyPI install works (see Test installation)
    before creating a stable release.

!!! warning "Version numbers are permanent"
    PyPI does not allow deleting packages or reusing version numbers.
    Bump the version and re-release if you need to fix a bad upload.

!!! info "Environment protection"
    The `release` environment has required reviewers and a 5-minute wait timer:
    this prevents accidental production releases.

---

## Troubleshooting

??? failure "`Publisher not configured` OIDC error"
    1. Verify environment name in workflow matches the PyPI settings exactly
    2. Verify workflow filename matches exactly
    3. Verify repository owner/name are correct
    4. Confirm 2FA is enabled on your PyPI account

??? failure "`Package already exists`"
    Cannot upload the same version twice. Release the next patch version
    of that package (`just release <package>=X.Y.Z canvodpy=X.Y.Z`).

??? failure "`Build failed`"
    Test locally first:
    ```bash
    uv build
    ls dist/   # should contain .whl and .tar.gz
    uvx twine check dist/*
    ```

??? failure "Environment approval stuck"
    Check the `release` environment's protection rules at
    Settings $\rightarrow$ Environments $\rightarrow$ release. Approve pending deployments manually.

---

## Next steps

- [ ] Test with beta release on TestPyPI
- [ ] First production release v0.1.0
- [ ] Set up Zenodo for DOI ([Zenodo Setup](ZENODO_SETUP.md))
