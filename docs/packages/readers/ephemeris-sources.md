---
title: Ephemeris Sources
description: Three levels of satellite ephemeris for computing observation geometry
---

# Ephemeris sources

Computing satellite geometry (theta, phi) requires knowing where each satellite
is at each observation epoch. canvodpy supports two ephemeris sources; a third
(RINEX navigation files) is planned.

---

## Source overview

<div class="grid cards" markdown>

-   :fontawesome-solid-trophy: &nbsp; **Agency Final Products (SP3/CLK)**

    ---

    Precise orbits (and, by default, clocks) from analysis centers (CODE,
    ESA, IGS). Downloaded via FTP. Final products are published about two
    weeks after observation.

    **Input:** SP3 (+ CLK, optional, see `aux_data.fetch_clock`) files (downloaded)
    **Output:** ECEF XYZ $\rightarrow$ $\theta$, $\varphi$, $r$

-   :fontawesome-solid-satellite: &nbsp; **SBF Broadcast (SatVisibility)**

    ---

    Satellite elevation and azimuth computed by the receiver firmware
    from broadcast ephemerides embedded in the SBF binary stream.
    Immediate availability, no internet required.

    **Input:** SBF binary file (SatVisibility block)
    **Output:** theta, phi directly

-   :fontawesome-solid-file-lines: &nbsp; **RINEX NAV Broadcast (planned)**

    ---

    Not implemented yet. Keplerian orbital elements from RINEX navigation files (`.YYp`).
    Propagated to target epochs using the Keplerian model (GPS/Galileo/BeiDou)
    or RK4 integration (GLONASS state vectors). Immediate, no internet.

    **Input:** `.YYp` / `.YYn` / `.YYg` nav files
    **Output:** ECEF XYZ $\rightarrow$ $\theta$, $\varphi$, $r$

</div>

---

## Accuracy

The SBF angles are stored by the receiver with a resolution of $0.01^\circ$
(SatVisibility block), so they cannot be more precise than that. The SP3
path computes $\theta$ and $\varphi$ from interpolated satellite positions and the
receiver position. canvodpy has not quantified the difference between the
two sources on its test data; until then, do not mix them in one analysis.

---

## Agency final products (SP3/CLK)

The default path of `canvodpy run` (`ephemeris_source: final`).

### Pipeline

```
1. AuxDataPipeline: download SP3 (+ CLK, if aux_data.fetch_clock) from FTP (CODE/ESA/IGS)
2. Epoch grid of the day: 00:00 plus multiples of the sampling interval of the
   observations (1 s with a shared aux cache), in GPS time like the SP3 file
3. Hermite interpolation: SP3 positions → epoch grid
4. Clock piecewise linear interpolation (skipped if fetch_clock=False)
5. Write Zarr cache: 00_aux_zarr/aux_{date}.zarr
6. Per file: open Zarr → nearest grid epoch per observation epoch
   → compute_spherical_coordinates()
7. Output: ds["theta"], ds["phi"], ds["r"]
```

CLK is not used by the VOD formula, $\text{VOD} = -\ln(T) \cdot \cos\theta$, which needs only
transmittance and polar angle. Set `aux_data.fetch_clock: false` to skip
step 1's clock download and step 4 entirely.

### Configuration

```yaml
# canvod-settings.yaml
processing:
  params:
    ephemeris_source: "final"
  aux_data:
    agency: "COD"
    product_type: "final"
    ftp_timeout_s: 30
    fetch_clock: true  # set false to skip CLK download/interpolation
```

### Component locations

| Component | Package | Module |
|-----------|---------|--------|
| SP3/CLK download | canvod-auxiliary | `pipeline.py` |
| FTP with fallback | canvod-auxiliary | `core/downloader.py` |
| Hermite interpolation | canvod-auxiliary | `interpolation/interpolator.py` |
| Clock interpolation (optional, `aux_data.fetch_clock`) | canvod-auxiliary | `interpolation/interpolator.py` |
| ECEF $\rightarrow$ $\theta$, $\varphi$, $r$ | canvod-auxiliary | `position/spherical_coords.py` |

---

## SBF broadcast

Available when the receiver is a Septentrio unit outputting SBF binary format,
with `ephemeris_source: broadcast`.
The receiver firmware computes satellite elevation and azimuth from the
satellite's almanac or broadcast ephemeris and embeds them in the
`SatVisibility` block, together with which of the two it used.

### How it works

```
1. SBF reader scans file: extracts SatVisibility blocks
2. Azimuth and elevation are pre-computed by receiver firmware
3. Stored in the sbf_obs auxiliary dataset as broadcast_theta/broadcast_phi
   (radians), on the epochs and SIDs of the observations: each value comes
   from the SatVisibility block with the same time stamp as the observations
4. Copied to theta/phi of the observations dataset where the receiver
   computed them from the broadcast ephemeris (broadcast_angle_source = 2);
   almanac-based angles become NaN, and a file with no ephemeris-based
   angle raises an error
5. No download, no Zarr cache, no coordinate transform needed
```

!!! info "Theta and phi convention"

    SBF SatVisibility provides elevation and geographic azimuth
    ($0^\circ$ = North, clockwise). The reader converts elevation to the polar
    angle ($\theta = 90^\circ - \text{elevation}$) and both angles to radians, the
    convention used throughout canvodpy.

### Configuration

```yaml
processing:
  params:
    ephemeris_source: "broadcast"
  # reader_format must be "sbf" for this to work
```

### Limitations

- Only available for SBF receivers (Septentrio)
- Theta/phi are tied to the receiver's computed position: if the receiver
  position is inaccurate (poor fix), geometry is slightly affected
- No satellite distance ($r$), only angles

---

## RINEX NAV broadcast

!!! abstract "Status: not implemented"

    A `RinexNavProvider` is planned but not built. This section records
    the intended design.

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

GLONASS broadcasts state vectors ($x$, $y$, $z$, $v_x$, $v_y$, $v_z$) in PZ-90 frame
instead of Keplerian elements. Propagation uses fourth-order Runge-Kutta
numerical integration.

### NAV file types

| Extension | Content | Constellations |
|-----------|---------|----------------|
| `.YYp` | Mixed GNSS navigation | All (GPS, GLONASS, Galileo, BeiDou, and others) |
| `.YYn` | GPS-only navigation | GPS |
| `.YYg` | GLONASS-only navigation | GLONASS |

### Validity intervals

Broadcast ephemerides are valid for ~2-4 hours around their reference epoch
(toe). The propagator must select the closest valid ephemeris set for each
target epoch, not simply the first record found.

---

## Receiver file types summary

| Extension | Format | Observations | Broadcast ephemeris | Use in canvodpy |
|-----------|--------|:---:|:---:|---|
| `.YYo` / `.rnx` | RINEX 3 OBS | :fontawesome-solid-check: | No | Primary observation data |
| `.YY_` / `.sbf` | SBF binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Observations + broadcast geometry |
| `.YYp` | RINEX 3 NAV (mixed) | No | :fontawesome-solid-check: | Not read (planned) |
| `.YYn` | RINEX 2 NAV (GPS) | No | :fontawesome-solid-check: | Not read (planned) |
| `.YYg` | RINEX NAV (GLONASS) | No | :fontawesome-solid-check: | Not read (planned) |
| `.nmea` | NMEA 0183 | SNR only | No | Observations (`NmeaObs`); geometry from SP3 |
| `.ubx` | u-blox binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Not supported |

!!! warning "NMEA is not an ephemeris source"

    NMEA GSV sentences carry satellite elevation and azimuth in whole
    degrees. `NmeaObs` reads the signal strengths only; the geometry of
    NMEA data comes from SP3 files.

---

## Choosing an ephemeris source

??? question "When to use agency final products"

    Use `ephemeris_source: "final"` when:

    - The receivers write RINEX or NMEA (the only source for them)
    - Final products are available for the days (about two weeks after
      observation)
    - You have internet access during processing

??? question "When to use broadcast ephemerides"

    Use `ephemeris_source: "broadcast"` when:

    - The receivers write SBF (the geometry is embedded in the file)
    - Processing recent data, before final products are published
    - Working offline
