# SBF Reader — Septentrio Binary Format

## Overview

The Septentrio Binary Format (SBF) is the proprietary high-rate binary telemetry
output of Septentrio GNSS receivers (AsteRx SB3, mosaic-X5, PolaRx, etc.).
`SbfReader` in `canvod-readers` decodes SBF streams and produces two complementary
`xarray.Dataset` objects from a **single file scan**.

!!! tip "No ephemeris download needed"

    The SBF reader differs from `Rnxv3Obs` (RINEX) in one fundamental respect:
    **satellite geometry is embedded in the binary stream**.
    No SP3 ephemeris download is required for quick-look analysis —
    the receiver's own navigation solution provides azimuth and polar angle
    for every tracked signal.

---

## Decoded SBF Blocks

<div class="grid cards" markdown>

-   :fontawesome-solid-tower-broadcast: &nbsp; **ReceiverSetup**

    ---

    Receiver serial number, firmware version, station name.
    Populates global dataset attributes.

-   :fontawesome-solid-clock: &nbsp; **ReceiverTime**

    ---

    GPS↔UTC leap-second offset ΔLS.
    Used to convert GPS Time (WN + TOW) to UTC.

-   :fontawesome-solid-satellite: &nbsp; **ChannelStatus**

    ---

    GLONASS FDMA frequency-slot cache (`SVID → FreqNr`).
    Pre-scanned before MeasEpoch decoding.

-   :fontawesome-solid-signal: &nbsp; **MeasEpoch**

    ---

    Per-epoch GNSS observations: C/N₀ (SNR), pseudorange, carrier phase, Doppler.
    Primary source for the observations dataset.

-   :fontawesome-solid-map-pin: &nbsp; **PVTGeodetic**

    ---

    Navigation solution: position fix, fix type, number of SVs used,
    horizontal and vertical accuracy estimates, age of corrections.

-   :fontawesome-solid-chart-bar: &nbsp; **DOP**

    ---

    Dilution of Precision — PDOP, HDOP, VDOP per epoch.

-   :fontawesome-solid-microchip: &nbsp; **ReceiverStatus**

    ---

    CPU load, board temperature, error bit-field `rx_error`.

-   :fontawesome-solid-compass: &nbsp; **SatVisibility**

    ---

    Per-satellite azimuth and elevation for each tracked SV.
    Converted to geographic azimuth φ and polar angle θ.

-   :fontawesome-solid-wave-square: &nbsp; **MeasExtra**

    ---

    Extra per-signal quality: multipath path-delay correction,
    code-phase and carrier-phase noise variance.

</div>

---

## Output Datasets

### Observations dataset — `to_ds()`

Identical structure to `Rnxv3Obs.to_ds()` — a drop-in replacement:

| Property | Value |
| -------- | ----- |
| Dimensions | `(epoch, sid)` |
| `epoch` coordinate | `datetime64[ns]`, UTC |
| `sid` coordinate | `"SV\|Band\|Code"` string (e.g. `G07\|L1\|C`) |
| Data variables | `SNR` (always), `Pseudorange`, `Phase`, `Doppler` (on request) |
| Validation | Passes `validate_dataset()` |

### Metadata dataset — `to_metadata_ds()`

A second dataset carrying receiver geometry and quality monitoring signals, stored
under `{receiver}/metadata/sbf_obs` in the Icechunk store.

**Epoch-level scalar variables** (dimension: `epoch`):

| Variable | SBF Source | CF `units` | Description |
| -------- | ---------- | ---------- | ----------- |
| `pdop` | DOP block | `1` | Position Dilution of Precision |
| `hdop` | DOP block | `1` | Horizontal DOP |
| `vdop` | DOP block | `1` | Vertical DOP |
| `n_sv` | PVTGeodetic | `1` | Number of SVs used in fix |
| `h_accuracy` | PVTGeodetic | `m` | 2DRMS horizontal accuracy (~95 %) |
| `v_accuracy` | PVTGeodetic | `m` | 2σ vertical accuracy (~95 %) |
| `pvt_mode` | PVTGeodetic | `1` | Fix type (see flag table) |
| `mean_corr_age` | PVTGeodetic | `s` | Age of differential corrections |
| `cpu_load` | ReceiverStatus | `percent` | Receiver CPU utilisation |
| `temperature` | ReceiverStatus | `degC` | Board temperature |
| `rx_error` | ReceiverStatus | `1` | Error bit-field (see bitmask table) |

**Per-signal variables** (dimensions: `epoch × sid`):

| Variable | SBF Source | CF `units` | Description |
| -------- | ---------- | ---------- | ----------- |
| `broadcast_theta` | SatVisibility | `rad` | Polar angle θ (0 = overhead, π/2 = horizon) |
| `broadcast_phi` | SatVisibility | `rad` | Geographic azimuth φ (0 = North, clockwise) |
| `rise_set` | SatVisibility | `1` | 1 = rising, 0 = setting |
| `mp_correction_m` | MeasExtra | `m` | Pseudorange multipath correction |
| `smoothing_corr_m` | MeasExtra | `m` | Hatch-filter smoothing correction on pseudorange |
| `code_var` | MeasExtra | `m^2` | Code-phase noise variance |
| `carrier_var` | MeasExtra | `mcycles^2` | Carrier-phase noise variance |
| `lock_time_s` | MeasExtra | `s` | Continuous carrier tracking duration (reset at slip) |
| `cum_loss_cont` | MeasExtra | `1` | Cycle-slip counter (modulo 256; Δ ≠ 0 → slip) |
| `car_mp_corr_cycles` | MeasExtra | `cycles` | Carrier-phase multipath correction |
| `cn0_highres_correction` | MeasExtra | `dB-Hz` | CN0HighRes sub-quantisation correction (applied to SNR automatically) |

!!! tip "Field decoding formulas"

    All transformations from raw SBF integers to physical units are documented
    in detail — including the signal-dependent C/N₀ formula, the 40-bit
    pseudorange reconstruction, and the carrier-phase wavelength conversion:

    [:octicons-arrow-right-24: SBF Field Decoding Reference](sbf-decoding.md)

---

## PVT mode flags

`pvt_mode` uses CF `flag_values` / `flag_meanings` attributes — a fixed set of mutually exclusive values:

<div class="grid" markdown>

| Value | Fix type |
| ----- | -------- |
| `0` | No solution |
| `1` | StandAlone — autonomous from broadcast ephemeris |
| `2` | Differential GNSS (DGNSS) |
| `3` | Fixed RTK |
| `4` | Float RTK |
| `5` | SBAS-aided |
| `6` | MovingBase |
| `10` | Precise Point Positioning (PPP) |

!!! info "In the dataset"

    ```python
    meta_ds["pvt_mode"].attrs
    # {
    #     "long_name": "PVT fix mode",
    #     "flag_values": [0, 1, 2, 3, 4, 5, 6, 10],
    #     "flag_meanings": "no_solution standalone dgnss fixed_rtk float_rtk sbas moving_base ppp",
    #     "units": "1",
    # }
    ```

</div>

---

## `rx_error` bitmask

`rx_error` is a **bit field** — multiple flags may be set simultaneously.
Test a specific flag with `(rx_error & flag_mask) != 0`.

| Bit mask | Flag meaning |
| -------- | ------------ |
| `8` (bit 3) | Software watchdog reset |
| `16` (bit 4) | Antenna problem detected |
| `32` (bit 5) | Receiver congestion |
| `64` (bit 6) | CPU overload |
| `512` (bit 9) | Invalid configuration |
| `1024` (bit 10) | Out of geofence |
| `2048` (bit 11) | Reserved |

!!! example "Decoding the bitmask"

    ```python
    import numpy as np

    rx_error = meta_ds["rx_error"].values          # int16 array (epoch,)

    sw_watchdog  = (rx_error & 8)   != 0            # bit 3
    antenna_prob = (rx_error & 16)  != 0            # bit 4
    cpu_overload = (rx_error & 64)  != 0            # bit 6

    print(f"Epochs with software errors: {sw_watchdog.sum()}")
    print(f"Epochs with antenna issues:  {antenna_prob.sum()}")
    ```

    `rx_error = 48` means both bit 4 (antenna) and bit 5 (congestion) are set simultaneously.

---

## Coordinate Conventions

### Polar angle θ (theta)

$$\theta = 90° - \text{elevation}$$

<div class="grid" markdown>

| θ | Meaning |
| - | ------- |
| `0°` | Satellite directly overhead (zenith) |
| `90°` | Satellite at the horizon |

!!! warning "Elevation mask"

    A typical 5–10° elevation mask corresponds to `θ < 80–85°`.
    VOD analyses commonly restrict to `θ ≤ 70°` (elevation ≥ 20°) to limit multipath.

</div>

### Azimuth φ (phi)

The stored value is the **geographic (compass) azimuth**:

- 0° = North · 90° = East · 180° = South · 270° = West *(clockwise)*
- This is the raw SBF `Azimuth` field scaled by 0.01°

!!! note "Mathematical convention"

    This is **NOT** the spherical-coordinate azimuthal angle, which is measured
    counterclockwise from East. To convert:

    $$\phi_\text{spherical} = (90° - \phi_\text{stored}) \bmod 360°$$

---

## CF-Convention Metadata Attributes

Every variable in the metadata dataset carries full CF-convention attributes for NetCDF
interoperability and scientific reproducibility.

=== "pdop"

    ```python
    meta_ds["pdop"].attrs
    # {
    #     "long_name":     "Position Dilution of Precision",
    #     "standard_name": "position_dilution_of_precision",
    #     "units":         "1",
    #     "source":        "SBF DOP block",
    #     "comment":       "PDOP = sqrt(σ_x² + σ_y² + σ_z²) / σ_R ...",
    #     "references":    "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 ...",
    # }
    ```

=== "theta"

    ```python
    meta_ds["theta"].attrs
    # {
    #     "long_name":     "Polar angle",
    #     "standard_name": "polar_angle",
    #     "units":         "degrees",
    #     "source":        "SBF SatVisibility block",
    #     "comment":       "theta = 90 - elevation; 0 = overhead, 90 = horizon",
    # }
    ```

=== "rx_error"

    ```python
    meta_ds["rx_error"].attrs
    # {
    #     "long_name":     "Receiver error status bit field",
    #     "units":         "1",
    #     "flag_masks":    [8, 16, 32, 64, 512, 1024, 2048],
    #     "flag_meanings": "software_watchdog antenna congestion cpu_overload ...",
    #     "source":        "SBF ReceiverStatus block",
    # }
    ```

=== "pvt_mode"

    ```python
    meta_ds["pvt_mode"].attrs
    # {
    #     "long_name":     "PVT fix mode",
    #     "units":         "1",
    #     "flag_values":   [0, 1, 2, 3, 4, 5, 6, 10],
    #     "flag_meanings": "no_solution standalone dgnss fixed_rtk float_rtk sbas moving_base ppp",
    #     "source":        "SBF PVTGeodetic block",
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
    print(reader.header.rx_name)       # e.g. "AsteRx SB3"
    print(reader.header.rx_version)    # e.g. "4.14.4"
    print(reader.num_epochs)           # number of MeasEpoch blocks
    print(reader.systems)              # ["E", "G", "R", ...]

    # Observations only
    obs_ds = reader.to_ds(
        keep_data_vars=["SNR", "Pseudorange", "Phase", "Doppler"],
        write_global_attrs=True,
    )

    # Metadata only
    meta_ds = reader.to_metadata_ds()
    ```

=== "Combined single-pass (pipeline)"

    ```python
    # Recommended: one binary scan, two datasets
    obs_ds, aux_dict = reader.to_ds_and_auxiliary(
        keep_data_vars=["SNR", "Pseudorange"],
        write_global_attrs=True,
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

    daily_obs  = xr.concat(obs_list,  dim="epoch", join="outer").sortby("epoch")
    daily_meta = xr.concat(meta_list, dim="epoch", join="outer").sortby("epoch")
    ```

=== "SID filtering + geometry mask"

    ```python
    # All GPS signals
    gps = daily_obs.sel(sid=[s for s in daily_obs.sid.values if s.startswith("G")])

    # L1C band only
    l1c = daily_obs.sel(sid=[s for s in daily_obs.sid.values if "|L1C|" in s])

    # Polar angle filter: elevation ≥ 20° → theta ≤ 70°
    theta_mask = daily_meta["theta"] <= 70
    snr_high_el = daily_obs["SNR"].where(theta_mask)
    ```

---

## Combined Scan API — `to_ds_and_auxiliary()`

!!! info "Why a combined scan?"

    The pipeline always calls `to_ds_and_auxiliary()` rather than making two
    separate calls. This avoids reading and parsing the binary file twice.

```
┌─────────────────────────────────────────────────┐
│                  SBF file                        │
│  MeasEpoch  PVTGeodetic  DOP  SatVisibility …   │
└───────────────────────┬─────────────────────────┘
                        │ single parser.read() pass
        ┌───────────────┴────────────────┐
        ▼                                ▼
  obs accumulators              metadata accumulators
  (SNR, PR, phase, Doppler)     (DOP, PVT, theta, phi, …)
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

## Source Format Identification

Every reader exposes a `source_format` property used by the store and viewer
to identify the data origin. The base class returns `"rinex3"` by default;
`SbfReader` overrides it:

```python
reader = SbfReader(fpath=Path("station.25_"))
reader.source_format  # → "sbf"
```

This value is written as a root-level Zarr attribute (`source_format`) on first
ingest. The store viewer uses it to select the correct display labels and to
detect whether `sbf_obs` metadata is available.

---

## Broadcast Ephemeris: SBF as Geometry Source

The SBF `SatVisibility` block provides satellite azimuth and elevation computed
by the receiver firmware from broadcast navigation messages. This makes SBF files
a **self-contained ephemeris source** — no SP3/CLK download needed.

The `SbfBroadcastProvider` (an `EphemerisProvider` implementation) extracts
theta/phi from the `sbf_obs` auxiliary dataset and aligns them to observation
epochs and SIDs:

```python
# Automatic in the orchestrator when ephemeris_source = "broadcast"
# and reader_format = "sbf"

# Manual usage:
obs_ds, aux = reader.to_ds_and_auxiliary(keep_data_vars=["SNR"])
sbf_obs = aux["sbf_obs"]

# theta/phi are already in sbf_obs — no coordinate transform needed
theta = sbf_obs["theta"]  # polar angle (degrees)
phi = sbf_obs["phi"]      # geographic azimuth (degrees)
```

!!! tip "When to use broadcast vs agency final"

    For VOD applications, broadcast ephemeris accuracy (~1-2 m orbit) produces
    angular errors six orders of magnitude below measurement noise. Use
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

## Satellite Catalog Enrichment

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
| Geometry (θ, φ) | Requires SP3 download | **Embedded in file** |
| Metadata | Header only | Full PVT + quality monitoring |
| `source_format` | `"rinex3"` | `"sbf"` |
| `to_ds()` | ✓ | ✓ |
| `iter_epochs()` | ✓ | ✓ |
| `to_metadata_ds()` | — | ✓ |
| `to_ds_and_auxiliary()` | Returns `{}` aux | Returns `{"sbf_obs": meta_ds}` |
| Broadcast ephemeris | Requires `.YYp` NAV file (planned) | Built-in via SatVisibility |
| SID discovery | Header-based (all declared SVs) | Observation-based (tracked SVs only) |
| SNR quantization | ~0.001 dB | 0.25 dB (hardware) |

---

## Time Conversion

SBF timestamps use GPS Time (GPS Week + Time of Week in milliseconds).
`SbfReader` converts GPS Time to UTC using the leap-second offset ΔLS from
the `ReceiverTime` block.

$$\text{UTC} = \text{GPS\_epoch} + \frac{\text{WN} \times 604800 \times 10^3 + \text{TOW}}{10^3} - \Delta_\text{LS}$$

Where GPS epoch = 1980-01-06 00:00:00 UTC and ΔLS = 18 s (current, valid
from 2017-01-01). The ΔLS value is updated dynamically if a `ReceiverTime`
block is present.

---

## GLONASS FDMA Frequencies

GLONASS signals use Frequency Division Multiple Access (FDMA). The centre
frequency depends on the frequency slot number (FreqNr, K ∈ {−7, …, +6}):

$$f_{L1} = 1602 \text{ MHz} + K \times 0.5625 \text{ MHz}$$
$$f_{L2} = 1246 \text{ MHz} + K \times 0.4375 \text{ MHz}$$

`SbfReader` pre-scans all `ChannelStatus` blocks to build a complete
`SVID → FreqNr` cache before iterating `MeasEpoch` blocks. This ensures
accurate frequency assignments even for GLONASS epochs near the start of
the file, before the receiver has broadcast the ChannelStatus block.

---

## References

- Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide
- Septentrio AsteRx SB3 ProBase Firmware v4.15.1 Reference Guide
- IS-GPS-200 Rev. N, §20.3.3.5.2.4 (GPS time conversion)
- CF Conventions v1.11 — `flag_masks`, `flag_meanings`, `flag_values`
- RINEX 3.04 signal nomenclature (used verbatim for SID strings)
- [:octicons-arrow-right-24: SBF Field Decoding Reference](sbf-decoding.md) — all formulas with firmware page citations

---

!!! example "Try it"
    [06 · SBF Reading](../../notebooks/_build/06_sbf_reading.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/06_sbf_reading.py)
