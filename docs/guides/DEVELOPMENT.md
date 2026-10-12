# Development guide

Quick reference for day-to-day canVODpy development.

---

## Initial setup

```bash
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy
git submodule update --init --recursive   # test data + demo data
uv sync                                    # install all packages (editable)
just hooks                                 # install pre-commit hooks
just test                                  # verify everything works
```

!!! info "Submodules"
    Two data repositories are pulled as submodules:

    - **`packages/canvod-readers/tests/test_data`**: falsified/corrupted RINEX files for validation tests
    - **`demo`**: clean real-world data for demos and documentation

    Tests that depend on these datasets are automatically skipped if submodules are not initialized.

---

## Prerequisites

Two tools must be installed outside `uv`:

| Tool | Install | Purpose |
|------|---------|---------|
| **uv** | `brew install uv` | Python + dependency management |
| **just** | `brew install just` | Task runner |

```bash
just check-dev-tools   # verify both are present
```

[:octicons-arrow-right-24: Full installation guide](contributor-setup.md)

---

## Configuration management

canVODpy uses three YAML files in `config/`:

| Section | Purpose |
|---------|---------|
| `processing:` | Processing parameters, NASA Earthdata credentials, storage strategies, Icechunk settings |
| `sites:` | Research sites, receiver definitions, data root paths, VOD analysis pairs |
| `sids:` | Signal ID filtering: `all`, a named `preset`, or a `custom` list |

All three sections live in a single `config/canvod-settings.yaml`. Template: `config/canvod-settings.yaml.example`, a copy of the template the package ships (`packages/canvod-config/src/canvod/config/templates/`); edit that one and copy it.

=== "First-time setup"

    ```bash
    canvodpy config init                # scaffold canvod-settings.yaml from template
    # edit config/canvod-settings.yaml (or: canvodpy config init --interactive)
    canvodpy config validate            # check for errors
    canvodpy config show                # print resolved config
    ```

=== "Daily use"

    ```bash
    just config-validate    # after editing
    just config-show        # inspect current values
    canvodpy doctor         # environment + config diagnostics when something's off
    ```

---

## Testing

```bash
just test                            # all tests
just test-package canvod-readers     # specific package
just test-coverage                   # with HTML coverage report
```

Tests live in `packages/<pkg>/tests/`. Integration tests are marked
`@pytest.mark.integration` and excluded from the default run.

---

## Code Quality

```bash
just check          # lint + format + type-check (run before committing)
just check-lint     # ruff linting only
just check-format   # ruff formatting only
```

| Tool | Purpose |
|------|---------|
| **ruff** | Linting + formatting (replaces flake8, black, isort) |
| **ty** | Type checking (replaces mypy) |
| **pytest** | Testing with coverage |

### Type checking (ty)

`ty check` must pass with zero diagnostics. It blocks `git push` (local
pre-push hook) and runs again in CI (`type_consistency` job). There's no
budget or ratchet; if you introduce a diagnostic, fix it before pushing.

Most real diagnostics mean the annotation is actually wrong: fix the
annotation, not the checker. Suppress with a targeted comment only when the
code is correct and a limitation of ty is the real issue (for example, a runtime-built
`enum.StrEnum`, a deliberately dynamic attribute set on a function object, a
third-party stub that's too strict for a legitimately partial dict):

```python
_excepthook._logger_holder = logger_holder  # ty: ignore[unresolved-attribute]
```

Always include the specific rule name in brackets (`uv run ty check` prints
it in the diagnostic, for example `error[invalid-return-type]`). A bare `# type:
ignore` (mypy syntax) does not suppress ty diagnostics, since ty matches on
its own rule codes.

---

## Logging: add it generously

canvodpy runs unattended on remote machines. When something goes wrong
there, whatever you logged is the *only* evidence there is:
there's no attaching a debugger to a cron job after the fact. Log more than
feels necessary, especially around: file I/O, external calls (downloads,
Icechunk writes), anything with a fallback/degraded path, and any place a
silent skip could hide data loss. See `docs/guides/diagnostics.md` for the
full picture (the log files, `run_id`, the failure events, `stage_timer`,
the performance dashboard). This section is the short version: how to add a log
line.

**Which logger to use:** every module, in every package, gets its logger
directly from structlog:

```python
import structlog

log = structlog.get_logger(__name__)
```

Only canvodpy configures
logging; the canvod-* packages never do. `configure_logging()` installs
structlog's processor chain *globally*, so **any** `structlog.get_logger()`
call anywhere in the process, regardless of which package it's in,
automatically gets routed through the two-track logging setup (human/agent
files) with `run_id` injected, with zero per-call-site wiring. Never
reach for `print()` or the standard library `logging` directly.

**Event style:** first positional argument is a short `snake_case` event name,
everything else is a structured keyword, not string interpolation:

```python
# Good
log.info("rinex_preprocessing_started", file=str(rnx_file.name), site=site_name)
log.warning("sids_dropped_no_ephemeris", count=len(dropped), sids=sorted(dropped))

# Avoid: loses structure, can't be grepped/filtered on a field
log.info(f"Started preprocessing {rnx_file.name} for {site_name}")
```

**Timing:** use `stage_timer()`/`timed_stage()` from `canvod.utils.logging`
rather than hand-rolling `t0 = time.perf_counter(); ...; duration = ...`:
it emits the canonical `stage_timing` event the performance dashboard
reads, and still emits (with `status="error"`) if the block raises.

```python
from canvod.utils.logging import stage_timer

with stage_timer("icechunk.write", group=group_name, size_mb=size_mb):
    to_icechunk(dataset, session, group=group_name)
```

When one block has several sequential checkpoints, each a dashboard stage
of its own, measure them yourself and emit each with
`record_stage_timing(stage, seconds, ...)` (see `_preprocess_file` in
`processor.py`). Checkpoints that are not dashboard stages belong in one
specific, well-named event with their own rich context (see
`_preprocess_aux_data_with_hermite` in `processor.py`), which is more useful
than forcing everything through one generic name.

Only the main process adds stages to the `run_summary`; stages timed in a
worker process reach the log and the dashboard only.

---

## Keeping your fork in sync

If you are working from a fork (rather than a direct clone), periodically pull updates from the upstream repository:

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main

# Then update your feature branch:
git checkout feature/my-feature
git rebase main
```

If `upstream` is not configured, add it once:

```bash
git remote add upstream git@github.com:nfb2021/canvodpy.git
```

[:octicons-arrow-right-24: Detailed fork sync guide](contributor-setup.md#12-keeping-your-fork-up-to-date)

---

## Pre-commit hooks

`just hooks` installs Git hooks that run **automatically on every commit**. If any hook fails, the commit is rejected: your changes stay staged but no commit is created.

### What runs

| Hook | Stage | Effect |
|------|-------|--------|
| **ruff check --fix** | `pre-commit` | Lints and auto-fixes Python code |
| **ruff format** | `pre-commit` | Formats Python code |
| **uv-lock** | `pre-commit` | Verifies `uv.lock` matches `pyproject.toml` |
| **trailing-whitespace** | `pre-commit` | Strips trailing whitespace |
| **check-added-large-files** | `pre-commit` | Blocks large files from being committed |
| **detect-private-key** | `pre-commit` | Prevents accidental secret commits |
| **end-of-file-fixer** | `pre-commit` | Ensures files end with one newline |
| **commitizen** | `commit-msg` | Validates Conventional Commits format |

### When your commit is rejected

```bash
# Most common: ruff auto-fixed your code. Stage the fixes and retry:
git add -u && git commit -m "feat(readers): your message"

# If commitizen rejects your message, use the correct format:
git commit -m "type(scope): description"
# types: feat, fix, docs, refactor, test, chore, perf, ci
# scopes: readers, aux, grids, vod, store, viz, utils, naming, ops, docs, ci, deps

# If uv-lock is out of date:
uv sync && git add uv.lock && git commit -m "feat(readers): your message"
```

[:octicons-arrow-right-24: Full troubleshooting guide](contributor-setup.md#14-pre-commit-hooks-and-why-your-commit-may-be-rejected)

---

## Contributing workflow

```bash
git checkout -b feature/my-feature
# … make changes in packages/<pkg>/src/ …
# … add tests in packages/<pkg>/tests/ …
just check && just test
git add packages/<pkg>/src/... packages/<pkg>/tests/...
git commit -m "feat(readers): add RINEX 4.0 support"
git push origin feature/my-feature
# → open pull request on GitHub
```

### Conventional commit scopes

`readers` · `aux` · `grids` · `vod` · `store` · `viz` · `utils` · `naming` · `ops` · `docs` · `ci` · `deps`

---

## Continuous Integration

Every push and PR triggers GitHub Actions workflows:

| Workflow | Checks |
|----------|--------|
| **Code Quality** | ruff lint, ruff format, ty type-check, lockfile consistency |
| **Test with Coverage** | pytest $\rightarrow$ coverage.lcov $\rightarrow$ [Coveralls](https://coveralls.io/github/nfb2021/canvodpy) |
| **Platform Tests** | Multi-OS, multi-Python-version test matrix |

Coverage reports are posted as PR comments and tracked on Coveralls over time. To run coverage locally:

```bash
just test-coverage    # generates HTML report
```

---

## Private or local add-on packages

You may want to develop an add-on package alongside canVODpy that is not part
of the public repository, for example a private algorithm, a site-specific
extension, or an experimental module you are not yet ready to publish.

The recommended pattern keeps the public workspace and lock file clean while
letting you use the package locally without friction.

### The pattern

**1. Place the package inside `packages/`**

```
packages/
  canvod-myprivatepackage/
    pyproject.toml
    src/
      canvod/myprivatepackage/
```

**2. Add it to `.gitignore`** (so it is never accidentally committed)

```
packages/canvod-myprivatepackage
```

**3. Exclude it from the uv workspace** in the root `pyproject.toml`

```toml
[tool.uv.workspace]
members  = ["packages/*", "canvodpy"]
exclude  = ["packages/canvod-myprivatepackage"]
```

This keeps `uv.lock` identical for everyone else.
CI never sees the directory, so it resolves the same 240 packages with or
without your local copy.

**4. Install locally with `uv pip install`**

```bash
uv pip install -e packages/canvod-myprivatepackage/
```

`uv pip install` installs directly into the virtual environment. It does **not** modify
`pyproject.toml` or `uv.lock`.
After a fresh `uv sync`, re-run the command to restore your local install.

### Upgrade path

When the package is ready to become public:

1. Remove it from `.gitignore` and from the `exclude` list.
2. Commit the package directory.
3. Run `uv lock` and commit the updated `uv.lock`.

It becomes a first-class workspace member and appears in the lock for everyone.

### Why not git submodules?

You could also host the private package in its own repository and add it as a
git submodule. `actions/checkout@v4` does not initialize submodules by
default, so CI would still see an empty directory. The trade-off is that the
`uv.lock` would diverge between users who have initialized the submodule and
those who have not, requiring everyone to keep the `exclude` in place anyway.
For a single-developer private add-on the simpler approach is preferred.

---

## All just commands

```bash
just                     # list all commands
just check               # lint + format + type-check
just test                # run all tests
just sync                # install/update dependencies
just clean               # remove build artifacts
just hooks               # install pre-commit hooks
canvodpy config init     # scaffold canvod-settings.yaml from template
just config-init-interactive  # scaffold canvod-settings.yaml via guided wizard
just config-validate     # validate configuration
just config-show         # view resolved configuration
just doctor              # environment + config diagnostics
just store-list          # list every site's gnss/vod stores + status
just store-info SITE     # branches/groups/stats for one site's store
just store-log SITE      # commit history graph for one site's store
just docs                # preview documentation (opens the browser)
just docs-lint           # language check of the docs (Vale, Google style)
just docs-links          # link check of the built docs (lychee)
just build-all           # build all packages
just deps-report         # dependency metrics report
just deps-mermaid        # mermaid dependency graph
```

---

## Troubleshooting

??? failure "`No module named 'canvod.X'`"
    Run `uv sync` to install/reinstall packages in editable mode.

??? failure "`Command not found: just`"
    Install just: `brew install just` (macOS) or see [contributor-setup](contributor-setup.md).

??? failure "Tests fail after dependency changes"
    ```bash
    uv sync --all-extras
    ```

??? failure "`uv.lock` needs to be updated; CI fails but local works"
    An untracked directory inside `packages/` is being picked up by the
    `packages/*` workspace glob and included in the lock. CI does not have
    the directory and therefore resolves fewer packages, causing a mismatch.

    Identify the culprit:

    ```bash
    git ls-tree HEAD packages/   # shows only committed packages
    ls packages/                 # shows all local packages (including untracked)
    ```

    Any directory present locally but absent from the `git ls-tree` output is
    the source of the divergence. Follow the
    [Private or Local Add-on Packages](#private-or-local-add-on-packages)
    pattern to exclude it and regenerate the lock.
