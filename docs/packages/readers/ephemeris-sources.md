---
title: Ephemeris Sources
description: The precise and the broadcast ephemeris, how to choose between them, and how to set up navigation files
---

# Ephemeris sources

Computing satellite geometry (theta, phi) requires knowing where each satellite
is at each observation epoch. canvodpy supports two ephemeris sources: the
precise ephemeris of an analysis center (`ephemeris_source: precise`) and the
broadcast ephemeris the receiver recorded (`ephemeris_source: broadcast`,
from SBF files or from RINEX navigation files). A store holds one
ephemeris: its content settings record the source, and a run with the
other source stops at an existing store. Give that run a store of its own
(another `gnss_store_name`).

## Setting up a run

1. Choose the source (see [Choosing an ephemeris source](#choosing-an-ephemeris-source)).
2. With `broadcast`, give each receiver with RINEX files the folder of its
   navigation files as `nav_directory`, and a `nav_recipe` if their names
   don't follow the convention. In shared-position mode (the default)
   only the canopy receivers need them (see
   [Broadcast ephemeris from RINEX navigation files](#broadcast-ephemeris-from-rinex-navigation-files)).
   SBF files need nothing more.
3. Check the settings, then run:

=== "Command line"

    ```bash
    canvodpy config validate
    canvodpy run --site ExampleSite --start 2025001 --end 2025007 \
        --ephemeris-source broadcast
    ```

    Without `--ephemeris-source`, the run takes
    `processing.params.ephemeris_source` from the settings file. A site
    whose store was made with the other source stops; see the start of
    this page.

=== "Python"

    ```python
    from canvodpy import Site

    site = Site("ExampleSite")
    with site.pipeline() as pipeline:
        for unit in pipeline.run("2025001", "2025007"):
            print(sorted(unit.days), unit.vod.written)
    ```

    The pipeline takes `processing.params.ephemeris_source` from the
    settings file.

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
    then the same interpolation as the precise ephemeris. GPS, Galileo,
    GLONASS, BeiDou, QZSS, and SBAS so far.

    **Input:** RINEX 3.04/3.05 navigation files (`nav_directory`)
    **Output:** ECEF XYZ $\rightarrow$ $\theta$, $\varphi$, $r$

</div>

---

## Accuracy

To date, no in-depth scientific analysis or comparison of the precise and
the broadcast ephemeris has been done. It is up to you to decide which one
to use for which task and to what end.

The receiver stores the SatVisibility angles of SBF files with a
resolution of $0.01^\circ$ (SatVisibility block; Septentrio AsteRx SB3
ProBase Firmware v4.14.0 Reference Guide, p. 400).

---

## Precise ephemeris (SP3/CLK)

The default source (`ephemeris_source: precise`). The
products are chosen by `aux_data.agency` and `aux_data.product_type`
(`final` or `rapid`). Before v1.1.0 this source was called `final`; that name
still works until v2.0.0 and warns.

The agency and the product type apply only to the precise ephemeris. With
`ephemeris_source: broadcast`, a store records them as empty in its content
settings, and a value other than the default (`COD`, `final`) warns that it
is ignored. A broadcast store created before v1.1.0 recorded them as they
were set; runs still write to it, since broadcast stores do not compare them.

### Pipeline

```
1. AuxDataPipeline: download SP3 (+ CLK, if aux_data.fetch_clock) from FTP (CODE/ESA/IGS)
2. Epoch grid of the day: 00:00 plus multiples of the sampling interval of the
   observations (1 s with a shared aux cache), in GPS time like the SP3 file
3. Hermite interpolation: SP3 positions → epoch grid
4. Clock piecewise linear interpolation (skipped if fetch_clock=False)
5. Write Zarr cache: 00_aux_zarr/aux_{date}.zarr; with a shared aux cache an
   entry of aux_cache.zarr, one value per satellite for all its signals
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
In shared-position mode (`receiver_position_mode: shared`, the default) a
reference receiver takes them from the navigation files of the canopy it is
paired with, as with SBF files, and needs none of its own.
So far GPS, Galileo, GLONASS, BeiDou, QZSS, and SBAS: the signals of the other systems
are stored without $\theta$ and $\varphi$, so they get no VOD; the run log
names the systems with angles for each receiver and day. The files sit in
the folder `nav_directory` names, relative to the site data root like
`directory` (it may be the same folder), and need canonical names of type
`nav` with sampling `00U`, for example
`FANA01INK_R_20250010000_15M_00U_AA.nav`. Navigation files with other
names need a naming recipe with `file_type: nav`, set as the receiver's
`nav_recipe` (given like `recipe`; see
[Files that don't follow the convention](../naming/overview.md#files-that-dont-follow-the-convention)).
In per-receiver mode (`receiver_position_mode: per_receiver`) every
receiver with RINEX files reads its own navigation files.

### How it works

```
1. Read the day's navigation files of the receiver (canvod-readers, rinex/nav.py)
2. Per satellite and 5-minute grid time, the record with the nearest time of
   ephemeris, if the time lies within half its fit interval; elsewhere NaN
3. Orbit from the record's Keplerian elements (IS-GPS-200N, Table 20-IV,
   with each system's constants; BeiDou GEO satellites with the rotations
   of BDS-SIS-ICD-B1I-3.0, Table 5-11); velocities from the positions
   0.5 s before and after. GLONASS: the record's position, velocity and
   luni-solar acceleration, integrated to the grid time (ICD GLONASS,
   Edition 5.1, A.3.1.2), which also gives the velocity. SBAS: the
   record's position, moved with its velocity and acceleration to the grid
   time (RINEX 3.05, Table A16)
4. From here as the precise ephemeris: Hermite interpolation onto the epoch
   grid, Zarr cache 00_aux_zarr/aux_{date}_{site}_{receiver}_nav.zarr,
   theta/phi. With `shared_aux_cache_dir` the interpolated orbits go to the
   shared cache instead, one entry per date and content of the navigation
   files (SHA-256), so a rerun of the day computes nothing again and a
   changed or added navigation file gives a new entry
```

The fit interval is the one in the record for GPS (at least 4 hours) and
2 hours for QZSS (IS-QZSS-PNT-005, Table 4.1.1-2). The Galileo and BeiDou
interface specifications give none; canvodpy uses those records for 4
hours too, 2 hours on either side of their time of ephemeris. A GLONASS
record is used within 15 minutes of its time, the interval over which the
ICD keeps its luni-solar acceleration constant (A.3.1.2). GLONASS records
are in UTC; canvodpy converts them to GPS time with the leap seconds of
the date. An SBAS record is used within 6 minutes of its time, the
time-out of the GEO navigation message for en route, terminal and
non-precision approach (RTCA DO-229D, Table 2-1 and Table A-25). The
standard counts the time-out from the end of reception; a RINEX
navigation file keeps no reception time, so canvodpy takes the 6 minutes
on either side of the record's time.

A satellite with no valid record at an epoch has NaN angles there,
never extrapolated ones. The run names these satellites with their
epochs, per receiver-day and in the log book (see
[Satellites without a position](../../guides/diagnostics.md#satellites-without-a-position)).

Records flagged unhealthy are still used.

`ephemeris_source: broadcast` supports SBF and RINEX files. NMEA receivers
and receivers read by a reader plugin take their angles from the precise
ephemeris only: under `broadcast`, the settings check refuses NMEA
receivers, and the run refuses the others once their files show the
format.

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
        nav_recipe: my_site_canopy_nav  # only for names outside the convention
        reader_format: rinex3
```

Settings with `broadcast` and a receiver whose `reader_format` is a RINEX
format but that has no `nav_directory` are refused; in shared-position
mode, reference receivers are exempt. A `nav_recipe` without
`nav_directory` is refused too. In Airflow, `check_day` waits for the
navigation files as it waits for the observation files.

---

## Receiver file types summary

| Extension | Format | Observations | Broadcast ephemeris | Use in canvodpy |
|-----------|--------|:---:|:---:|---|
| `.YYo` / `.rnx` | RINEX 3 OBS | :fontawesome-solid-check: | No | Primary observation data |
| `.YY_` / `.sbf` | SBF binary | :fontawesome-solid-check: | :fontawesome-solid-check: | Observations + broadcast geometry |
| `.YYp` / `.nav` | RINEX 3 NAV (mixed) | No | :fontawesome-solid-check: | Broadcast ephemeris (GPS, Galileo, GLONASS, BeiDou, QZSS, SBAS so far), canonical type `nav` |
| `.YYn` | RINEX 2 NAV (GPS) | No | :fontawesome-solid-check: | Not read (planned) |
| `.YYg` | RINEX 2 NAV (GLONASS) | No | :fontawesome-solid-check: | Not read (planned) |
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
