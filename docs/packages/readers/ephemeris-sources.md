---
title: Ephemeris Sources
description: Three levels of satellite ephemeris for computing observation geometry
---

# Ephemeris Sources

Computing satellite geometry (theta, phi) requires knowing where each satellite
is at each observation epoch. canvodpy supports three ephemeris sources, each
with different accuracy, latency, and connectivity requirements.

---

## Source Overview

<div class="grid cards" markdown>

-   :fontawesome-solid-trophy: &nbsp; **Agency Final Products (SP3/CLK)**

    ---

    Precise orbits (and, by default, clocks) from analysis centres (CODE,
    ESA, IGS). Downloaded via FTP. ~2-3 cm orbit accuracy. Available 12-18
    days after observation.

    **Input:** SP3 (+ CLK, optional — `aux_data.fetch_clock`) files (downloaded)
    **Output:** ECEF XYZ → theta, phi, r

-   :fontawesome-solid-satellite: &nbsp; **SBF Broadcast (SatVisibility)**

    ---

    Satellite elevation and azimuth computed by the receiver firmware
    from broadcast ephemerides embedded in the SBF binary stream.
    Immediate availability, no internet required.

    **Input:** SBF binary file (SatVisibility block)
    **Output:** theta, phi directly

-   :fontawesome-solid-file-lines: &nbsp; **RINEX NAV Broadcast**

    ---

    Keplerian orbital elements from RINEX navigation files (`.YYp`).
    Propagated to target epochs using the Keplerian model (GPS/Galileo/BeiDou)
    or RK4 integration (GLONASS state vectors). Immediate, no internet.

    **Input:** `.YYp` / `.YYn` / `.YYg` nav files
    **Output:** ECEF XYZ → theta, phi, r

</div>

---

## Accuracy Comparison

| Source | Orbit accuracy | Angular error (theta/phi) | Clock accuracy | Latency |
|--------|---------------|--------------------------|----------------|---------|
| Agency final (SP3) | ~2-3 cm | ~0.0000001 deg | ~0.1 ns | 12-18 days |
| SBF broadcast | ~1-2 m | ~0.00001 deg | ~5 ns | Immediate |
| RINEX NAV broadcast | ~1-2 m | ~0.00001 deg | ~5 ns | Immediate |

!!! success "All sources are sufficient for VOD"

    The angular difference between broadcast and final ephemerides is
    six orders of magnitude below GNSS-T measurement noise. For VOD
    retrievals, broadcast ephemerides produce identical results to
    agency final products.

---

## Agency Final Products (SP3/CLK)

The production path used by the orchestrator (Levels 1 and 3).

### Pipeline

```
1. AuxDataPipeline: download SP3 (+ CLK, if aux_data.fetch_clock) from FTP (CODE/ESA/IGS)
2. Hermite interpolation: SP3 positions → target epoch grid
3. Clock piecewise linear interpolation (skipped if fetch_clock=False)
4. Write Zarr cache: aux_{date}.zarr
5. Per file: open Zarr → sel(epoch) → compute_spherical_coordinates()
6. Output: ds["theta"], ds["phi"], ds["r"]
```

CLK is not consumed by the VOD formula (`VOD = -ln(T) · cos(θ)` — only
transmittance and polar angle). Set `aux_data.fetch_clock: false` to skip
steps 1's clock download and step 3 entirely.

### Configuration

```yaml
# canvod-settings.yaml
processing:
  params:
    ephemeris_source: "final"
  aux_data:
    agencies: ["COD"]
    product_type: "final"
    ftp_timeout_s: 30
    fetch_clock: true  # set false to skip CLK download/interpolation
```

### Component locations

| Component | Package | Module |
|-----------|---------|--------|
| SP3/CLK download | canvod-auxiliary | `pipeline.py` |
| FTP with fallback | canvod-auxiliary | `core/downloader.py` |
| Hermite interpolation | canvodpy | `orchestrator/interpolator.py` |
| Clock interpolation (optional, `aux_data.fetch_clock`) | canvodpy | `orchestrator/interpolator.py` |
| ECEF → theta/phi/r | canvod-auxiliary | `position/spherical_coords.py` |

---

## SBF Broadcast

Available when the receiver is a Septentrio unit outputting SBF binary format.
The receiver firmware computes satellite elevation and azimuth from the
broadcast navigation message and embeds them in the `SatVisibility` block.

### How it works

```
1. SBF reader scans file: extracts SatVisibility blocks
2. Azimuth and elevation are pre-computed by receiver firmware
3. Stored in sbf_obs auxiliary dataset as theta/phi
4. Aligned to observation epochs and SIDs
5. No download, no Zarr cache, no coordinate transform needed
```

!!! info "Theta and phi convention"

    SBF SatVisibility provides polar angle (theta = 90° - elevation)
    and geographic azimuth (0° = North, clockwise). Same convention
    used throughout canvodpy — no conversion needed.

### Configuration

```yaml
processing:
  ephemeris_source: "broadcast"
  # reader_format must be "sbf" for this to work
```

### Limitations

- Only available for SBF receivers (Septentrio)
- Theta/phi are tied to the receiver's computed position — if the receiver
  position is inaccurate (poor fix), geometry is slightly affected
- No satellite distance (r) — only angles

---

## RINEX NAV Broadcast

!!! abstract "Status: Phase 3 — not yet implemented"

    The `RinexNavProvider` is planned but not yet built. This section
    documents the design for implementation.

For RINEX receivers, broadcast ephemerides are available in navigation files
(`.YYp` for mixed GNSS, `.YYn` for GPS, `.YYg` for GLONASS) that sit alongside
observation files in the same directory.

### Keplerian propagation

GPS, Galileo, and BeiDou use a common 16-parameter Keplerian orbital model
(IS-GPS-200, Galileo ICD, BeiDou ICD):

```
Input: orbital elements (a, e, i₀, Ω₀, ω, M₀) + correction terms
       from navigation message

Steps:
  1. Mean motion:  n = √(μ/a³) + Δn
  2. Mean anomaly: M = M₀ + n·(t - tₒₑ)
  3. Kepler's equation: E - e·sin(E) = M  (iterate ~10×)
  4. True anomaly: ν = atan2(√(1-e²)·sin(E), cos(E)-e)
  5. Argument of latitude with corrections
  6. Radius with corrections
  7. Inclination with corrections
  8. ECEF rotation from orbital plane

Output: satellite ECEF (X, Y, Z) in meters
```

### GLONASS exception

GLONASS broadcasts state vectors (x, y, z, vx, vy, vz) in PZ-90 frame
instead of Keplerian elements. Propagation uses 4th-order Runge-Kutta
numerical integration (~80 lines of code).

### NAV file types

| Extension | Content | Constellations |
|-----------|---------|----------------|
| `.YYp` | Mixed GNSS navigation | All (GPS + GLONASS + Galileo + BeiDou + ...) |
| `.YYn` | GPS-only navigation | GPS |
| `.YYg` | GLONASS-only navigation | GLONASS |

### Validity intervals

Broadcast ephemerides are valid for ~2-4 hours around their reference epoch
(toe). The propagator must select the closest valid ephemeris set for each
target epoch — not simply the first record found.

---

## Receiver File Types Summary

| Extension | Format | Observations | Broadcast ephemeris | Use in canvodpy |
|-----------|--------|:---:|:---:|---|
| `.YYo` / `.rnx` | RINEX 3 OBS | :fontawesome-solid-check: | — | Primary observation data |
| `.YY_` / `.sbf` | SBF binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Observations + broadcast geometry |
| `.YYp` | RINEX 3 NAV (mixed) | — | :fontawesome-solid-check: | Broadcast ephemeris (Phase 3) |
| `.YYn` | RINEX 2 NAV (GPS) | — | :fontawesome-solid-check: | Legacy broadcast (Phase 3) |
| `.YYg` | RINEX NAV (GLONASS) | — | :fontawesome-solid-check: | Legacy broadcast (Phase 3) |
| `.YY1` | NMEA | — | — | **Not used** (integer-degree precision) |
| `.ubx` | u-blox binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Future (Phase 4) |

!!! warning "NMEA is not an ephemeris source"

    NMEA `.YY1` files contain GSV sentences with integer-degree satellite
    elevation and azimuth. This 1° precision is far too coarse for VOD.
    NMEA also lacks carrier-phase observables. These files are ignored by canvodpy.

---

## Choosing an Ephemeris Source

??? question "When should I use agency final products?"

    Use `ephemeris_source: "final"` when:

    - You need the highest possible accuracy for research publications
    - Data is more than 18 days old (products are available)
    - You have internet access during processing
    - You're doing reanalysis or reprocessing

??? question "When should I use broadcast ephemerides?"

    Use `ephemeris_source: "broadcast"` when:

    - Processing near-real-time data (same day or recent)
    - Working offline or in the field
    - Running an SBF receiver (geometry is free — embedded in the file)
    - VOD accuracy is the goal (broadcast is more than sufficient)

??? question "What about `auto` mode?"

    `ephemeris_source: "auto"` (planned) will prefer broadcast if available,
    falling back to agency final products. This is the recommended default
    for production pipelines that may run on both fresh and aged data.

---

!!! example "Try it"
    [08 · Ephemeris & Coordinates](../../notebooks/_build/08_ephemeris_coordinates.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/08_ephemeris_coordinates.py)
