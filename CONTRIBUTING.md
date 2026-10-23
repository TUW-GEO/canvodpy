# Contributing

Contributions of all kinds are welcome: bug reports, bug fixes, features,
documentation, and feedback. This guide covers the development setup and the
contribution workflow. A step-by-step setup for a new machine is in the
[contributor setup guide](https://canvodpy.eu/guides/contributor-setup/).

## Ways to contribute

- **Report bugs** at https://github.com/TUW-GEO/canvodpy/issues. Include your
  operating system, Python version, and the steps to reproduce.
- **Fix bugs:** issues labeled "bug" and "help wanted" are open for pull
  requests. Comment on the issue first so nobody duplicates work.
- **Implement features:** issues labeled "enhancement" and "help wanted" are
  open. Keep the scope narrow: one feature per pull request.
- **Improve documentation:** docs, docstrings, or external articles. See the
  [development guide](https://canvodpy.eu/guides/DEVELOPMENT/).
- **Submit feedback:** file feature proposals at
  https://github.com/TUW-GEO/canvodpy/issues. Keep the scope narrow and
  explain the intended behavior.

## Required tools

Two tools must be installed before `uv sync`, which doesn't manage them:
the [uv](https://docs.astral.sh/uv/) package manager and the
[just](https://github.com/casey/just) command runner.

```bash
# macOS
brew install uv just

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
    | bash -s -- --to ~/.local/bin
```

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install Casey.Just
```

The repository needs uv 0.13 (`required-version` in `pyproject.toml`), so
every machine writes `uv.lock` the same way. Install a 0.13 release if uv
refuses to start.

## Contribution workflow

```bash
# 1. Fork on GitHub, then clone your fork
git clone git@github.com:YOUR_USERNAME/canvodpy.git
cd canvodpy

# 2. Check the tools, install dependencies and hooks
just check-dev-tools
git submodule update --init --recursive
uv sync
just hooks
just agent-skills   # if you develop with Claude Code: the shared agent workflow

# 3. Create a feature branch
git checkout -b feature/my-feature

# 4. Make changes
# packages/<pkg>/src/canvod/<pkg>/   implementation
# packages/<pkg>/tests/              tests

# 5. Verify
just test && just check

# 6. Commit with Conventional Commits
git add packages/<pkg>/src/... packages/<pkg>/tests/...
git commit -m "feat(readers): add RINEX 4.0 support"

# 7. Push and open a pull request
git push origin feature/my-feature
```

## Commit message format

```
<type>(<scope>): <subject>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`

**Scopes:** `readers`, `aux`, `grids`, `vod`, `store`, `viz`, `utils`, `docs`, `ci`, `deps`

```bash
git commit -m "feat(vod): add tau-omega calculator"
git commit -m "fix(readers): handle empty RINEX files"
git commit -m "docs: update installation instructions"
git commit -m "feat(viz)!: redesign 3D plotting API"   # ! = breaking change
```

See [Conventional Commits](https://www.conventionalcommits.org/) for the full
specification.

## Git hooks

`just hooks` installs Git hooks that run on their own. **If a hook before the
commit fails, the commit is rejected:** your files stay staged, but no commit
is created.

| Hook | When | What it does |
|------|------|--------------|
| **ruff check --fix** | Before commit | Lints Python; fixes what it can (unused imports, style) |
| **ruff format** | Before commit | Formats Python code |
| **uv-lock** | Before commit | Checks that `uv.lock` matches all `pyproject.toml` files |
| **trailing-whitespace** | Before commit | Strips trailing whitespace |
| **check-added-large-files** | Before commit | Blocks files larger than the size limit |
| **detect-private-key** | Before commit | Blocks committed SSH/PGP keys |
| **end-of-file-fixer** | Before commit | Ends files with exactly one newline |
| **check-agent-docs** | Before commit | Checks that paths and `just` recipes named in `AGENTS.md` files and skills exist |
| **commitizen** | After writing the message | Checks the `type(scope): subject` format |
| **ty-check** | Before push | Type-checks the code with ty |
| **code-graph** | After commit, merge, checkout | Updates the code graph in the background |

When a commit is rejected:

- **ruff fixed your code:** it changed the files in place. Stage the fixes
  and commit again: `git add -u`, then the same `git commit`.
- **commitizen rejected the message:** write it as `type(scope): subject`,
  for example `fix(readers): handle empty observation epochs`.
- **uv-lock is out of date:** run `uv sync`, `git add uv.lock`, and commit
  again.

More cases are in the
[hook troubleshooting](https://canvodpy.eu/guides/contributor-setup/#14-pre-commit-hooks-and-why-your-commit-may-be-rejected).

## Common commands

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

## Continuous integration

Every push and pull request runs these checks on GitHub Actions:

- **Python Code Quality:** checks that `uv.lock` is up to date and runs ruff
  (lint and format) and ty (types). It also builds and imports every package
  with only its declared dependencies and checks the paths named in
  `AGENTS.md` files and skills.
- **Test with coverage:** pytest with coverage, uploaded to
  [Coveralls](https://coveralls.io/github/TUW-GEO/canvodpy) and posted as a
  comment on the pull request.
- **Platform Tests:** the test suite on Linux, Windows, and macOS.
- **Docs Quality:** a language check (Vale) of the changed pages and root
  files, and a link check (lychee) of the built site.

## Pull request guidelines

1. `just test && just check` pass with no errors.
2. The change follows `CODING_STANDARDS.md` (rules and per-change
   checklist); the reasons are in `docs/adr/`.
3. Include tests for every new feature: every new public function and method
   has at least one test, edge cases and error paths (empty inputs, invalid
   parameters) are covered, and coverage doesn't decrease. Run
   `just test-coverage` to see which lines are covered.
4. Update the Zensical documentation in `docs/` with every change of behavior
   (new logic, new code, changed code), public API, or configuration. A pull
   request without docs to match is declined. The changed pages must pass
   Vale (`just docs-lint-changed`) and the built site the link check
   (`just docs-links`); CI runs both.
5. Target Python 3.14.
6. Add yourself to `CONTRIBUTORS.md` if this is your first contribution.

## Licensing

canVODpy is licensed under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). By
submitting a pull request, you agree that your contribution is licensed under
the same terms. The `LICENSE` and `NOTICE` files at the repository root apply
to all source files. Per-file license headers aren't required.

## Releasing (maintainers)

```bash
just release-status                              # commits per package since its last tag
just release canvod-store=1.1.0 canvodpy=1.1.0   # tests, versions, release commit on release/v1.1.0
```

Each package has its own version; the maintainer chooses them, and canvodpy
is part of every release. Then open a pull request for the release branch;
after it's merged, a maintainer runs `just tag-release` on `main`, pushes
the tags, and starts the PyPI publish. The full steps are in the
[release process](https://canvodpy.eu/RELEASING/).
