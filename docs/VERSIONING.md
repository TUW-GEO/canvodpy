# Versioning Strategy

canVODpy uses **unified semantic versioning** across all packages in the monorepo — one version number covers all twelve packages, released together.

!!! info "Planned: a version per package"
    Each package will get its own version, so that a package used on its own
    (e.g. canvod-readers) changes its version only when its code changes. A
    `canvodpy` version will then name the exact version of every package it
    installs. Until then, all packages share one version.

---

## Why Unified Versioning?

<div class="grid cards" markdown>

-   :fontawesome-solid-microscope: &nbsp; **Scientific Reproducibility**

    ---

    A single version number enables unambiguous citation in papers.
    `pip install canvodpy==0.2.0` recreates a known-compatible environment.
    Supports FAIR principles for scientific software.

-   :fontawesome-solid-layer-group: &nbsp; **Sollbruchstellen**

    ---

    Independent during development; coherent at release time.
    Develop and test packages independently, release them together with one tag.

</div>

---

## Semantic Versioning

Following [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH
```

| Increment | Trigger | Example |
|-----------|---------|---------|
| `MAJOR` | Breaking API changes | 0.9.0 → 1.0.0 |
| `MINOR` | New features, backwards compatible | 0.1.0 → 0.2.0 |
| `PATCH` | Bug fixes, backwards compatible | 0.1.0 → 0.1.1 |

Pre-release identifiers: `0.2.0-alpha.1` · `0.2.0-beta.1` · `0.2.0-rc.1`

---

## Creating Releases

```bash
just release 0.2.0    # minor release
just release 0.1.1    # patch release
just release 1.0.0    # major release
```

`just release` runs the tests, bumps the version of all packages and
writes `CHANGELOG.md` and `uv.lock` (`just bump`), and commits exactly
those files on a new branch `release/vX.Y.Z`. It creates no tag: a
maintainer tags the merged commit on `main` ([Releasing](RELEASING.md)).

`just bump` alone changes the files only, by version or by bump type:

```bash
just bump minor       # 0.1.0 → 0.2.0
just bump patch       # 0.1.0 → 0.1.1
just bump major       # 0.1.0 → 1.0.0
```

---

## Version Files

commitizen keeps every `pyproject.toml` in sync. For each package it updates
the package's own `version` and its requirements on other canVODpy packages:

```toml
[tool.commitizen]
version = "0.4.0"
version_files = [
    "canvodpy/pyproject.toml:version",
    "canvodpy/pyproject.toml:\"canvod-[a-z-]+[=>]=",
    "packages/canvod-readers/pyproject.toml:version",
    "packages/canvod-readers/pyproject.toml:\"canvod-[a-z-]+[=>]=",
    # ... the same two lines for every package
]
```

- `canvodpy` requires each package at exactly the version released with it
  (`canvod-store==0.4.0`), so `pip install canvodpy==0.4.0` always installs
  the mix of packages that was tested together.
- A package requires the other canVODpy packages at least at its own version
  (`canvod-config>=0.4.0`), so it never runs with an older package that lacks
  code it uses.
- `__version__` of each package is read from the installed package
  (`importlib.metadata`), never written into the code.

Git tags follow `vMAJOR.MINOR.PATCH` — e.g. `v0.1.0`, `v1.0.0`, `v0.2.0-beta.1`.

---

## Deprecation Policy

1. **Version N** — Feature deprecated with `DeprecationWarning`
2. **Version N+1** — Louder warning, migration guide in docs
3. **Version N+2** — Feature removed, MAJOR version bump

---

## Citation

```bibtex
@software{canvodpy2026,
  author  = {Bader, Nicolas and Contributors},
  title   = {canvodpy: GNSS Vegetation Optical Depth Analysis},
  version = {0.2.0},
  year    = {2026},
  url     = {https://github.com/nfb2021/canvodpy},
  doi     = {10.5281/zenodo.XXXXXXX}
}
```

> "Analysis was performed using canvodpy v0.2.0 (Bader et al., 2026)."

---

[:octicons-arrow-right-24: Release Process](RELEASING.md) &nbsp;&nbsp; [:octicons-arrow-right-24: Conventional Commits](https://www.conventionalcommits.org/)
