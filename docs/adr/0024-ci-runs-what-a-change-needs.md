# CI runs what a change needs

*Proposed 2026-11-07 (#632).*

Every pull request ran the full CI, whatever it changed: a fix to one
docs page ran the tests on Linux, macOS, and Windows, the type check,
and the package build. A path filter on each workflow can't fix this alone:
`main` requires its checks by name, and a workflow that a path filter
skips reports nothing, so the pull request can't be merged.

**One summary check gates `main`.** One CI workflow
(`.github/workflows/ci.yml`) calls the workflows that gate a pull
request. Its last job, `ci-ok`, waits for all the others and fails when
any of them failed or was cancelled. A job skipped by its condition
counts as passed. `main` requires `ci-ok` only, so adding, renaming or
skipping a job never needs a change to the branch rules.

**Only a docs-only pull request skips anything, and the list of docs is
fail-safe.** A pull request skips the expensive jobs only when every
file it changes is on the docs list (`scripts/ci_changes.py`): the docs
pages, Markdown files anywhere, the release notebooks, the docs site
configuration, and the Vale configuration. Any other file, a new kind of
file included, runs everything. A gap in the list costs time, never a
skipped test. The changed files are counted against the merge base, so
merging `main` into a branch adds none.

**A pull request runs the S3 tests only when it changes store code.**
The S3 tests start an S3 emulator and test the stores on S3: the store
packages, the store commands of the command line, and the S3 tests
themselves turn them on, and so do the lock file, the workflows, and the
script that classifies the changes. This is a list of code paths, not a
fail-safe list: code outside it that breaks the stores on S3 is caught
on `main`.

**Every push to `main` and every run started by hand runs everything.**
A pull request classified wrongly is caught on `main` at the latest.

## Considered options

- **A path filter on each workflow.** A skipped workflow reports no
  check, and the required checks wait forever.
- **A list of code paths that need the tests.** A new folder or file
  type not on the list would skip the tests without anyone noticing.
- **A third-party action that reads the changed files.** One more
  action with read access to the repository; the few lines of a script
  in this repository are tested with the rest of the code.
- **A merge queue.** The rule that a branch is up to date with `main`
  before it merges already tests each pull request against the newest
  `main`.

## Consequences

- A docs-only pull request still runs the lock file check, lint, format,
  the agent docs check, and the docs checks.
- A test (`canvodpy/tests/test_ci_workflow.py`) fails when a job of the
  CI workflow is missing from `ci-ok`, so `ci-ok` can't silently stop
  protecting `main`.
- A branch without a pull request runs no CI.
