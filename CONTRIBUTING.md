# Contributing

Contributions of all kinds are welcome: bug reports, bug fixes, features,
documentation, and feedback. This guide covers the development setup and the
contribution workflow. A step-by-step setup for a new machine is in the
[contributor setup guide](https://canvodpy.eu/guides/contributor-setup/).

## Ways to contribute

- **Report bugs** at https://github.com/TUW-GEO/canvodpy/issues with the
  bug report form. It asks for the steps to reproduce, the error output, and
  the output of `canvodpy doctor`.
- **Fix bugs:** issues labeled "bug" and "help wanted" are open for pull
  requests. Comment on the issue first so nobody duplicates work.
- **Implement features:** issues labeled "enhancement" and "help wanted" are
  open. Keep the scope narrow: one feature per pull request.
- **Improve documentation:** docs, docstrings, or external articles. See the
  [development guide](https://canvodpy.eu/guides/DEVELOPMENT/).
- **Submit feedback:** file feature proposals at
  https://github.com/TUW-GEO/canvodpy/issues with the feature request form.
  Keep the scope narrow and explain the intended behavior.

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

**Scopes**, for example: `readers`, `aux`, `config`, `grids`, `vod`, `store`,
`viz`, `utils`, `naming`, `orchestrator`, `diagnostics`, `ops`, `ci`, `docs`,
`deps` (the list in `[tool.commitizen.customize]` of `pyproject.toml`)

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
just reference-check           # Compare with the reference stores (needs the test data)
```

## Continuous integration

Every pull request and every push to `main` runs one workflow on GitHub
Actions, **CI**, which sums up its checks in one check, `ci-ok`. A pull
request that changes only docs skips the type check, the package build,
the package-import check and the platform tests; one that changes no
store code skips the S3 tests
(ADR 0024, `docs/adr/0024-ci-runs-what-a-change-needs.md`). CI runs:

- **Python Code Quality:** checks that `uv.lock` is up to date and runs ruff
  (lint and format) and ty (types). It also builds and imports every package
  with only its declared dependencies and checks the paths named in
  `AGENTS.md` files and skills.
- **Platform Tests:** the test suite on Linux, Windows, and macOS. The Linux
  job measures the coverage, uploads it to
  [Coveralls](https://coveralls.io/github/TUW-GEO/canvodpy) and posts it as a
  comment on the pull request.
- **S3 Tests:** the tests of stores on S3, against an S3 emulator.
- **Docs Quality:** a language check (Vale) of the changed pages and root
  files, and a link check (lychee) of the built site.
- **Reference stores:** on a change of the package sources or `uv.lock`,
  builds the GNSS and VOD stores of every setting profile from the test
  data and compares them with the published reference stores
  (`just reference-check`, Linux only). A difference fails the job and
  uploads the report, `reference-check.txt`, as the artifact
  `reference-check-report`. If your change alters a result on purpose,
  say why in the pull request, attach the report, and change the
  reference stores as
  [Reference stores](https://canvodpy.eu/guides/reference-stores/#changing-the-reference-stores)
  describes; the job fails until the new stores are published and
  pinned. Otherwise the difference is a bug: run `just reference-check`
  locally to fix it.

### Fuzzing

A second workflow, **Fuzzing** (`.github/workflows/fuzz.yml`), feeds random
input to the readers and the file name parser with
[atheris](https://github.com/google/atheris). It fails on any exception
the code doesn't document for bad input, on a hang and on a memory
blow-up. It runs weekly for 10 minutes per target and opens an issue for a
crash, and for 1 minute per target on a pull request that changes a
reader, the file name parser or the fuzzing setup. It is not part of
`ci-ok`. Every input that once found a bug is kept in `fuzz/crashes/`,
and the tests replay it on every pull request. To fuzz locally (Linux
x86_64 only):

```bash
uv sync --group fuzz
just fuzz sbf 600    # target: rinex3, rinex2, nav, nmea, sbf or filename
```

A crash lands in `.fuzz/`. After the fix, copy the input to
`fuzz/crashes/<target>/` under a name that says what it holds.

## Pull request guidelines

A new pull request starts from the template in
`.github/pull_request_template.md`: summary, evidence, merge danger, and a
checklist of the points below.

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
