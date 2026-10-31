# canvod-auxiliary

Satellite geometry for the observations: orbits and clocks (agency SP3/CLK
products or the receiver's broadcast data), interpolation onto the
observation epochs, receiver position, and θ/φ per epoch and SID.

## Where things live

| Path (under `src/canvod/auxiliary/`) | What |
|---|---|
| `ephemeris/provider.py` | `EphemerisProvider` ABC; `AgencyEphemerisProvider` (SP3/CLK), `SbfBroadcastProvider` (SBF SatVisibility angles), `RinexNavProvider` (RINEX navigation files) |
| `ephemeris/broadcast.py` | Broadcast orbits: navigation records to positions and velocities on a 5-minute grid, the input of the orbit interpolation (ADR 0023) |
| `interpolation/` | The one interpolation module: orbits (polynomial of degree 10 through the 11 nearest epochs, as RTKLIB), clock interpolation, and the day grid (`interpolation/day_grid.py`) |
| `position/` | `ECEFPosition`, geodetic position, spherical coordinates (θ, φ) |
| `products/` | Product registry (`products/products.toml`): which final/rapid agency products exist, their samplings and GNSS, where to fetch them; `products/check.py` checks it against the servers (`just check-products`) |
| `augmentation.py`, `pipeline.py` | Adding the auxiliary data to an observation dataset |
| `cache_fingerprint.py` | Fingerprint of the interpolated-product cache (`AUX_CACHE_FORMAT_VERSION`) |

Background: `docs/packages/auxiliary/overview.md`,
`docs/packages/auxiliary/interpolation.md`,
`docs/packages/auxiliary/coordinates.md`,
`docs/packages/auxiliary/products.md`,
`docs/packages/readers/ephemeris-sources.md`.

## Invariants

- **Epoch grid**: 00:00 of the day plus multiples of the observations'
  sampling interval, the same rule for `canvodpy run`, the Python API and
  Airflow. Products are interpolated once per day onto it.
- **Receiver position** comes from the data (`ECEFPosition.from_ds_metadata`),
  not from the settings.
- **Broadcast geometry**: SBF files take θ/φ from `SbfBroadcastProvider`
  (θ/φ the receiver derived from the almanac are masked; the source of
  each value is recorded). RINEX files take the receiver's navigation
  files through `ephemeris/broadcast.py` and the same orbit
  interpolation as the agency products; never a second interpolation
  path, never a fallback to the agency products (ADR 0023).
- CLK clock bias is read in seconds. When a change alters cached
  interpolation results, raise `AUX_CACHE_FORMAT_VERSION`.
- Angles are radians in datasets; polar angle, not elevation.
- **Products**: only `final` and `rapid`; file names come from
  `ProductSpec.sp3_filenames`/`clk_filenames` (one per listed sampling, tried
  in order). After editing `products/products.toml`, run `just check-products`
  and `just test-network`.

## Tests

```bash
just test-package canvod-auxiliary
```

Downloading products needs network access and credentials; those tests are
marked `integration`.
