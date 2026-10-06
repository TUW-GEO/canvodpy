---
status: accepted, tooling not yet switched
---

# Each package has its own version; canvodpy pins the exact mix

The packages (readers, auxiliary, grids, store, ...) are useful on their
own, so each gets its own version and release tags `<package>-vX.Y.Z`.
The `canvodpy` umbrella package pins every package to an exact version,
so a canvodpy version names exactly the mix of code it runs.
