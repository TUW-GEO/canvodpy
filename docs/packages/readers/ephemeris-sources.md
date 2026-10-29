---
title: Ephemeris Sources
description: Three levels of satellite ephemeris for computing observation geometry
---

# Ephemeris sources

Computing satellite geometry (theta, phi) requires knowing where each satellite
is at each observation epoch. canvodpy supports two ephemeris sources: the
precise ephemeris of an analysis center (`ephemeris_source: precise`) and the
broadcast ephemeris the receiver recorded (`ephemeris_source: broadcast`,
from SBF files or from RINEX navigation files).

---

## Source overview

<div class="grid cards" markdown>

-   :fontawesome-solid-trophy: &nbsp; **Precise ephemeris (SP3/CLK)**

    ---

    Orbits (and, optionally, clocks) computed afterwards by analysis
    centers (CODE, ESA, IGS), as final or rapid products. Downloaded via
    FTP. Final products are published only after a delay.

    **Input:** SP3 (+ CLK, optional, see `aux_data.fetch_clock`) files (downloaded)
    **Output:** ECEF XYZ $\rightarrow$ $\theta$, $\varphi$, $r$

-   :fontawesome-solid-satellite: &nbsp; **Broadcast ephemeris, SBF (SatVisibility)**

    ---

    Satellite elevation and azimuth computed by the receiver firmware
    from broadcast ephemerides embedded in the SBF binary stream.
    Immediate availability, no internet required.

    **Input:** SBF binary file (SatVisibility block)
    **Output:** theta, phi directly

-   :fontawesome-solid-file-lines: &nbsp; **Broadcast ephemeris, RINEX navigation files**

    ---

    Orbit parameters the satellites broadcast, recorded by the receiver
    in RINEX navigation files. Satellite positions on a 5-minute grid,
    then the same interpolation as the precise ephemeris. GPS so far.

    **Input:** RINEX 3.04/3.05 navigation files (`nav_directory`)
    **Output:** ECEF XYZ $\rightarrow$ $\theta$, $\varphi$, $r$

</div>

---

## Accuracy

The SBF angles are stored by the receiver with a resolution of $0.01^\circ$
(SatVisibility block), so they cannot be more precise than that. The SP3
path computes $\theta$ and $\varphi$ from interpolated satellite positions and the
receiver position. canvodpy has not quantified the difference between the
two sources on its test data; until then, do not mix them in one analysis.

The angles from RINEX navigation files were compared with those from the
COD final orbits on the test day (2025-001, GPS, every 30 s): the largest
difference was $0.00002^\circ$, the median $0.000002^\circ$.

---

## Precise ephemeris (SP3/CLK)

The default path of `canvodpy run` (`ephemeris_source: precise`). The
products are chosen by `aux_data.agency` and `aux_data.product_type`
(`final` or `rapid`). Before v1.0.1 this source was called `final`; that name
still works until v2.0.0 and warns.

The agency and the product type apply only to the precise ephemeris. With
`ephemeris_source: broadcast`, a store records them as empty in its content
settings, and a value other than the default (`COD`, `final`) warns that it
is ignored. A broadcast store created before v1.0.1 recorded them as they
were set; runs still write to it, since broadcast stores do not compare them.

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
transmittance and polar angle, so `aux_data.fetch_clock` is `false` by
default, which skips step 1's clock download and step 4 entirely.

### Configuration

```yaml
# canvod-settings.yaml
processing:
  params:
    ephemeris_source: "precise"
  aux_data:
    agency: "COD"
    product_type: "final"
    ftp_timeout_s: 30
    fetch_clock: false  # true: also download and interpolate CLK
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

## Broadcast ephemeris from SBF

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

## Broadcast ephemeris from RINEX navigation files

With `ephemeris_source: broadcast`, a receiver with RINEX files takes the
satellite positions from its own RINEX 3.04/3.05 navigation files (ADR 0023).
So far GPS: the signals of the other systems are stored without $\theta$
and $\varphi$, so they get no VOD; the run log says so for each receiver
and day. The files sit in the folder `nav_directory` names, relative to the
site data root like `directory` (it may be the same folder), and need
canonical names of type `nav` with sampling `00U`, for example
`FANA01INK_R_20250010000_15M_00U_AA.nav`.

### How it works

```
1. Read the day's navigation files of the receiver (canvod-readers, rinex/nav.py)
2. Per satellite and 5-minute grid time, the record with the nearest time of
   ephemeris, if the time lies within half its fit interval; elsewhere NaN
3. GPS orbit from the record's Keplerian elements (IS-GPS-200N, Table 20-IV);
   velocities from the positions 0.5 s before and after
4. From here as the precise ephemeris: Hermite interpolation onto the epoch
   grid, Zarr cache 00_aux_zarr/aux_{date}_{site}_{receiver}_nav.zarr,
   theta/phi
```

Records flagged unhealthy are still used. G01 and G22 sent such records on
the test day; their angles differed from those of the COD final
orbits by at most $0.00002^\circ$ (G01, the largest difference of the day).

`ephemeris_source: broadcast` supports SBF and RINEX files. An NMEA
receiver takes its angles from the precise ephemeris only: the settings
check refuses it under `broadcast`, and so does the run for a receiver
whose format shows only in its files.

A day without navigation files stops the run, with an error that names the
receiver, the day, and the folder searched. There is no fallback to the
precise ephemeris.

### Configuration

```yaml
processing:
  params:
    ephemeris_source: "broadcast"
sites:
  <site>:
    receivers:
      canopy_01:
        directory: 02_canopy
        nav_directory: 02_canopy_nav
        reader_format: rinex3
```

Settings with `broadcast` and a receiver whose `reader_format` is a RINEX
format but that has no `nav_directory` are refused.

---

## Receiver file types summary

| Extension | Format | Observations | Broadcast ephemeris | Use in canvodpy |
|-----------|--------|:---:|:---:|---|
| `.YYo` / `.rnx` | RINEX 3 OBS | :fontawesome-solid-check: | No | Primary observation data |
| `.YY_` / `.sbf` | SBF binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Observations + broadcast geometry |
| `.YYp` / `.nav` | RINEX 3 NAV (mixed) | No | :fontawesome-solid-check: | Broadcast ephemeris (GPS so far), canonical type `nav` |
| `.YYn` | RINEX 2 NAV (GPS) | No | :fontawesome-solid-check: | Not read (planned) |
| `.YYg` | RINEX NAV (GLONASS) | No | :fontawesome-solid-check: | Not read (planned) |
| `.nmea` | NMEA 0183 | SNR only | No | Observations (`NmeaObs`); geometry from SP3 |
| `.ubx` | u-blox binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Not supported |

!!! warning "NMEA is not an ephemeris source"

    NMEA GSV sentences carry satellite elevation and azimuth in whole
    degrees. `NmeaObs` reads the signal strengths only; the geometry of
    NMEA data comes from SP3 files and the receiver position of the GGA
    fixes ([readers overview](overview.md)).

---

## Choosing an ephemeris source

??? question "When to use the precise ephemeris"

    Use `ephemeris_source: "precise"` when:

    - The receivers write NMEA (the only source for them), or RINEX
      without navigation files
    - Final products are available for the days
    - You have internet access during processing

??? question "When to use the broadcast ephemeris"

    Use `ephemeris_source: "broadcast"` when:

    - The receivers write SBF (the geometry is embedded in the file), or
      RINEX navigation files next to their RINEX observations
    - Processing recent data, before final products are published
    - Working offline
