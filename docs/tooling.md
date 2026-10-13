---
title: Development Tooling
description: Tools used in canVODpy development
---

# Development tooling

canVODpy uses a modern Python toolchain built almost entirely on the [Astral](https://astral.sh/) ecosystem.

<div class="grid cards" markdown>

-   :fontawesome-solid-box: &nbsp; **uv**

    ---

    Replaces pip, venv, pip-tools, and twine in a single binary.
    Manages Python versions, virtual environments, dependency resolution,
    and builds.

    [:octicons-arrow-right-24: astral.sh/uv](https://docs.astral.sh/uv/)

-   :fontawesome-solid-broom: &nbsp; **ruff**

    ---

    Linter + formatter in one tool. Implements 700+ rules from flake8,
    pylint, black, and isort at $10\times$ to $100\times$ their speed.

    [:octicons-arrow-right-24: astral.sh/ruff](https://docs.astral.sh/ruff/)

-   :fontawesome-solid-magnifying-glass-chart: &nbsp; **ty**

    ---

    Type checker replacing mypy. Early development (alpha) but already
    significantly faster for large codebases.

    [:octicons-arrow-right-24: docs.astral.sh/ty](https://docs.astral.sh/ty/)

-   :fontawesome-solid-list-check: &nbsp; **just**

    ---

    Task runner with simpler syntax than Make. All common development
    tasks (test, check, docs, settings) are `just <command>` away.

    [:octicons-arrow-right-24: github.com/casey/just](https://github.com/casey/just)

</div>

---

## Core tools

=== "uv: package manager"

    ```bash
    uv sync                  # Install all dependencies (workspace-aware)
    uv add numpy             # Add a runtime dependency
    uv add --dev pytest      # Add a dev dependency
    uv run pytest            # Run in the managed environment
    uv build                 # Build a wheel
    uv publish               # Publish to PyPI
    ```

    `uv sync` resolves `uv.lock` and creates or updates the shared workspace
    `.venv` at the repo root; all 12 packages share a single environment.

    Configuration in `pyproject.toml`:

    ```toml
    [project]
    dependencies = ["numpy>=2.0", "xarray>=2024.0"]

    [dependency-groups]
    dev = ["pytest>=9.0", "ruff>=0.15", "ty>=0.0.44"]
    ```

=== "uv_build: build backend"

    Builds wheel and sdist with native namespace package support:

    ```toml
    # packages/canvod-readers/pyproject.toml
    [build-system]
    requires      = ["uv_build>=0.13.0,<0.14.0"]
    build-backend = "uv_build"

    [tool.uv.build-backend]
    module-name = "canvod.readers"   # dot → namespace package
    ```

    All 12 workspace packages use `uv_build` as their build backend.

=== "ruff: linter + formatter"

    ```bash
    ruff check .          # Lint
    ruff check . --fix    # Lint with auto-fix
    ruff format .         # Format
    ```

    Configuration (workspace root `pyproject.toml`, inherited by all packages):

    ```toml
    [tool.ruff]
    line-length = 88
    target-version = "py314"

    [tool.ruff.lint]
    select = ["E", "F", "W", "I", "UP", "B", "RUF"]
    ```

    Philosophy: catch real bugs, enforce consistent formatting, don't fight
    scientists over naming or style. Dropped stylistic rules (N, SIM, C4, PIE, PT)
    that add noise without catching bugs.

=== "ty: type checker"

    Type annotations are optional labels on function inputs/outputs; `ty`
    checks that they are consistent, catching a class of bugs before you run
    the code.

    ```bash
    uv run ty check packages/canvod-readers/src/canvod/readers/
    uv run ty check canvodpy/src/canvodpy/
    ```

    Configured at the **workspace root** `pyproject.toml`:

    ```toml
    [tool.ty.environment]
    python-version = "3.14"
    ```

    !!! info "Blocking in canVODpy"
        `ty` runs in the pre-push hook and in CI (the `type_consistency`
        job of `code_quality.yml`). A type error blocks the push and the
        pull request. `[tool.ty.src]` in `pyproject.toml` lists the files
        it leaves out. Run `just check-types` to see the errors.

---

## Supporting tools

=== "just: task runner"

    Recipes are defined in `Justfile` at the repo root. Use `just --list` to
    see all available recipes.

    All common tasks are single commands:

    ```bash
    just test             # Run the full test suite
    just check            # Lint + format + type-check
    just hooks            # Install pre-commit hooks
    just docs             # Preview documentation locally
    just docs-build       # Build static documentation
    just docs-lint        # Check the language of the docs
    just docs-links       # Check every link of the built docs
    just config-init      # Scaffold canvod-settings.yaml from template
    just config-validate  # Validate config files
    just --list           # Show all available commands
    ```

=== "pytest: testing"

    ```bash
    uv run pytest                        # All tests
    uv run pytest --cov=canvod           # With coverage
    uv run pytest -m "not integration"   # Skip integration tests
    uv run pytest packages/canvod-readers/tests/
    ```

    Integration tests are marked `@pytest.mark.integration`. They are **not**
    excluded by default; pass `-m "not integration"` to skip them for a fast
    unit-only run.

=== "pre-commit, Git hooks"

    ```bash
    just hooks    # Install hooks (run once after clone)
    ```

    Configured in `.pre-commit-config.yaml`. ruff and ty use `repo: local`
    so pre-commit uses the same versions as the project:

    ```yaml
    repos:
      - repo: local
        hooks:
          - id: ruff-check
            entry: uv run --locked ruff check --fix
            stages: [pre-commit]
          - id: ruff-format
            entry: uv run --locked ruff format
            stages: [pre-commit]
      - repo: https://github.com/astral-sh/uv-pre-commit
        hooks:
          - id: uv-lock
            stages: [pre-commit]
      - repo: https://github.com/pre-commit/pre-commit-hooks
        hooks:
          - id: trailing-whitespace
          - id: check-added-large-files
          - id: detect-private-key
          - id: end-of-file-fixer
      - repo: https://github.com/commitizen-tools/commitizen
        hooks:
          - id: commitizen
            stages: [commit-msg]
      - repo: local
        hooks:
          - id: ty-check
            entry: uv run --locked ty check
            stages: [pre-push]
    ```

    Ruff, uv-lock, and file hygiene hooks run at the `pre-commit` stage and
    block the commit on failure. Commitizen validates the message at `commit-msg`.
    `ty-check` runs at the **`pre-push` stage** (not on every commit), so type
    errors surface before reaching the remote but without slowing down local commits.
    The tools run with `uv run --locked`: they never rewrite `uv.lock`, and
    fail when it is out of date (run `uv lock`).

=== "Conventional Commits"

    Commits must follow the format `type: short description` where `type` is
    one of `feat`, `fix`, `chore`, `docs`, or `refactor`. commitizen validates
    this at the `commit-msg` git hook stage and blocks non-conforming messages.
    This powers the automated changelog.

    ```
    feat: add Fibonacci grid tessellation       ✅
    fix(store): handle empty metadata table     ✅
    docs(aux): clarify SP3 interpolation        ✅
    added new grid                              ❌  (no type prefix)
    ```

    Monorepo scopes (optional but encouraged): `readers`, `aux`, `grids`, `vod`,
    `store`, `viz`, `utils`, `naming`, `orchestrator`, `diagnostics`, `ops`,
    `ci`, `docs`, `deps`.

=== "Zensical + beautiful-mermaid"

    Documentation is built with [Zensical](https://zensical.org/), a
    Rust+Python wrapper around MkDocs Material:

    ```bash
    just docs          # Preview locally (wraps uv run zensical serve --open)
    just docs-build    # Build static site (wraps uv run zensical build)
    ```

    Two checks keep the pages correct:

    - `just docs-lint` checks the language with
      [Vale](https://vale.sh/) and its Google style package (`.vale.ini`).
      Project words that are spelled correctly go in
      `.vale/styles/config/vocabularies/canvodpy/accept.txt`. Pass a path
      to check a single page: `just docs-lint docs/users/index.md`.
    - `just docs-links` builds the site and checks every link with
      [lychee](https://lychee.cli.rs/) (`lychee.toml`): links between
      pages, anchors, and links to other sites. Install lychee once with
      `brew install lychee`.

    Write diagrams as Mermaid code blocks inside the page; the browser
    renders them. `docs/diagrams/` holds only files that a page embeds.

---

## Tool comparison

| Task | Traditional stack | canVODpy |
|------|------------------|----------|
| Package management | pip | uv |
| Virtual environments | venv / virtualenv | uv (built-in) |
| Linting | flake8 + pylint | ruff |
| Formatting | black + isort | ruff |
| Type checking | mypy | ty |
| Building | setuptools | uv_build |
| Publishing | twine | uv |
| Task runner | make / tox | just |
| Documentation | Sphinx | Zensical (MkDocs) |

---

## Quality & security

canVODpy follows FAIR software principles and OpenSSF best practices:

<div class="grid cards" markdown>

-   :fontawesome-solid-shield-halved: &nbsp; **OpenSSF Best Practices**

    ---

    Certified compliance with open source security best practices.

    [:octicons-arrow-right-24: badge guide](OPENSSF_BADGE_GUIDE.md)

-   :fontawesome-solid-star: &nbsp; **FAIR Software**

    ---

    Compliance with the 5 FAIR software recommendations (findable,
    accessible, interoperable, reusable). Automated howfairis workflow
    runs on every push.

    [:octicons-arrow-right-24: Implementation Summary](FAIR_IMPLEMENTATION_SUMMARY.md)

-   :fontawesome-solid-chart-line: &nbsp; **OpenSSF Scorecard**

    ---

    Automated security monitoring across 18+ best practice checks.

    **Runs:** weekly and on every push to main
    **Results:** the GitHub Security tab

    [:octicons-arrow-right-24: View Scorecard](https://securityscorecards.dev/viewer/?uri=github.com/nfb2021/canvodpy)

-   :fontawesome-solid-lock: &nbsp; **Security Policy**

    ---

    Vulnerability reporting process with defined response timelines.
    Private reporting via GitHub Security Advisories.

    [:octicons-arrow-right-24: Security Policy](SECURITY.md)

</div>

### Continuous integration

All quality checks run automatically:

| Workflow | Runs On | Purpose |
|----------|---------|---------|
| `test_platforms.yml` | Push, PR | Multi-platform tests (Linux/macOS on Apple silicon/Windows) |
| `test_coverage.yml` | Push, PR | Coverage tracking $\rightarrow$ Coveralls |
| `code_quality.yml` | Push | Linting, formatting, type checking |
| `codeql.yml` | Push, PR, Weekly | CodeQL security analysis |
| `fair-software.yml` | Push, PR | FAIR compliance checks |
| `scorecard.yml` | Weekly, Push to main | Security best practices |

All workflows must pass before merging to `main`.

**See also:** [security policy](SECURITY.md) · [FAIR compliance](FAIR_IMPLEMENTATION_SUMMARY.md)
