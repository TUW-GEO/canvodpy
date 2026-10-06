# How the Release Infrastructure Works

This page documents the complete release automation chain — from commit message to PyPI upload.

<div class="grid cards" markdown>

-   :fontawesome-solid-comment: &nbsp; **Conventional Commits**

    ---

    Structured commit messages that machines can parse.
    `feat`, `fix`, `docs` determine version bumps automatically.

    [:octicons-arrow-right-24: Details](#1-conventional-commits-system)

-   :fontawesome-solid-scroll: &nbsp; **Changelog Generator**

    ---

    `commitizen` writes the new section of `CHANGELOG.md` from the
    commit history on every version bump; `git-changelog` writes the
    release notes of the GitHub Release.

    [:octicons-arrow-right-24: Details](#2-git-changelog-generator)

-   :fontawesome-solid-tag: &nbsp; **Version Management**

    ---

    `commitizen` bumps `version` in all `pyproject.toml` files at once;
    `just release` commits them on a release branch. A maintainer tags
    the merged commit.

    [:octicons-arrow-right-24: Details](#3-version-management-with-commitizen)

-   :fontawesome-brands-github: &nbsp; **GitHub Releases**

    ---

    A workflow detects new tags, creates a draft release from
    the CHANGELOG, and waits for maintainer approval.

    [:octicons-arrow-right-24: Details](#4-github-releases-automation)

-   :fontawesome-solid-box-open: &nbsp; **PyPI Publishing**

    ---

    Two workflows: `publish_testpypi.yml` (runs on alpha, beta and rc
    tags) and `publish_pypi.yml` (started by hand, never by a tag).

    [:octicons-arrow-right-24: Details](#5-pypi-publishing-setup)

-   :fontawesome-solid-lock: &nbsp; **OIDC Authentication**

    ---

    Short-lived JWT tokens from GitHub — no stored API keys.
    Each workflow run gets a unique 10-minute proof-of-identity.

    [:octicons-arrow-right-24: Details](#6-trusted-publishing-with-oidc)

</div>

---

---

## 1. Conventional Commits System

### What It Is

A specification for writing commit messages with a structured format that machines can parse.

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

### How It Works in canvodpy

**Step 1: Developer writes a commit**
```bash
git add packages/canvod-readers/
git commit -m "feat(readers): add RINEX 4.0 support"
```

**Step 2: Pre-commit hook intercepts**
- File: `.git/hooks/commit-msg` (installed by `just hooks`)
- Runs: `commitizen check` on the message
- Validates format matches conventional commits

**Step 3: Hook validates or rejects**

**Valid commit - allowed:**
```
feat(readers): add RINEX 4.0 support
fix(vod): correct tau calculation
docs: update installation guide
```

**Invalid commit - rejected:**
```
Added new feature
WIP
fixed bug
```

**Configuration Files:**

1. **`pyproject.toml`** - Commitizen config
   ```toml
   [tool.commitizen]
   name = "cz_conventional_commits"
   version = "0.1.0"

   [tool.commitizen.customize]
   scopes = [
       "readers", "aux", "grids", "vod",
       "store", "viz", "utils",
   ]
   ```

2. **`.pre-commit-config.yaml`** - Hook registration
   ```yaml
   - repo: https://github.com/commitizen-tools/commitizen
     rev: v4.13.3
     hooks:
       - id: commitizen
         stages: [commit-msg]
   ```

### Why It Matters

- **Automated changelog:** Tools can parse commits to generate CHANGELOG.md
- **Semantic versioning:** Type determines version bump (feat=minor, fix=patch)
- **Clear history:** Easy to see what changed without reading code
- **Community standard:** Expected in 2026 for open-source projects

---

## 2. Git Changelog Generator

### What It Is

A tool ([git-changelog](https://pawamoy.github.io/git-changelog/)) that reads your git history and generates a beautiful CHANGELOG.md file.

### How It Works

**Input: Git Commits**
```bash
git log --oneline
abc1234 feat(vod): add tau-omega calculator
def5678 fix(readers): handle empty files
ghi9012 docs: update API reference
```

**Processing:**
1. Read all commits since last tag (or all commits)
2. Parse conventional commit format
3. Group by type (Features, Bug Fixes, Docs)
4. Extract issue numbers and link to GitHub
5. Generate markdown sections

**Output: CHANGELOG.md**
```markdown
## [0.2.0] - 2026-02-04

### Features
- **vod:** add tau-omega calculator ([abc1234](link))

### Bug Fixes
- **readers:** handle empty files ([def5678](link))

### Documentation
- update API reference ([ghi9012](link))
```

### Configuration: `.git-changelog.toml`

```toml
[changelog]
convention = "angular"  # Use Angular/conventional commits style

sections = [
    { name = "Features", types = ["feat"], order = 1 },
    { name = "Bug Fixes", types = ["fix"], order = 2 },
    { name = "Performance", types = ["perf"], order = 3 },
]

template = "keepachangelog"  # Use Keep a Changelog format
provider = "github"
repository = "nfb2021/canvodpy"
```

### Usage

**Manual generation:**
```bash
just changelog        # Generate for current version
just changelog v0.2.0 # Generate for specific version
```

**What happens:**
1. Runs: `uvx git-changelog -Tio CHANGELOG.md -B="v0.2.0" -c angular`
2. Reads commits from git history
3. Parses with Angular convention
4. Inserts at `<!-- insertion marker -->` in CHANGELOG.md
5. Preserves existing content

### The Magic

- **No manual updates:** CHANGELOG writes itself from commits!
- **Links everywhere:** Auto-links to GitHub commits, issues, PRs
- **Consistent format:** Always follows Keep a Changelog style
- **Version tracking:** Each release gets its own section

---

## 3. Version Management with Commitizen

### What It Is

Commitizen can **bump versions** across multiple files in a coordinated way.

### How It Works for Monorepo

**Configuration: `pyproject.toml`**
```toml
[tool.commitizen]
version = "0.1.0"  # Current version

# All files to update when bumping
version_files = [
    "canvodpy/pyproject.toml:version",
    "packages/canvod-readers/pyproject.toml:version",
    "packages/canvod-auxiliary/pyproject.toml:version",
    # ... every package
]

tag_format = "v$version"  # Creates tags like v0.2.0
```

### The Bump Process

**Command:**
```bash
just bump 0.2.0
```

**What happens:**

1. **Read current version** from `pyproject.toml` (`[tool.commitizen]`)
2. **Calculate new version**: `0.2.0`, or `minor`, `patch`, `major`
3. **Update all version_files**: `version` and the pins between the
   packages in every `pyproject.toml` (`cz bump --files-only`)
4. **Write the new section of `CHANGELOG.md`** from the commits since the
   last tag
5. **Update uv.lock** (`uv lock`)

`just bump` makes no commit and no tag. `just release 0.2.0` runs the
tests, calls `just bump`, and commits exactly these files on the new
branch `release/v0.2.0`. The tag is created after the pull request is
merged, on `main` ([Releasing](../RELEASING.md)).

### Why Unified Versioning

**Problem without it:**
- canvod-readers: 1.2.0
- canvod-vod: 0.5.3
- canvod-store: 2.1.0
- User installs... which versions work together?

**Solution with unified versioning:**
- All packages: 0.2.0
- User installs canvodpy 0.2.0
- All components guaranteed compatible

---

## 4. GitHub Releases Automation

### What It Is

A GitHub Actions workflow that automatically creates releases when you push version tags.

### The Workflow: `.github/workflows/release.yml`

**Trigger:**
```yaml
on:
  push:
    tags:
      - "v*.*.*"  # Matches v0.1.0, v1.0.0, etc.
```

**Steps:**

1. **Detect tag push**
   - A maintainer runs: `git push origin v0.2.0` (on the merged `main`)
   - GitHub sees: new tag `v0.2.0`
   - Workflow starts

2. **Checkout code with history**
   ```yaml
   - uses: actions/checkout@v6
     with:
       fetch-depth: 0  # Need full history for changelog
   ```

3. **Install tools**
   ```yaml
   - uses: astral-sh/setup-uv@v7
   - run: uv python install 3.14
   ```

4. **Generate release notes**
   ```yaml
   - run: uvx git-changelog --release-notes > release-notes.md
   ```

   Extracts commits for THIS release only (since last tag)

5. **Create GitHub release**
   ```yaml
   - run: |
       gh release create v0.2.0 \
         --title "canvodpy v0.2.0" \
         --notes-file release-notes.md \
         --draft \
         --verify-tag
   ```

   Creates a **draft** (not published yet!)

### The Complete Flow

```
Developer                    GitHub Actions                 GitHub
    |                               |                          |
    | just release 0.2.0, PR, merge |                         |
    |----------------------------->|                          |
    |                               |                          |
    | git push origin v0.2.0       |                          |
    |------------------------------------------------------------>
    |                               |                          |
    |                               | Detect v0.2.0 tag        |
    |                               |<-------------------------|
    |                               |                          |
    |                               | Checkout code            |
    |                               | Generate release notes   |
    |                               | Create draft release     |
    |                               |------------------------->|
    |                               |                          |
    | Review draft release          |                          |
    |<----------------------------------------------------------
    |                               |                          |
    | Click "Publish Release"       |                          |
    |---------------------------------------------------------->|
    |                               |                          |
```

### Why Draft Releases?

- **Safety:** Review before making public
- **Flexibility:** Add migration notes, binaries, etc.
- **Control:** You decide when to announce

---

## 5. PyPI Publishing Setup

### PyPI

**PyPI** (Python Package Index) is where Python packages live.

- Users install: `pip install canvodpy`
- Searches: https://pypi.org/project/canvodpy/
- Hosts: Wheels (.whl) and source distributions (.tar.gz)

**TestPyPI** is the sandbox for testing before real PyPI.

### Setup Process

#### Step 1: Register Account

**TestPyPI (do this first!):**
1. Go to: https://test.pypi.org/account/register/
2. Create account with your email
3. Verify email

**Real PyPI (after testing):**
1. Go to: https://pypi.org/account/register/
2. Create account (can use same email)
3. Verify email

#### Step 2: Reserve Package Name

**On TestPyPI:**
1. Build package locally:
   ```bash
   uv build
   ```
   Creates: `dist/canvodpy-0.1.0-py3-none-any.whl`

2. Upload manually (first time only):
   ```bash
   uvx twine upload --repository testpypi dist/*
   ```

3. Enter credentials when prompted
4. Package name now reserved!

**On real PyPI:**
- Same process, but omit `--repository testpypi`
- **CAUTION:** Package names are permanent!

#### Step 3: Verify Manual Upload

```bash
# Install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ canvodpy

# Test it works
python -c "import canvodpy; print(canvodpy.__version__)"
```

---

## 6. Trusted Publishing with OIDC

### OIDC

**OIDC** (OpenID Connect) provides authentication without passwords or API tokens.

**Old way (API tokens):**
```
GitHub Actions → API Token → PyPI
Token in GitHub Secrets (can leak)
Token expires
Manual rotation needed
```

**New way (Trusted Publishing with OIDC):**
```
GitHub Actions → OIDC JWT → PyPI
No tokens to store
Never expires
Cryptographically secure
GitHub identity proves it's really you
```

### How OIDC Works (Simplified)

1. **GitHub Actions runs your workflow**
   - Workflow has identity: `repo: nfb2021/canvodpy`
   - GitHub issues a JWT (JSON Web Token)

2. **Workflow requests upload to PyPI**
   - Sends JWT instead of password/token
   - JWT says: "I'm an official GitHub Actions run from nfb2021/canvodpy"

3. **PyPI verifies JWT**
   - Checks signature (is it really from GitHub?)
   - Checks claims (is it the right repo?)
   - Allows upload

### Setup Process (Detailed)

#### Part A: Configure on PyPI

1. **Go to your project on PyPI:**
   - https://test.pypi.org/manage/project/canvodpy/settings/publishing/
   - (or real PyPI after testing)

2. **Click "Add a new publisher"**

3. **Fill in the form:**
   ```
   PyPI Project Name:     canvodpy
   Owner:                 nfb2021
   Repository name:       canvodpy
   Workflow name:         publish_pypi.yml
   Environment name:      pypi
   ```

4. **Click "Add"**

5. PyPI now trusts GitHub Actions from that repo/workflow.

#### Part B: Create GitHub Workflow

Create: `.github/workflows/publish_pypi.yml`

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]  # Trigger when you publish a release

permissions:
  id-token: write  # REQUIRED for OIDC
  contents: read

jobs:
  publish:
    name: Upload to PyPI
    runs-on: ubuntu-latest
    environment: release  # MUST match PyPI config!

    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7

      - name: Build package
        run: uv build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          # NO PASSWORD OR TOKEN NEEDED!
          # OIDC handles authentication
```

#### Part C: Create GitHub Environment

1. **Go to your GitHub repo:**
   - Settings → Environments → New environment

2. **Name it:** `pypi` (must match the workflow's `environment`)

3. **Add protection rules (optional but recommended):**
   - Required reviewers: Add yourself
   - Wait timer: 5 minutes (think before publishing)

4. **Save**

### The Complete Publishing Flow

```
1. Maintainer creates the release
   ├─> just release 0.2.0   (commit on release/v0.2.0)
   ├─> pull request, merged into main
   ├─> git tag -a v0.2.0 on main, git push origin v0.2.0
   └─> GitHub Actions creates draft release

2. Maintainer publishes the release on GitHub
   └─> Click "Publish Release" button

3. Maintainer starts the publish workflow
   ├─> gh workflow run publish_pypi.yml --ref v0.2.0 -f version=0.2.0
   ├─> GitHub generates OIDC JWT
   ├─> Workflow builds package
   └─> Sends package + JWT to PyPI

4. PyPI verifies and publishes
   ├─> Verifies JWT is from nfb2021/canvodpy
   ├─> Accepts upload
   └─> Package now live!

5. Users can install
   └─> pip install canvodpy==0.2.0
```

### Security Benefits

**Traditional API Tokens:**
- Must be stored in GitHub Secrets
- Can be leaked if workflow compromised
- Have broad permissions
- Need manual rotation

**OIDC Trusted Publishing:**
- No secrets to store
- JWT valid for ~10 minutes only
- Scoped to specific repo + workflow
- Automatic, no maintenance

### Testing with TestPyPI

**Why test first?**
- Real PyPI uploads are **permanent** (can't delete!)
- Package names are reserved forever
- Better to catch mistakes on TestPyPI

**Setup for TestPyPI:**

1. **Configure on TestPyPI:**
   - https://test.pypi.org/manage/project/canvodpy/settings/publishing/
   - Add publisher (same form as above)

2. **Modify workflow for testing:**
   ```yaml
   - name: Publish to TestPyPI
     uses: pypa/gh-action-pypi-publish@release/v1
     with:
       repository-url: https://test.pypi.org/legacy/
   ```

3. **Test the whole flow:**
   ```bash
   # Create test release: release commit, pull request, merge, then on main
   just release 0.1.0-beta.1
   git tag -a v0.1.0-beta.1 -m "Release v0.1.0-beta.1"
   git push origin v0.1.0-beta.1   # pre-release tags publish to TestPyPI

   # Publish draft release
   # Workflow uploads to TestPyPI

   # Verify
   pip install --index-url https://test.pypi.org/simple/ canvodpy
   ```

---

## Complete End-to-End Example

### Scenario: You're creating version 0.2.0

**Step 1: Development**

Changes reach `main` through pull requests, each with conventional
commits (`feat(readers): add RINEX 4.0 support`).

**Step 2: Prepare the release**
```bash
git switch main && git pull origin main
just release 0.2.0
# tests, version bump, CHANGELOG.md, uv.lock;
# commit "bump: version 0.1.0 → 0.2.0" on release/v0.2.0
```

**Step 3: Pull request**
```bash
git push -u origin release/v0.2.0
gh pr create --title "bump: version 0.1.0 → 0.2.0" --body "..."
# merge once CI passes
```

**Step 4: Tag the merged commit (maintainer)**
```bash
git switch main && git pull origin main
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

**Step 5: GitHub Actions (automatic)**
```
→ release.yml workflow triggers
→ Generates release notes
→ Creates draft release on GitHub
```

**Step 6: Review & Publish**
```
→ Go to: https://github.com/nfb2021/canvodpy/releases
→ Review the draft release v0.2.0, click "Publish Release"
```

**Step 7: PyPI (manual)**
```bash
gh workflow run publish_pypi.yml --ref v0.2.0 -f version=0.2.0
```

**Step 8: Users Install**
```bash
pip install canvodpy==0.2.0
```

---

## Troubleshooting

### Conventional Commits Hook Failing

**Error:** `[ERROR] Commit message does not follow conventional commits format`

**Fix:**
```bash
# Check format
git log -1 --oneline

# Should be: type(scope): description
# Bad:  "fixed the bug"
# Good: "fix(vod): correct tau calculation"

# Amend if needed
git commit --amend -m "fix(vod): correct tau calculation"
```

### Changelog Not Updating

**Problem:** Running `just changelog` but CHANGELOG.md unchanged

**Causes & Fixes:**
1. No conventional commits: Write proper commit messages
2. No `<!-- insertion marker -->` in CHANGELOG.md: Add it
3. Wrong version range: Check with `git tag -l`

### OIDC Upload Failing

**Error:** `Error: The workflow is not configured for publishing`

**Fix:**
1. Check environment name matches: `pypi`
2. Verify PyPI publisher settings (repo, workflow name)
3. Ensure workflow has `id-token: write` permission

### Version Bump Not Working

**Error:** `cz bump` fails

**Causes:**
1. Release files already changed: `just release` refuses; commit or
   discard the changes to `pyproject.toml`, `uv.lock` or `CHANGELOG.md`
2. No conventional commits: Can't determine bump type
3. Version format wrong: Must be `0.2.0` not `v0.2.0`

---

## Summary

You now have a **production-grade release system**:

1. **Conventional commits** enforce standard format
2. **Commitizen** manages unified versioning and writes CHANGELOG.md
3. **Git-changelog** writes the release notes
4. **GitHub Actions** automates releases
5. **OIDC** enables secure PyPI publishing

**Result:** one command prepares the release commit; a pull request, a
tag on `main` and a manual PyPI publish complete it.

```bash
just release 0.2.0
```
