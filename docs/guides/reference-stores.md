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

A profile that changes one thing of another profile has only
`reference-runs.yaml`. It names the other profile as `base`, lists its
change under `settings` and picks sites of the base under `sites`:

```yaml
base: default
settings:
  processing:
    params:
      ephemeris_source: broadcast
sites:
  rosalia_sbf: {}    # the base's days and SIDs
```

Its runs use the base's settings folder; the build merges `settings`
into the settings file it passes with `--config`. So `settings` is
exactly what differs from the base.

| Profile | Data | Days | Settings |
|---|---|---|---|
| `default` | both receivers of every site of the test data: Rosalia (RINEX v3.04, SBF, NMEA), MOFLUX (RINEX v2.11), ExampleSite (stripped RINEX v3.05), Hainich (NMEA) | 2025-001; Hainich 2026-001 | final SP3/CLK from the test data, no preprocessing, SNR only, VOD of each receiver pair, the SIDs of each site (below) |
| `sbf-broadcast` | both receivers of Rosalia (SBF) | 2025-001 | as `default`, but the satellite geometry from the broadcast ephemerides the SBF files carry |
| `gridded` | as `default` | as `default` | as `default`, plus the preprocessing: observations aggregated to 1-minute means (integer flags take the first value of each minute) and assigned to the cells of a 2° equal-area grid |

Each site's stores hold that site's own SIDs: per system (GPS, GLONASS,
Galileo and BeiDou, the systems the final orbits cover), up to 15 SIDs
that both receivers recorded SNR for the longest on the test day. The
lists are under `sids` in `reference-runs.yaml`. The build writes each
site's list into the settings file it passes to that site's run with
`--config`, and a list there replaces the list in
`canvod-settings.yaml` as a whole (see
[overlay file](configuration.md#overlay-file)).

The MOFLUX files carry no receiver position. The build copies them into
its output folder with the made-up test position in the header and runs
on the copies.

A run with a profile downloads nothing: the orbit and clock files come
from the test data. The metadata names the made-up identity the tests
use, so the stores name no real person.

## Build and check

The test data must be checked out (`git submodule update --init`).

```bash
just reference-check                        # run the profiles again and compare with the published stores
just reference-stores ~/reference-stores    # build the stores of every profile into a new folder
just reference-stores ~/broadcast sbf-broadcast   # only the named profiles
just reference-check ~/reference-stores     # compare with a build of your own
```

`just reference-check` builds the stores again in a temporary folder and
compares each GNSS store and VOD store with the reference stores, using
`compare_stores` (see the [store overview](../packages/store/overview.md)).
It writes the report to `reference-check.txt` (empty when the stores
match; a second argument sets another path) and exits with 1 on a
difference. The reference stores it compares with:

- without a folder, the published stores: the zips of one commit of the
  Hugging Face dataset named in `reference/published.yaml`. They are
  downloaded once into the user cache folder, and each zip's sha256 is
  checked against `reference/SHA256SUMS` before it is unpacked;
- a build folder (`just reference-stores`);
- a folder of zips (`just reference-pack`, below).

The folder must hold every profile: the check runs them all.

For the `default` profile, a build and a check each take three to four
minutes; the SBF day takes the longest. The `sbf-broadcast` profile
takes one and a half minutes, the `gridded` profile three to four
minutes. Two builds of the same code compare with an empty report: the
run is deterministic.

## Tolerances

Integer and flag variables, coordinates, groups, and every attribute
except the ones that change with every run (times, ids, the software
version; `VOLATILE_ATTRIBUTES`) must match exactly. Float variables are compared within one
absolute tolerance per variable, derived from the finest resolution any
format records. The table, with the derivation and its sources, is in
the [store overview](../packages/store/overview.md); the code holds it
as `FLOAT_TOLERANCES` in
`packages/canvod-store/src/canvod/store/comparison.py`.

## When the check fails

A difference means the new code stores something else. Either the
change is a bug, or it is intended: then say so in the pull request,
with the report, and change the reference stores (below).

A new setting with a default, or a changed default, fails the check
too: the report names it under `content_settings`. The remedy is the
same: new reference stores and a CHANGELOG entry, never an entry in
`VOLATILE_ATTRIBUTES`. That list holds only what changes with every run
or release.

## Changing the reference stores

1. The pull request says why the stores change and holds the report of
   `just reference-check`.
2. Build every profile from one commit, then pack the build:

   ```bash
   just reference-stores ~/reference-stores
   just reference-pack ~/reference-stores ~/reference-zips
   just reference-check ~/reference-zips    # the zips give an empty report
   ```

   `just reference-pack` writes one zip per store,
   `<profile>/<site>-<gnss|vod>.zip`, and their sha256 into `SHA256SUMS`.
   The zips hold only the stores: no settings files, no logs. It refuses
   a store that holds a local path (the build folder, the repository,
   the home folder). The zips are deterministic: packing the same build
   again gives the same sha256.
3. A maintainer uploads the folder of zips to the Hugging Face dataset
   (agents have no Hugging Face token):

   ```bash
   hf upload nfb2021/canvodpy-reference-stores ~/reference-zips . --repo-type dataset
   ```

4. The pull request moves `revision` in `reference/published.yaml` to the
   new commit of the dataset and replaces `reference/SHA256SUMS` with
   the new one.
