# Optional Extensions

canvodpy ships as a lean core. Packages that only a subset of users need
(because their receivers use non-standard filenames, or because they run a
specific orchestrator) live in a separate repository so the core install
stays small and dependency-free by default:

**[github.com/TUW-GEO/canvodpy-extensions](https://github.com/TUW-GEO/canvodpy-extensions)**

canvodpy works fully without any of these. `canvod-filemap` is used only
for receivers whose settings name a naming recipe (`recipe:`);
`canvod-airflow` and `canvod-adapters` call canvodpy, not the other way
around.

## Available extensions

| Package | Purpose | Status |
|---|---|---|
| `canvod-filemap` | Recipe-based filename mapping for non-canonical GNSS filenames (proprietary receiver output, legacy RINEX v2 short names, custom layouts) | Available |
| `canvod-airflow` | Airflow DAGs: one daily DAG per configured site, plus backfill; the tasks run the code of `canvodpy run` (`canvodpy.workflows.tasks.check_day`, `process_day`) | Available |
| `canvod-adapters` | Data exchange between canvodpy and other GNSS-T programs (gnssvod): observations and VOD, checked against canvodpy's dataset contracts | Available |

## Installing an extension

Each extension is a package on PyPI, released on its own under the tag
`<package>-v<version>` (for example `canvod-filemap-v1.0.0`). None has
extras: each package brings what it needs.

```bash
uv add canvod-filemap
uv add canvod-airflow
uv add canvod-adapters
```

In a clone of this repository, `canvod-filemap` is the dependency group
`filemap`:

```bash
uv sync --group filemap
```

The group exists only in this repository: it is not part of the `canvodpy`
package on PyPI, so `canvodpy[filemap]` does not exist. Its version range
is in the root `pyproject.toml`:

```toml
[dependency-groups]
filemap = ["canvod-filemap>=1.0.0"]
```

If you have both repositories cloned as sibling directories locally (common
for contributors iterating on `canvod-filemap` itself), you can point the
group at your checkout in your own uncommitted copy to pick up changes
without releasing:

```toml
# pyproject.toml (local override, do not commit)
[tool.uv.sources]
canvod-filemap = { path = "../canvodpy-extensions/packages/canvod-filemap" }
```

!!! warning "Don't commit a local path source"

    A path-based source only works on machines that happen to have
    `canvodpy-extensions` cloned as a sibling directory. `uv` resolves
    every dependency group's sources when it locks, even groups that are
    not installed, so committing a local path breaks `uv sync` for
    everyone else.

See [canvod-filemap's overview](https://extensions.canvodpy.eu/packages/filemap/overview/)
for the recipe format and mapping API,
[canvod-airflow's overview](https://extensions.canvodpy.eu/packages/airflow/overview/)
for DAG structure, deployment, and configuration (`canvod-airflow` depends
on `canvodpy`, not the other way around), and
[canvod-adapters' overview](https://extensions.canvodpy.eu/packages/adapters/overview/)
for the gnssvod conversion, including how merged VOD bands are imported.

## What happens if an extension isn't installed

canvodpy imports `canvod-filemap` only for a receiver whose settings set
`recipe:`. Without a recipe, discovery takes files with canonical canVOD
names only, whether or not the package is installed. A receiver with a
recipe but without `canvod-filemap` installed stops the run with an error
that says how to install it; it never falls back to guessing file names.
See [Configuration $\rightarrow$ Optional: non-canonical
filenames](configuration.md#optional-non-canonical-filenames).
