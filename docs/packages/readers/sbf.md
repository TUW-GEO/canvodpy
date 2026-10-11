# SBF reader (Septentrio Binary Format)

## Overview

The Septentrio Binary Format (SBF) is the proprietary high-rate binary telemetry
output of Septentrio GNSS receivers (AsteRx SB3, mosaic-X5, PolaRx, etc.).
`SbfReader` in `canvod-readers` decodes SBF streams and produces two complementary
`xarray.Dataset` objects from a **single file scan**.

All blocks with the same receiver time stamp (TOW, WNc) belong to one epoch
(RefGuide-4.14.0, Section 4.1.3). The reader groups them that way, so the
MeasExtra, SatVisibility, PVT and status values of an epoch are stored with
the observations of that same epoch. One decoder serves `iter_epochs()`,
`to_ds()` and `to_ds_and_auxiliary()`; they give the same values.

!!! tip "No ephemeris download needed"

    The SBF reader differs from `Rnxv3Obs` (RINEX) in one fundamental respect:
    **satellite geometry is embedded in the binary stream**.
    No SP3 ephemeris download is required for quick-look analysis:
    the receiver firmware reports azimuth and elevation for every satellite
    it has an almanac or broadcast ephemeris for.

---

## Decoded SBF blocks

<div class="grid cards" markdown>

-   :fontawesome-solid-tower-broadcast: &nbsp; **ReceiverSetup**

    ---

    Receiver serial number, firmware version, station name.
    Populates global dataset attributes.

-   :fontawesome-solid-clock: &nbsp; **ReceiverTime**

    ---

    Receiver time and its synchronization with GNSS time.
    Grouped with the epoch; epochs need only the WNc and TOW of MeasEpoch.

-   :fontawesome-solid-satellite: &nbsp; **ChannelStatus**

    ---

    Per-satellite tracking and PVT-usage status bit fields
    (`tracking_status_raw`, `pvt_status_raw`), main antenna.

-   :fontawesome-solid-signal: &nbsp; **MeasEpoch**

    ---

    Per-epoch GNSS observations: $C/N_0$ (SNR), pseudorange, carrier phase, Doppler.
    Primary source for the observations dataset.

-   :fontawesome-solid-map-pin: &nbsp; **PVTGeodetic**

    ---

    Navigation solution: position fix, fix type, number of SVs used,
    horizontal and vertical accuracy estimates, age of corrections.

-   :fontawesome-solid-chart-bar: &nbsp; **DOP**

    ---

    Dilution of Precision (PDOP, HDOP, VDOP) per epoch.

-   :fontawesome-solid-microchip: &nbsp; **ReceiverStatus**

    ---

    CPU load, board temperature, error bit-field `rx_error`.

-   :fontawesome-solid-compass: &nbsp; **SatVisibility**

    ---

    Per-satellite azimuth and elevation for each satellite above the
    horizon with an almanac or broadcast ephemeris, and which of the two
    the receiver used. Converted to geographic azimuth $\varphi$ and polar angle $\theta$.

-   :fontawesome-solid-wave-square: &nbsp; **MeasExtra**

    ---

    Extra per-signal quality: multipath and smoothing corrections,
    code and carrier noise variance, lock time, CN0HighRes.

-   :fontawesome-solid-gauge: &nbsp; **QualityInd**

    ---

    Receiver quality scores (0-10): overall, GNSS signals, RF power,
    CPU headroom, scintillation (firmware $\geq$ 4.15.1).

-   :fontawesome-solid-shield-halved: &nbsp; **RFStatus**

    ---

    Spoofing and navigation-message-authentication (NMA) flags.

</div>

---

## Output datasets

### Observations dataset: `to_ds()`

Identical structure to `Rnxv3Obs.to_ds()`, a drop-in replacement:

| Property | Value |
| -------- | ----- |
| Dimensions | `(epoch, sid)` |
| `epoch` coordinate | `datetime64[ns]`, GPS time (attribute `time_system: GPS`) |
| `sid` coordinate | `"SV\|Band\|Code"` string (for example `G07\|L1\|C`) |
| Data variables | `SNR`, `Pseudorange`, `Phase`, `Doppler`, `SSI`, `Smoothing`, `HalfCycle` (select with `keep_data_vars`) |
| Validation | Passes `validate_dataset()` |

`SNR` includes the MeasExtra CN0HighRes value of the same epoch where
MeasExtra is logged (0.03125 dB-Hz resolution instead of 0.25 dB-Hz).
`SSI` is derived from `SNR` (RINEX 3.04 banding); SBF has no native SSI.

`to_ds_and_auxiliary()` also returns the observables before the receiver's
corrections: `SNR_raw`, `Pseudorange_unsmoothed`, `Pseudorange_raw`,
`Phase_raw` (NaN where MeasExtra is not logged). `store_raw_observables=False`
leaves them out, and `to_ds()` never includes them. A run passes
`processing.params.store_sbf_raw_observables` (default `true`).

!!! note "Observations that are dropped"

    SVID 62 marks a GLONASS satellite whose slot number the receiver does not
    know (RefGuide-4.14.0, Section 4.1.9). It has no RINEX satellite code, and
    several such satellites would share one identifier, so its observations
    are not stored.

### Metadata dataset: `sbf_obs`

The second dataset returned by `to_ds_and_auxiliary()`, under the key
`"sbf_obs"`. It has the same `epoch` and `sid` coordinates as the
observations dataset and carries receiver geometry and quality monitoring
signals. The pipeline stores it under `{group}/metadata/sbf_obs` in the
Icechunk store, in the same commit as the observations of the same files:
a file whose observations are skipped as already stored adds no `sbf_obs`
either, so `sbf_obs` covers exactly the stored observation files. An
`overwrite` run replaces a file's `sbf_obs` together with its observations. Set
`processing.params.store_sbf_metadata: false` to not store it; broadcast
geometry still works, since it uses `sbf_obs` in memory.

**Epoch-level values** (coordinates on `epoch`):

| Variable | SBF Source | CF `units` | Description |
| -------- | ---------- | ---------- | ----------- |
| `pdop` | DOP block | `1` | Position Dilution of Precision |
| `hdop` | DOP block | `1` | Horizontal DOP |
| `vdop` | DOP block | `1` | Vertical DOP |
| `n_sv` | PVTGeodetic | `1` | Number of SVs used in fix |
| `h_accuracy_m` | PVTGeodetic | `m` | 2DRMS horizontal accuracy (~95 %) |
| `v_accuracy_m` | PVTGeodetic | `m` | $2\sigma$ vertical accuracy (~95 %) |
| `pvt_mode` | PVTGeodetic | `1` | Fix type (see flag table) |
| `mean_corr_age_s` | PVTGeodetic | `s` | Age of differential corrections |
| `cpu_load` | ReceiverStatus | `percent` | Receiver CPU utilisation |
| `temperature_c` | ReceiverStatus | `degC` | Receiver temperature |
| `rx_error` | ReceiverStatus | `1` | Error bit-field (see bitmask table) |
| `qual_overall` | QualityInd | `1` | Overall quality score (0-10, -1 unknown) |
| `qual_gnss_main` | QualityInd | `1` | GNSS signals, main antenna |
| `qual_rf_main` | QualityInd | `1` | RF power level, main antenna |
| `qual_cpu` | QualityInd | `1` | CPU headroom |
| `qual_scintillation` | QualityInd | `1` | Scintillation score (firmware $\geq$ 4.15.1) |
| `spoofing_flag` | RFStatus | `1` | 1 = signals may not be authentic |
| `nma_fail_flag` | RFStatus | `1` | 1 = non-authentic navigation message detected (NMA) |

**Per-signal variables** (dimensions: `epoch × sid`):

| Variable | SBF Source | CF `units` | Description |
| -------- | ---------- | ---------- | ----------- |
| `broadcast_theta` | SatVisibility | `rad` | Polar angle $\theta$ (0 = overhead, $\pi/2$ = horizon) |
| `broadcast_phi` | SatVisibility | `rad` | Geographic azimuth $\varphi$ (0 = North, clockwise) |
| `broadcast_angle_source` | SatVisibility | `1` | Orbit data behind $\theta$ and $\varphi$: 1 = almanac, 2 = ephemeris, -1 unknown |
| `rise_set` | SatVisibility | `1` | 1 = rising, 0 = setting |
| `mp_correction_m` | MeasExtra | `m` | Pseudorange multipath correction |
| `smoothing_corr_m` | MeasExtra | `m` | Hatch-filter smoothing correction on pseudorange |
| `code_var` | MeasExtra | `m^2` | Code-phase noise variance |
| `carrier_var` | MeasExtra | `mcycles^2` | Carrier-phase noise variance |
| `lock_time_s` | MeasExtra | `s` | Continuous carrier tracking duration (reset at slip) |
| `cum_loss_cont` | MeasExtra | `1` | Cycle-slip counter (modulo 256; $\Delta \neq 0 \rightarrow$ slip) |
| `car_mp_corr_cycles` | MeasExtra | `cycles` | Carrier-phase multipath correction |
| `cn0_highres_correction` | MeasExtra | `dB-Hz` | CN0HighRes sub-quantisation correction (applied to SNR automatically) |
| `tracking_status_raw` | ChannelStatus | `1` | Tracking status bit field, 2 bits per signal (main antenna) |
| `pvt_status_raw` | ChannelStatus | `1` | PVT usage bit field, 2 bits per signal (main antenna) |

!!! tip "Field decoding formulas"

    All transformations from raw SBF integers to physical units are documented
    in detail, including the signal-dependent $C/N_0$ formula, the 40-bit
    pseudorange reconstruction, and the carrier-phase wavelength conversion:

    [:octicons-arrow-right-24: SBF Field Decoding Reference](sbf-decoding.md)

---

## PVT mode flags

`pvt_mode` uses CF `flag_values` / `flag_meanings` attributes, a fixed set of mutually exclusive values:

<div class="grid" markdown>

| Value | Fix type |
| ----- | -------- |
| `0` | No solution |
| `1` | StandAlone: autonomous from broadcast ephemeris |
| `2` | Differential GNSS (DGNSS) |
| `3` | Fixed location |
| `4` | RTK with fixed ambiguities |
| `5` | RTK with float ambiguities |
| `6` | SBAS-aided |
| `7` | Moving-base RTK with fixed ambiguities |
| `8` | Moving-base RTK with float ambiguities |
| `10` | Precise Point Positioning (PPP) |

!!! info "In the dataset"

    ```python
    meta_ds["pvt_mode"].attrs
    # {
    #     "long_name": "PVT solution mode",
    #     "units": "1",
    #     "flag_values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 10],
    #     "flag_meanings": "no_pvt stand_alone differential fixed_location "
    #                      "rtk_fixed_ambiguities rtk_float_ambiguities sbas_aided "
    #                      "moving_base_rtk_fixed_ambiguities "
    #                      "moving_base_rtk_float_ambiguities ppp",
    #     "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    #     ...
    # }
    ```

</div>

---

## `rx_error` bitmask

`rx_error` is a **bit field**: multiple flags may be set simultaneously.
Test a specific flag with `(rx_error & flag_mask) != 0`.

| Bit mask | Flag meaning |
| -------- | ------------ |
| `8` (bit 3) | Software warning or error |
| `16` (bit 4) | Watchdog expired since power-on |
| `32` (bit 5) | Antenna overcurrent |
| `64` (bit 6) | Output data congestion |
| `256` (bit 8) | Missed external events |
| `512` (bit 9) | CPU load above 90 % |
| `1024` (bit 10) | Invalid configuration |
| `2048` (bit 11) | Out of geofence |

Source: RefGuide-4.14.0, ReceiverStatus, field RxError, p.398.

!!! example "Decoding the bitmask"

    ```python
    import numpy as np

    rx_error = meta_ds["rx_error"].values  # int32 array (epoch,)

    software = (rx_error & 8) != 0  # bit 3
    antenna = (rx_error & 32) != 0  # bit 5
    cpu_overload = (rx_error & 512) != 0  # bit 9

    print(f"Epochs with software errors: {software.sum()}")
    print(f"Epochs with antenna issues:  {antenna.sum()}")
    ```

    `rx_error = 48` means both bit 4 (watchdog) and bit 5 (antenna) are set simultaneously.

---

## Coordinate conventions

### Polar angle θ (theta)

$$\theta = 90^\circ - \text{elevation}$$

`broadcast_theta` and `broadcast_phi` are stored in radians; the tables
below give degrees for readability.

<div class="grid" markdown>

| $\theta$ | Meaning |
| - | ------- |
| $0^\circ$ | Satellite directly overhead (zenith) |
| $90^\circ$ | Satellite at the horizon |

!!! warning "Elevation mask"

    A typical elevation mask of $5^\circ$ to $10^\circ$ corresponds to $\theta < 80^\circ$ to $85^\circ$.
    VOD analyses commonly restrict to $\theta \leq 70^\circ$ (elevation $\geq 20^\circ$) to limit multipath.

</div>

### Azimuth φ (phi)

The stored value is the **geographic (compass) azimuth**:

- $0^\circ$ = North · $90^\circ$ = East · $180^\circ$ = South · $270^\circ$ = West *(clockwise)*
- The SBF `Azimuth` field (steps of $0.01^\circ$), converted to radians

!!! note "Mathematical convention"

    This is **NOT** the spherical-coordinate azimuthal angle, which is measured
    counterclockwise from East. To convert:

    $$\varphi_\text{spherical} = (90^\circ - \varphi_\text{stored}) \bmod 360^\circ$$

---

## CF-convention metadata attributes

Every variable in the metadata dataset carries the CF attributes `long_name` and
`units`, plus `source`, `comment` and `references`, which say where each value comes
from. None carries a `standard_name`: the CF standard name table has no name for these
quantities.

=== "`pdop`"

    ```python
    meta_ds["pdop"].attrs
    # {
    #     "long_name":  "Position Dilution of Precision",
    #     "units":      "1",
    #     "source":     "SBF DOP block (Block 4001), reported by receiver firmware",
    #     "comment":    "PDOP = √(Qxx + Qyy + Qzz), where Q is the position covariance ...",
    #     "references": "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, ...",
    # }
    ```

=== "`broadcast_theta`"

    ```python
    meta_ds["broadcast_theta"].attrs
    # {
    #     "long_name":     "Satellite polar angle reported by the receiver",
    #     "short_name":    "θ_B",
    #     "units":         "rad",
    #     "source":        "SBF SatVisibility block (Block 4012), reported by receiver firmware",
    #     "comment":       "Polar angle from vertical: 0 = overhead, π/2 = horizon. ...",
    #     "references":    "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, ...",
    # }
    ```

=== "`rx_error`"

    ```python
    meta_ds["rx_error"].attrs
    # {
    #     "long_name":     "Receiver error status bit field",
    #     "units":         "1",
    #     "flag_masks":    [8, 16, 32, 64, 256, 512, 1024, 2048],
    #     "flag_meanings": "software watchdog antenna congestion missedevent cpuoverload "
    #                      "invalidconfig outofgeofence",
    #     "source":        "SBF ReceiverStatus block, reported by receiver firmware",
    #     ...
    # }
    ```

=== "`pvt_mode`"

    ```python
    meta_ds["pvt_mode"].attrs
    # {
    #     "long_name": "PVT solution mode",
    #     "units": "1",
    #     "flag_values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 10],
    #     "flag_meanings": "no_pvt stand_alone differential fixed_location "
    #                      "rtk_fixed_ambiguities rtk_float_ambiguities sbas_aided "
    #                      "moving_base_rtk_fixed_ambiguities "
    #                      "moving_base_rtk_float_ambiguities ppp",
    #     "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    #     ...
    # }
    ```

---

## Usage

=== "Single file"

    ```python
    from pathlib import Path
    from canvod.readers.sbf import SbfReader

    reader = SbfReader(fpath=Path("rref001a00.25_"))

    # Inspect header
    print(reader.header.rx_name)  # receiver name from ReceiverSetup
    print(reader.header.rx_version)  # e.g. "4.14.4"
    print(reader.num_epochs)  # number of MeasEpoch blocks
    print(reader.systems)  # ["E", "G", "R", ...]

    # Observations only
    obs_ds = reader.to_ds(keep_data_vars=["SNR", "Pseudorange", "Phase", "Doppler"])

    # Observations and metadata
    obs_ds, aux = reader.to_ds_and_auxiliary()
    meta_ds = aux["sbf_obs"]
    ```

=== "Combined single-pass (pipeline)"

    ```python
    # One binary scan, two datasets
    obs_ds, aux_dict = reader.to_ds_and_auxiliary(
        keep_data_vars=["SNR", "Pseudorange"],
    )
    meta_ds = aux_dict["sbf_obs"]
    ```

=== "Multiple files"

    ```python
    import xarray as xr

    readers = [SbfReader(fpath=f) for f in sorted(sbf_dir.glob("*.sbf"))]

    obs_list, meta_list = [], []
    for r in readers:
        obs, aux = r.to_ds_and_auxiliary(keep_data_vars=["SNR"])
        obs_list.append(obs)
        meta_list.append(aux["sbf_obs"])

    daily_obs = xr.concat(obs_list, dim="epoch", join="outer").sortby("epoch")
    daily_meta = xr.concat(meta_list, dim="epoch", join="outer").sortby("epoch")
    ```

=== "SID filtering + geometry mask"

    ```python
    import numpy as np

    # All GPS signals
    gps = daily_obs.sel(sid=[s for s in daily_obs.sid.values if s.startswith("G")])

    # GPS L1 C/A only
    l1c = daily_obs.sel(
        sid=(daily_obs.system == "G") & (daily_obs.band == "L1") & (daily_obs.code == "C")
    )

    # Polar angle filter: elevation ≥ 20° → theta ≤ 70°
    theta_mask = daily_meta["broadcast_theta"] <= np.deg2rad(70)
    snr_high_el = daily_obs["SNR"].where(theta_mask)
    ```

---

## Combined scan API: `to_ds_and_auxiliary()`

!!! info "Why a combined scan?"

    The pipeline always calls `to_ds_and_auxiliary()`, which reads and parses
    the binary file once and builds both datasets from the same decoded
    observations.

```
┌─────────────────────────────────────────────────┐
│                  SBF file                        │
│  MeasEpoch  PVTGeodetic  DOP  SatVisibility …   │
└───────────────────────┬─────────────────────────┘
                        │ single parser.read() pass,
                        │ blocks grouped by time stamp
        ┌───────────────┴────────────────┐
        ▼                                ▼
  MeasEpoch + MeasExtra         SatVisibility, DOP, PVT,
  (SNR, PR, phase, Doppler)     status, quality (same epoch)
        │                                │
        ▼                                ▼
   obs_ds (epoch × sid)        meta_ds (epoch × sid)
                                   key: "sbf_obs"
```

Return type:

```python
tuple[xr.Dataset, dict[str, xr.Dataset]]
#       obs_ds       {"sbf_obs": meta_ds}
```

---

## Source format identification

Every reader exposes a `source_format` property used by the store and viewer
to identify the data origin. Every reader must define it; `SbfReader`
returns `"sbf"`:

```python
reader = SbfReader(fpath=Path("station.25_"))
reader.source_format  # → "sbf"
```

This value is written as a root-level Zarr attribute (`source_format`) on first
ingest. The store viewer uses it to select the correct display labels and to
detect whether `sbf_obs` metadata is available.

---

## Broadcast ephemeris: SBF as geometry source

The SBF `SatVisibility` block provides satellite azimuth and elevation computed
by the receiver firmware, per satellite either from its almanac or from its
broadcast ephemeris (`broadcast_angle_source`). This makes SBF files a
**self-contained ephemeris source**: no SP3/CLK download needed.

The `SbfBroadcastProvider` (an `EphemerisProvider` implementation) extracts
theta/phi from the `sbf_obs` auxiliary dataset and aligns them to observation
epochs and SIDs. It uses only angles computed from the broadcast ephemeris;
almanac-based angles become NaN, and a file without any ephemeris-based angle
raises an error:

```python
# Automatic in the orchestrator when ephemeris_source = "broadcast"
# and reader_format = "sbf"

# Manual usage:
obs_ds, aux = reader.to_ds_and_auxiliary(keep_data_vars=["SNR"])
sbf_obs = aux["sbf_obs"]

# theta/phi are already in sbf_obs; no coordinate transform needed;
# keep the ephemeris-based angles only, as SbfBroadcastProvider does
from_ephemeris = sbf_obs["broadcast_angle_source"] == 2
theta = sbf_obs["broadcast_theta"].where(from_ephemeris)  # polar angle (rad)
phi = sbf_obs["broadcast_phi"].where(from_ephemeris)  # geographic azimuth (rad)
```

!!! tip "When to use broadcast vs agency final"

    The receiver reports the angles in steps of $0.01^\circ$. Almanac-based angles
    are not used: on the 2025-001 test data they differed from the
    ephemeris-based angles by at most $0.03^\circ$ for GPS and Galileo, but by up to
    $0.26^\circ$ for GLONASS and up to $104^\circ$ for BeiDou. Use
    `ephemeris_source: "broadcast"` for immediate processing without internet.
    See [:octicons-arrow-right-24: Ephemeris Sources](ephemeris-sources.md) for details.

---

## Store Integration

The orchestrator writes the SBF metadata dataset to the Icechunk store
alongside observations, enabling retrospective quality analysis.

```python
from canvod.store import MyIcechunkStore

store = MyIcechunkStore(store_path)

# Write metadata (called automatically by orchestrator)
store.write_sbf_metadata(receiver_name, sbf_obs_ds)

# Read back
meta_ds = store.read_sbf_metadata(receiver_name)

# Check existence
if store.sbf_metadata_exists(receiver_name):
    meta_ds = store.read_sbf_metadata(receiver_name)
```

The metadata is stored at `{receiver}/metadata/sbf_obs` in the Zarr hierarchy.

---

## Satellite catalog enrichment

Combine SBF observations with IGS satellite metadata to add SVN, block type,
TX power, mass, and orbital plane as coordinates:

```python
from canvod.readers.gnss_specs import SatelliteCatalog

catalog = SatelliteCatalog.load()
enriched = catalog.enrich_dataset(obs_ds)

# Now filter by satellite generation
gps3 = enriched.sel(sid=enriched.coords["block"].str.startswith("GPS-III"))
```

See [:octicons-arrow-right-24: Satellite Catalog](satellite-catalog.md) for the full API.

---

## Differences vs. RINEX (`Rnxv3Obs`)

| Aspect | RINEX v3 (`Rnxv3Obs`) | SBF (`SbfReader`) |
| ------ | --------------------- | ----------------- |
| Format | Plain text | Binary |
| File extension | `.rnx` | `.sbf` |
| Header | Structured text | `ReceiverSetup` block |
| Geometry ($\theta$, $\varphi$) | Requires SP3 download | **Embedded in file** |
| Metadata | Header only | Full PVT + quality monitoring |
| `source_format` | `"rinex3"` | `"sbf"` |
| `to_ds()` | ✓ | ✓ |
| `iter_epochs()` | ✓ | ✓ |
| `to_ds_and_auxiliary()` | Returns `{}` aux | Returns `{"sbf_obs": meta_ds}` |
| Broadcast ephemeris | Not supported (needs a navigation file) | Built-in via SatVisibility |
| SID discovery | Header-based (all declared SVs) | Observation-based (tracked SVs only) |
| SNR quantization | ~0.001 dB | 0.25 dB-Hz; 0.03125 dB-Hz with MeasExtra |

---

## Time conversion

SBF time stamps are GPS time: GPS week (`WNc`) and time of week (`TOW`,
milliseconds), with no leap seconds (RefGuide-4.14.0, Section 2.3, p.53).
`SbfReader` keeps them in GPS time, like RINEX files and the orbit and
clock products:

$$\text{GPS time} = \text{GPS\_epoch} + \frac{\text{WN} \times 604800 \times 10^3 + \text{TOW}}{10^3}$$

where GPS epoch = 1980-01-06 00:00:00. A file named for a GPS day starts at
00:00:00 of that day. Stores written by earlier versions hold UTC epochs,
18 s earlier (23:59:42 of the previous day for the first file of a day).

---

## GLONASS FDMA frequencies

GLONASS signals use Frequency Division Multiple Access (FDMA). The center
frequency depends on the frequency number $K = \text{FreqNr} - 8$
(RefGuide-4.14.0: $K \in \{-7, \dots, +13\}$; RefGuide-4.15.1: $K \in \{-7, \dots, +6\}$):

$$f_{L1} = 1602 \text{ MHz} + K \times 0.5625 \text{ MHz}$$
$$f_{L2} = 1246 \text{ MHz} + K \times 0.4375 \text{ MHz}$$

`SbfReader` takes FreqNr from bits 3-7 of the `ObsInfo` field of each
MeasEpoch Type1 sub-block (RefGuide-4.14.0, p.262), so every GLONASS
observation carries its own frequency number, from the first epoch of the
file on. Type2 sub-blocks take it from their Type1 sub-block.

---

## References

- Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide
- Septentrio AsteRx SB3 ProBase Firmware v4.15.1 Reference Guide
- CF Conventions v1.11: `flag_masks`, `flag_meanings`, `flag_values`
- RINEX 3.04 signal nomenclature (used verbatim for SID strings)
- [:octicons-arrow-right-24: SBF Field Decoding Reference](sbf-decoding.md): all formulas with firmware page citations
