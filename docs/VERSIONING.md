# Versioning strategy

Each canVODpy package has its own version
([ADR 0010](adr/0010-per-package-versions.md)). A package used on its own
(for example canvod-readers) changes its version only when its code changes. The
umbrella package `canvodpy` pins every package to an exact version, so a
canvodpy version names exactly the mix of packages it installs.

---

## Why a version per package, and one umbrella?

<div class="grid cards" markdown>

-   :fontawesome-solid-cubes: &nbsp; **Reusable packages**

    ---

    A tool that needs only canvod-readers depends on canvod-readers, and
    its version says what changed in the readers, not elsewhere.

-   :fontawesome-solid-microscope: &nbsp; **Scientific reproducibility**

    ---

    `uv add canvodpy==1.1.0` installs exactly the mix of packages that
    was tested together, so one version is enough to cite in a paper.

</div>

---

## Semantic versioning

Following [Semantic Versioning 2.0.0](https://semver.org/), for each
package on its own:

| Increment | Trigger | Example |
|-----------|---------|---------|
| `MAJOR` | Breaking API changes | 1.4.2 $\rightarrow$ 2.0.0 |
| `MINOR` | New features, backwards compatible | 1.1.0 $\rightarrow$ 1.2.0 |
| `PATCH` | Bug fixes, backwards compatible | 1.1.0 $\rightarrow$ 1.1.1 |

Versions are written as Python writes them
([PEP 440](https://peps.python.org/pep-0440/)).

canvodpy's increment is at least the largest increment of the packages
released with it: a minor release of canvod-store comes with at least a
minor release of canvodpy.

---

## Pre-releases

Before a final version, a package can be released as a test version. PEP 440
defines three kinds, marked by a suffix, and sorts them before the final
version:

`1.0.0a1` $<$ `1.0.0b1` $<$ `1.0.0rc1` $<$ `1.0.0`

| Stage | Suffix | What it says | Choose it when |
|-------|--------|--------------|----------------|
| Alpha | `a` | Incomplete | Planned features are still missing |
| Beta | `b` | Nearly complete, may still change | The planned features are in, but behavior or interfaces can still change before the final version |
| Release candidate | `rc` | The final version, unless a bug turns up | Only fixes remain |
| Final | none | Released | A release candidate needed no further fix |

- Each stage counts from 1 (`1.0.0b1`, `1.0.0b2`, …), and the next stage
  starts again at 1 (`1.0.0b2`, then `1.0.0rc1`). A stage may be skipped.
- A pre-release of canvodpy pins pre-releases of the packages it releases,
  with the same suffix: canvodpy `1.0.0b1` pins canvod-store `1.0.0b1`.
- uv and pip skip pre-releases unless asked for one: by its exact version
  (`uv add canvodpy==1.0.0b1`), or with `--prerelease allow` (uv) or
  `--pre` (pip). canvodpy's exact pins then bring every package at its
  pre-release. A notebook or script that installs canVODpy packages next
  to canvodpy pins each of them too: a package that nothing pins to its
  pre-release is installed at its last final version.
- Tags carry the suffix (`v1.0.0b1`, `canvod-store-v1.0.0b1`). Pushing a
  pre-release tag of canvodpy publishes the packages released at that
  commit to TestPyPI, and the draft GitHub release is marked as a
  pre-release. Publishing to PyPI stays a separate step
  ([Releasing](RELEASING.md)).

---

## Choosing a version

For each package in a release:

1. Choose the increment from the changes since the package's last final
   version ([Semantic Versioning](#semantic-versioning)): major, minor or
   patch.
2. Choose the stage ([Pre-releases](#pre-releases)): a pre-release while the
   release is still being tested, the final version once it holds.
3. canvodpy takes at least the largest increment of the packages, and the
   same stage.

---

## Requirements between packages

- `canvodpy` requires each package at exactly one version
  (`canvod-store==1.1.0`): its pins are the log of which mix a canvodpy
  version is.
- A package requires another canVODpy package with a range up to the next
  major version (`canvod-config>=1.0.0,<2`). The lower bound is the
  version that has what the package uses; raise it by hand when the package
  starts to use something newer.
- A major release of a package (for example canvod-config 2.0.0) is outside the
  ranges of the packages that require it: the release is refused until
  each of them is checked against the new version and its range widened by
  hand.
- `__version__` of each package is read from the installed package
  (`importlib.metadata`), never written into the code.

---

## Tags

| Package | Tag | GitHub release |
|---------|-----|----------------|
| canvodpy | `vX.Y.Z` (for example `v1.1.0`) | yes, drafted from `CHANGELOG.md` |
| any other package | `<package>-vX.Y.Z` (for example `canvod-store-v1.1.0`) | no |

Every package has its own `CHANGELOG.md` in its folder; canvodpy's is the
one at the repository root, and each of its sections lists the package
versions it pins.

Before per-package versions (up to 0.4.0), all packages shared one version
and the tag `vX.Y.Z`.

---

## Creating releases

The maintainer chooses the packages and versions;
[Releasing](RELEASING.md) has the steps.

```bash
just release-status                               # commits per package since its last tag
just release canvod-store=1.1.0 canvodpy=1.1.0    # prepare the release commit
just tag-release                                  # on the merged commit on main
```

---

## Deprecation policy

Superseded public code is deprecated with the `deprecated` decorator of
canvod-utils and removed only with the next major version
([ADR 0005](adr/0005-deprecate-until-next-major.md)). The documentation
describes only the code to use: guides and examples leave deprecated code
out, and the API reference hides everything that carries the decorator,
and every argument named by its companion `deprecated_argument`
(`scripts/griffe_hide_deprecated.py`).

---

## Citation

```bibtex
@software{canvodpy2026,
  author  = {Bader, Nicolas and Contributors},
  title   = {canvodpy: GNSS Vegetation Optical Depth Analysis},
  version = {1.0.0},
  year    = {2026},
  url     = {https://github.com/nfb2021/canvodpy},
  doi     = {10.5281/zenodo.XXXXXXX}
}
```

> "Analysis was performed using canvodpy v1.0.0 (Bader et al., 2026)."

Cite the canvodpy version: it fixes the version of every package.

---

[:octicons-arrow-right-24: Release Process](RELEASING.md) &nbsp;&nbsp; [:octicons-arrow-right-24: Conventional Commits](https://www.conventionalcommits.org/)
