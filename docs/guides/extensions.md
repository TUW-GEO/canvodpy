# Optional Extensions

canvodpy ships as a lean core. Packages that only a subset of users need
(because their receivers use non-standard filenames, or because they run a
specific orchestrator) live in a separate repository so the core install
stays small and dependency-free by default:

**[github.com/nfb2021/canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions)**

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

Extensions are released on GitHub only, each package under its own tag
`<package>-v<version>` (for example `canvod-filemap-v1.0.0`), never on PyPI.

!!! note "Before the 1.0.0 releases"
    The commands below use the 1.0.0 tags. Until those releases exist, this
    repository pins canvod-filemap to a commit of the extensions' `main`
    (`rev = ...` in `[tool.uv.sources]`) and `uv sync --group filemap`
    installs that commit.

In a clone of this repository, `canvod-filemap` is the dependency group
`filemap`. The root `pyproject.toml` points it at a release tag of the
public repository, so

```bash
uv sync --group filemap
```

installs that release on any machine, no sibling checkout required. The
group exists only in this repository: it is not part of the `canvodpy`
package on PyPI, so `canvodpy[filemap]` does not exist.
Elsewhere, install the package from its tag:

```bash
uv add "canvod-filemap @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-filemap-v1.0.0#subdirectory=packages/canvod-filemap"
```

The group is pinned in the root `pyproject.toml`: the version range in
`[dependency-groups]`, the tag in `[tool.uv.sources]`:

```toml
[dependency-groups]
filemap = ["canvod-filemap>=1.0.0"]

[tool.uv.sources]
canvod-filemap = { git = "https://github.com/nfb2021/canvodpy-extensions.git", subdirectory = "packages/canvod-filemap", tag = "canvod-filemap-v1.0.0" }
```

If you have both repositories cloned as sibling directories locally (common
for contributors iterating on `canvod-filemap` itself), you can override the
source in your own uncommitted local checkout to pick up changes without
reinstalling:

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
    Keep the git source in version control; only override it locally.

See [canvod-filemap's overview](https://extensions.canvodpy.eu/packages/filemap/overview/)
for the recipe format and mapping API.

`canvod-airflow` is installed directly (it depends on `canvodpy`, not the
other way around):

```bash
uv add "canvod-airflow[airflow] @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-airflow-v1.0.0#subdirectory=packages/canvod-airflow"
```

See [canvod-airflow's overview](https://extensions.canvodpy.eu/packages/airflow/overview/)
for DAG structure, deployment, and configuration.

`canvod-adapters` is installed directly wherever you exchange data with
another program:

```bash
uv add "canvod-adapters[store] @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-adapters-v1.0.0#subdirectory=packages/canvod-adapters"
```

See [canvod-adapters's overview](https://extensions.canvodpy.eu/packages/adapters/overview/)
for the gnssvod conversion, including how merged VOD bands are imported.

## What happens if an extension isn't installed

canvodpy imports `canvod-filemap` only for a receiver whose settings set
`recipe:`. Without a recipe, discovery takes files with canonical canVOD
names only, whether or not the package is installed. A receiver with a
recipe but without `canvod-filemap` installed stops the run with an error
that says how to install it; it never falls back to guessing file names.
See [Configuration $\rightarrow$ Optional: non-canonical
filenames](configuration.md#optional-non-canonical-filenames).
