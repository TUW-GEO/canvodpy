# Reference stores

A reference store is a GNSS store or VOD store built from the test data
with a setting profile. New code must reproduce it: a change that alters
the stored observations, the satellite geometry or the VOD shows up as a
difference when the profiles run again.

## Setting profiles

A setting profile is an ordinary settings folder under
`reference/profiles/`. `canvodpy run` uses it as the settings folder
(`--config-dir`), so the check runs the same code as any run; nothing
is patched. Each profile has two files:

- `canvod-settings.yaml`: the settings. Data paths are relative to the
  repository root and point into the test data.
- `reference-runs.yaml`: the sites and days the profile runs.

| Profile | Data | Days | Settings |
|---|---|---|---|
| `default` | Rosalia, RINEX v3.04: the canopy receiver and the reference receiver | 2025-001 | final SP3/CLK from the test data, no preprocessing, SNR only, 15 SIDs per system (GPS, GLONASS, Galileo, BeiDou), VOD of the receiver pair |

A run with a profile downloads nothing: the orbit and clock files come
from the test data. The metadata names the made-up identity the tests
use, so the stores name no real person.

## Build and check

The test data must be checked out (`git submodule update --init`).

```bash
just reference-stores ~/reference-stores    # build the stores of every profile into a new folder
just reference-check ~/reference-stores     # run the profiles again and compare
```

`just reference-check` builds the stores again in a temporary folder and
compares each GNSS store and VOD store with the reference stores, using
`compare_stores` (see the [store overview](../packages/store/overview.md)).
It writes the report to `reference-check.txt` (empty when the stores
match; a second argument sets another path) and exits with 1 on a
difference.

For the `default` profile, a build and a check each take under a
minute on a laptop. Two builds of the same code compare with an empty
report: the run is deterministic.

## Tolerances

Integer and flag variables, coordinates, groups, and the compared
attributes must match exactly. Float variables are compared within one
absolute tolerance per variable, derived from the finest resolution any
format records. The table, with the derivation and its sources, is in
the [store overview](../packages/store/overview.md); the code holds it
as `FLOAT_TOLERANCES` in
`packages/canvod-store/src/canvod/store/comparison.py`.

## When the check fails

A difference means the new code stores something else. Either the
change is a bug, or it is intended: then say so in the pull request,
with the report, and build new reference stores.
