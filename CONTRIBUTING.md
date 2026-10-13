# Contributing

Contributions are welcome. This guide covers the development setup and contribution workflow.

## Required Tools

Two external tools must be installed separately (not managed by `uv sync`):

### uv (Python Package Manager)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via package manager
brew install uv
```

The repository needs uv 0.13 (`required-version` in `pyproject.toml`), so
every machine writes `uv.lock` the same way. Install a 0.13 release if uv
refuses to start.

[uv documentation](https://docs.astral.sh/uv/)

### just (Command Runner)

```bash
# macOS/Linux
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash

# Or via package manager
brew install just
```

[just documentation](https://github.com/casey/just)

## Types of Contributions

### Report Bugs

Report bugs at https://github.com/nfb2021/canvodpy/issues. Include operating system, local setup details, and steps to reproduce.

### Fix Bugs

Issues tagged "bug" and "help wanted" are open for contributions.

### Implement Features

Issues tagged "enhancement" and "help wanted" are open for contributions.

### Write Documentation

Improvements to documentation, docstrings, or external articles are appreciated.

### Submit Feedback

File feature proposals at https://github.com/nfb2021/canvodpy/issues. Keep the scope narrow and explain the intended behavior.

## Development Workflow

1. Install required tools (uv and just).

2. Fork and clone the repository:
   ```bash
   git clone git@github.com:your_name_here/canvodpy.git
   cd canvodpy
   ```

3. Verify tools and install dependencies:
   ```bash
   just check-dev-tools
   uv sync
   just hooks
   just agent-skills   # if you develop with Claude Code: the shared agent workflow
   ```

4. Create a feature branch:
   ```bash
   git checkout -b name-of-your-bugfix-or-feature
   ```

5. Make changes and verify:
   ```bash
   just test
   just check
   ```

6. Commit using conventional commits:
   ```bash
   git commit -m "feat(readers): add support for RINEX 4.0 format"
   ```

7. Push and create a pull request:
   ```bash
   git push origin name-of-your-bugfix-or-feature
   ```

### Commit Message Format

```
<type>(<scope>): <subject>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`

**Scopes:** `readers`, `aux`, `grids`, `vod`, `store`, `viz`, `utils`, `docs`, `ci`, `deps`

**Examples:**
```bash
git commit -m "feat(vod): add tau-omega calculator"
git commit -m "fix(readers): handle empty RINEX files"
git commit -m "docs: update installation instructions"
git commit -m "feat(viz)!: redesign 3D plotting API"  # Breaking change
```

See [Conventional Commits](https://www.conventionalcommits.org/) for the full specification.

## Common Commands

```bash
just --list                    # Show all commands
just test                      # Run all tests
just test-coverage             # With coverage report
just test-package canvod-grids # Specific package
just check                     # Lint + format + type-check
just docs                      # Preview documentation
just docs-lint                 # Language check of the docs (Vale)
just docs-lint-changed         # Vale on the pages changed since origin/main
just docs-links                # Link check of the built docs (lychee)
```

## Pull Request Guidelines

1. Include tests for new functionality: new code must not reduce test coverage.
2. Update the Zensical documentation in `docs/` with every change of behavior (new logic, new code, changed code), public API, or configuration. A pull request without docs to match is declined. The changed pages must pass Vale (`just docs-lint-changed`) and the built site the link check (`just docs-links`); CI runs both.
3. Ensure compatibility with Python 3.14+.
4. Add yourself to `CONTRIBUTORS.md` if this is your first contribution.

## Licensing

canVODpy is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
By submitting a pull request, you agree that your contribution is licensed under
the same terms. The `LICENSE` and `NOTICE` files at the repository root apply to
all source files. Per-file license headers are not required.

## Code Quality

- **ruff** for linting and formatting
- **ty** for type checking
- **pytest** for testing with coverage

Run `just check` before committing. Every change follows `CODING_STANDARDS.md`
(rules and per-change checklist); the reasons are in `docs/adr/`.

## Deploying

For maintainers:

```bash
just release-status                              # commits per package since its last tag
just release canvod-store=1.1.0 canvodpy=1.1.0   # tests, versions, release commit on release/v1.1.0
```

Each package has its own version; the maintainer chooses them, and canvodpy
is part of every release. Then open a pull request for the release branch;
after it is merged, a maintainer runs `just tag-release` on `main`, pushes
the tags and starts the PyPI publish. The full
steps are in `docs/RELEASING.md`.
