---
status: accepted
---

# Each package has its own version; canvodpy pins the exact mix

The packages (readers, auxiliary, grids, store, and others) are useful on their
own, so each gets its own version and release tags `<package>-vX.Y.Z`.
The `canvodpy` umbrella package pins every package to an exact version,
so a canvodpy version names exactly the mix of code it runs.

How releases work (`scripts/release.py`, [Versioning](../VERSIONING.md)):

- The maintainer chooses which packages to release and their versions by
  hand; no tool derives them from commit messages. `just release-status`
  lists the commits per package since its last tag to help.
- canvodpy is part of every release, and its increment is at least the
  largest increment of the packages released with it (a minor release of
  canvod-store makes at least a minor release of canvodpy).
- A package requires another canVODpy package with a range up to the next
  major version (`canvod-config>=1.0.0,<2`). A release that leaves such a
  range is refused until the range is checked and widened by hand.
- canvodpy keeps the tags `vX.Y.Z`; only these create a GitHub release
  (and a Zenodo archive), whose notes list the package versions.
- PyPI receives the packages whose release tag points at the published
  commit.
