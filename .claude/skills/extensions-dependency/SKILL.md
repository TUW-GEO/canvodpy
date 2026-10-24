---
name: extensions-dependency
description: Change how canvodpy takes canvod-filemap from canvodpy-extensions (PyPI version range, dependency group, relock), or change canvodpy API the extensions use. Use when touching the filemap group or public API they import.
---

# canvodpy and canvodpy-extensions

The two repositories depend on each other, in both directions:

- canvodpy installs **canvod-filemap** from PyPI, as a workspace
  dependency group: `uv sync --group filemap`. It is not an extra.
  canvodpy depends on no extension; the group only lets developers and CI
  test the two together.
- The extensions import canvodpy from PyPI: canvod-preflight's convention,
  the readers' contracts, `canvodpy.workflows.tasks` (canvod-airflow).

## Where it is set

Root `pyproject.toml`, `[dependency-groups]`:
`filemap = ["canvod-filemap>=1.0.0"]`. There is no source for it: it comes
from PyPI. canvod-filemap's own dependencies on canvod-preflight and
canvod-utils resolve to this workspace's packages, so the lock holds one
of each.

## Take a new canvod-filemap release

1. After the release is on PyPI, raise the lower bound in the `filemap`
   group if canvodpy needs the new release.
2. `uv lock --upgrade-package canvod-filemap` and `uv sync --group filemap`.
3. Check: `just test-package canvodpy` (discovery uses canvod-filemap)
   and `just check-agent-docs` (paths written `extensions:<path>` are
   checked at the locked release tag, `canvod-filemap-v<version>`).

To test unreleased canvod-filemap code, point the group at a local
checkout in an uncommitted copy (`docs/guides/extensions.md`); never
commit a git or path source.

## Changing canvodpy API the extensions use

Search the extensions first (`git -C <extensions checkout> grep -n <name>`).
A rename here breaks them once they relock against a new canvodpy release.
Keep the old name working with the `deprecate` guide, and note the change
for the extensions. Their side of this is their `canvodpy-dependency`
guide (in their repository).
