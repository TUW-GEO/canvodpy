# Contributing

Contributions of all kinds are welcome: bug reports, feature implementations, documentation improvements, and feedback.

---

## Ways to contribute

<div class="grid cards" markdown>

-   :fontawesome-solid-bug: &nbsp; **Report Bugs**

    ---

    Open an issue at [github.com/nfb2021/canvodpy/issues](https://github.com/nfb2021/canvodpy/issues).
    Include your OS, Python version, and steps to reproduce.

-   :fontawesome-solid-wrench: &nbsp; **Fix Bugs**

    ---

    Issues labeled **"bug"** and **"help wanted"** are open for PRs.
    Comment on the issue first so nobody duplicates work.

-   :fontawesome-solid-star: &nbsp; **Implement Features**

    ---

    Issues labeled **"enhancement"** and **"help wanted"** are open.
    Keep scope narrow: one feature per PR.

-   :fontawesome-solid-book: &nbsp; **Improve Documentation**

    ---

    Improvements to docs, docstrings, or external articles are always
    appreciated. See the [Development Guide](guides/DEVELOPMENT.md).

</div>

---

## Required tools

Two tools must be installed before `uv sync` (not managed by it):

=== "macOS"

    ```bash
    brew install uv just
    ```

=== "Linux"

    ```bash
    # uv
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # just
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
        | bash -s -- --to ~/.local/bin
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    winget install Casey.Just
    ```

Verify both are available:

```bash
just check-dev-tools
```

---

## Contribution workflow

```bash
# 1. Fork on GitHub, then clone your fork
git clone git@github.com:YOUR_USERNAME/canvodpy.git
cd canvodpy

# 2. Install dependencies + hooks
git submodule update --init --recursive
uv sync
just hooks
just agent-skills   # if you develop with Claude Code: the shared agent workflow

# 3. Create a feature branch
git checkout -b feature/my-feature

# 4. Make changes
# packages/<pkg>/src/canvod/<pkg>/  ← implementation
# packages/<pkg>/tests/             ← tests

# 5. Verify
just test && just check

# 6. Commit with Conventional Commits
git add packages/<pkg>/src/... packages/<pkg>/tests/...
git commit -m "feat(readers): add RINEX 4.0 support"

# 7. Push + open PR
git push origin feature/my-feature
```

---

## Commit message format

```
<type>(<scope>): <subject>
```

**Types:** `feat` · `fix` · `docs` · `refactor` · `test` · `chore` · `perf` · `ci`

**Scopes:** `readers` · `aux` · `grids` · `vod` · `store` · `viz` · `utils` · `docs` · `ci` · `deps`

```bash
git commit -m "feat(vod): add tau-omega calculator"
git commit -m "fix(readers): handle empty RINEX files"
git commit -m "docs: update installation instructions"
git commit -m "feat(viz)!: redesign 3D plotting API"   # ! = breaking change
```

See [Conventional Commits](https://www.conventionalcommits.org/) for the full specification.

---

## Pre-commit hooks

When you run `just hooks`, Git hooks are installed that execute automatically on every `git commit`. These hooks enforce code quality and commit message standards. **If a hook fails, the commit is rejected**: your files stay staged, but no commit object is created.

### Hooks and what they check

| Hook | Stage | What it does |
|------|-------|-------------|
| **ruff check --fix** | Before commit | Lints Python; auto-fixes where possible (unused imports, style) |
| **ruff format** | Before commit | Formats Python code (indentation, line length, quotes) |
| **uv-lock** | Before commit | Verifies `uv.lock` matches all `pyproject.toml` files |
| **trailing-whitespace** | Before commit | Strips trailing whitespace |
| **check-added-large-files** | Before commit | Blocks files larger than the size threshold |
| **detect-private-key** | Before commit | Prevents accidental commit of SSH/PGP keys |
| **end-of-file-fixer** | Before commit | Ensures files end with exactly one newline |
| **commitizen** | After writing message | Validates `type(scope): subject` format |

### Fixing a rejected commit

=== "ruff auto-fixed your code"

    ruff modifies files in place when it can. After rejection, stage the fixes and retry:

    ```bash
    git add -u
    git commit -m "feat(readers): your original message"
    ```

=== "Commit message rejected by commitizen"

    Your message must follow `type(scope): subject`. Example:

    ```bash
    # Wrong:
    git commit -m "updated the reader"

    # Correct:
    git commit -m "fix(readers): handle empty observation epochs"
    ```

=== "uv-lock out of date"

    ```bash
    uv sync
    git add uv.lock
    git commit -m "feat(readers): your message"
    ```

[:octicons-arrow-right-24: Full hook troubleshooting](guides/contributor-setup.md#14-pre-commit-hooks-and-why-your-commit-may-be-rejected)

---

## Continuous integration and coverage

Every push and pull request triggers automated CI on GitHub Actions:

- **Code Quality**: ruff linting, formatting, ty type-checking, lockfile consistency
- **Test with Coverage**: pytest with coverage measurement, results uploaded to [Coveralls](https://coveralls.io/github/nfb2021/canvodpy), and posted as a PR comment
- **Platform Tests**: test suite across multiple OS and Python versions

The CI runs the **same checks as the pre-commit hooks**, so fixing hook failures locally means your PR passes CI.

---

## Pull request guidelines

!!! tip "Before opening a PR"
    1. `just test && just check` must pass with no errors.
    1. The change follows `CODING_STANDARDS.md` (rules and per-change checklist); the reasons are in the [decisions](adr/index.md).
    2. Include tests for every new feature.
    3. New code must not reduce test coverage. Aim to increase it.
    4. Update the Zensical documentation in `docs/` if adding or changing public API, behavior, or configuration.
    5. Target Python 3.14+.
    6. Add yourself to `CONTRIBUTORS.md` if this is your first contribution.
### Test coverage requirement

Every pull request that adds a feature **must include tests**. The CI
pipeline measures line coverage and posts a report on the PR. While there is no
hard minimum percentage, reviewers check that:

- All new public functions and methods have at least one test
- Edge cases and error paths are covered (empty inputs, invalid parameters)
- Coverage doesn't decrease compared to the base branch

Run `just test-coverage` locally to inspect which lines are covered before pushing.

### Licensing

canVODpy is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
By submitting a pull request, you agree that your contribution is licensed under
the same terms. The `LICENSE` and `NOTICE` files at the repository root apply to
all source files. Per-file license headers aren't required.

---

## Code Quality

```bash
just check          # lint + format + type-check (run before committing)
```

| Tool | Role |
|------|------|
| **ruff** | Linting + formatting |
| **ty** | Type checking |
| **pytest** | Testing with coverage |
| **pre-commit** | Automatic checks on `git commit` |

---

## Deploying (maintainers)

```bash
just release-status                              # commits per package since its last tag
just release canvod-store=1.1.0 canvodpy=1.1.0   # tests, versions, release commit on release/v1.1.0
```

Each package has its own version; the maintainer chooses them, and canvodpy
is part of every release. Then open a pull request for the release branch;
after it's merged, a maintainer runs `just tag-release` on `main`, pushes
the tags and starts the PyPI publish. The full
steps are in `docs/RELEASING.md`.
