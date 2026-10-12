---
title: Satellite Catalog (IGS SINEX)
description: Time-aware GNSS satellite metadata from the IGS igs_satellite_metadata.snx file
---

# Satellite Catalog — IGS SINEX Metadata

## Why satellite metadata matters for GNSS-T

GNSS-Transmissometry derives vegetation properties from the **attenuation** of
satellite signals passing through a canopy. Several satellite-level properties
directly affect signal interpretation:

- **Transmit power (TX)** — different satellite generations broadcast at different
  power levels (e.g. GPS-IIF: 240 W, GPS-III: 370 W). When computing transmittance
  as the ratio of canopy-to-reference SNR, the absolute power cancels — but mixed
  constellations and satellite replacements can introduce systematic biases if not
  accounted for.
- **PRN reassignments** — a PRN code (e.g. `G01`) is not permanently bound to one
  satellite vehicle. When a satellite is decommissioned and its PRN reassigned to a
  new vehicle, the TX power, antenna pattern, and orbital characteristics change.
  Long time series that span a reassignment must be flagged to avoid false trends.
- **Orbital plane and slot** — the satellite's position in the constellation
  determines its sky track over the receiver site, which affects the polar angle
  distribution and therefore the VOD sampling geometry.

The IGS SINEX catalog provides all of this information in a single, authoritative,
machine-readable file — enabling canvodpy to track these properties automatically.

## Overview

The `SatelliteCatalog` class parses the IGS `igs_satellite_metadata.snx` SINEX file —
a single authoritative source of satellite metadata maintained by the [IGS](https://gssc.esa.int/navipedia/index.php/International_GNSS_Service_(IGS)){:target="_blank"} (updated
every 2-4 weeks by [DLR](https://gssc.esa.int/navipedia/index.php/GNSS_Satellite_Orbit_Determination){:target="_blank"}). It provides time-aware queries for all GNSS constellations:
GPS, GLONASS, Galileo, BeiDou, QZSS, IRNSS, and SBAS.

!!! tip "Offline-first design"

    `SatelliteCatalog` **never fails** without internet. A bundled fallback copy
    ships with the package. Fresh copies are downloaded automatically when online
    and cached locally.

---

## What's in the SINEX file?

The file contains seven data blocks covering ~290 satellite vehicles:

| SINEX Block | Data | Example |
|-------------|------|---------|
| `SATELLITE/IDENTIFIER` | SVN, COSPAR ID, NORAD catalog number, block type, launch date | `G063`, `2014-068A`, `GPS-IIF` |
| `SATELLITE/PRN` | PRN ↔ SVN assignments with validity periods | G01 → G063 from 2014-250 to open |
| `SATELLITE/TX_POWER` | Transmit power (Watts) per SVN | G063: 240 W |
| `SATELLITE/MASS` | Satellite mass (kg) per SVN | G063: 1633.0 kg |
| `SATELLITE/FREQUENCY_CHANNEL` | GLONASS FDMA channel numbers per SVN | R730: channel 1 |
| `SATELLITE/PLANE` | Orbital plane and slot assignments | G063: plane B, slot 2 |

---

## Loading the Catalog

### Discovery chain

`SatelliteCatalog.load()` searches for the file in this order:

```
1. Explicit search_dirs (e.g. config aux_data_dir)
2. ~/.cache/canvod/
3. Download from IGS (if online and cache is stale)
4. Bundled fallback (always works, ships with package)
```

=== "Default (auto-download)"

    ```python
    from canvod.readers.gnss_specs import SatelliteCatalog

    catalog = SatelliteCatalog.load()
    ```

=== "Offline only"

    ```python
    catalog = SatelliteCatalog.load(allow_download=False)
    ```

=== "From specific file"

    ```python
    catalog = SatelliteCatalog.from_file("/path/to/igs_satellite_metadata.snx")
    ```

=== "Custom cache directory"

    ```python
    catalog = SatelliteCatalog.load(
        search_dirs=[Path("/data/aux/")],
        max_age_days=14,
    )
    ```

!!! info "Placing the file manually"

    Drop a fresh copy of `igs_satellite_metadata.snx` into `~/.cache/canvod/`
    or your project's `aux_data_dir`. The catalog will find it automatically.

---

## Querying

All time-varying queries take an `on_date` parameter to resolve validity periods.

### PRN ↔ SVN mapping

PRN codes (e.g. `G01`) are **not permanent** — they can be reassigned to different
satellite vehicles over time. The catalog tracks the full assignment history.

```python
from datetime import date

catalog = SatelliteCatalog.load()

# What satellite vehicle is behind G01 today?
svn = catalog.prn_to_svn("G01", date(2025, 6, 17))  # → "G063"

# Reverse lookup
prn = catalog.svn_to_prn("G063", date(2025, 6, 17))  # → "G01"

# Full assignment history for a PRN
history = catalog.prn_history("G01")
for assignment in history:
    print(f"  {assignment.svn}: {assignment.start} → {assignment.end or 'active'}")
```

### Reassignment detection

```python
# Were there any PRN reassignments in my processing window?
changes = catalog.reassignments_in_range("G01", date(2020, 1, 1), date(2025, 12, 31))
for r in changes:
    print(f"  {r.prn}: {r.old_svn} → {r.new_svn} on {r.new_start}")
```

!!! warning "Why reassignments matter"

    If a PRN is reassigned during your observation period, the satellite
    behind that PRN changed — with different transmit power, antenna pattern,
    and orbital characteristics. Time series continuity assumptions break.

### Active PRNs per constellation

```python
# All GPS satellites active on a given date
gps_prns = catalog.active_prns("G", date(2025, 1, 1))  # → ["G01", "G02", ...]

# Galileo
gal_prns = catalog.active_prns("E", date(2025, 1, 1))  # → ["E01", "E02", ...]
```

### Satellite metadata

```python
# Block type (satellite generation)
block = catalog.satellite_block("G063")  # → "GPS-IIF"

# Transmit power
power = catalog.tx_power("G063", date(2025, 1, 1))  # → 240 (Watts)

# Mass
mass = catalog.mass("G063", date(2025, 1, 1))  # → 1633.0 (kg)

# GLONASS frequency channel
channel = catalog.glonass_channel("R730", date(2025, 1, 1))  # → 1

# Orbital plane and slot
plane, slot = catalog.plane_and_slot("G063", date(2025, 1, 1))  # → ("B", "2")
```

### Combined metadata lookup

```python
# Get everything for a PRN on a date
meta = catalog.get_prn_metadata("G01", date(2025, 1, 1))
# → {
#     "prn": "G01", "svn": "G063", "block": "GPS-IIF",
#     "cospar_id": "2014-068A", "satcat": 40294,
#     "tx_power_watts": 240, "mass_kg": 1633.0,
#     "plane": "B", "slot": "2", "glonass_channel": None,
#     "comment": "Launched 2014-10-29"
# }
```

---

## Polars DataFrame Export

The catalog can be exported as a Polars DataFrame for interactive exploration
in marimo notebooks.

=== "Snapshot (one date)"

    ```python
    df = catalog.to_dataframe(on_date=date(2025, 1, 1))
    # Columns: prn, svn, constellation, block, cospar_id, satcat,
    #          tx_power_watts, mass_kg, plane, slot, glonass_channel, launch
    ```

=== "Full history"

    ```python
    df = catalog.to_dataframe()
    # Columns: prn, svn, constellation, block, start, end
    # One row per PRN assignment (all time periods)
    ```

!!! example "Quick analysis in marimo"

    ```python
    import marimo as mo

    df = catalog.to_dataframe(on_date=date(2025, 1, 1))

    # TX power by constellation
    mo.ui.table(
        df.group_by("constellation").agg(
            pl.col("tx_power_watts").mean().alias("mean_power_W"),
            pl.col("tx_power_watts").min().alias("min_power_W"),
            pl.col("tx_power_watts").max().alias("max_power_W"),
            pl.len().alias("count"),
        )
    )
    ```

---

## Dataset Enrichment

`enrich_dataset()` adds satellite metadata as `sid`-level coordinates on an
existing xarray Dataset. This attaches SVN, block type, TX power, mass, plane,
and slot to every signal identifier.

```python
catalog = SatelliteCatalog.load()

# ds has dims (epoch, sid) from any reader
enriched = catalog.enrich_dataset(ds, on_date=date(2025, 1, 1))

# New coordinates on the sid dimension:
enriched.coords["svn"]             # "G063", "E210", ...
enriched.coords["block"]           # "GPS-IIF", "GAL-FOC", ...
enriched.coords["tx_power_watts"]  # 240.0, 265.0, ...
enriched.coords["mass_kg"]         # 1633.0, 733.0, ...
enriched.coords["plane"]           # "B", "A", ...
enriched.coords["slot"]            # "2", "5", ...
```

!!! info "Date inference"

    If `on_date` is not provided, it is inferred from the first epoch in the
    dataset. Unknown SIDs (not in the catalog) get empty strings / NaN values.

### Use case: filter by satellite generation

```python
# Select only GPS-III satellites (higher TX power)
gps3_mask = enriched.coords["block"].str.startswith("GPS-III")
gps3_data = enriched.sel(sid=gps3_mask)
```

---

## Integration with Constellations

Each constellation class has an `update_svs_from_catalog()` method that
replaces the static SV list with the actual active PRNs from the catalog:

```python
from canvod.readers.gnss_specs.constellations import GPS

gps = GPS()
print(len(gps.svs))  # 32 (static default)

gps.update_svs_from_catalog(on_date=date(2025, 1, 1))
print(len(gps.svs))  # actual active PRNs on that date
```

---

## Summary of Catalog Contents

```python
catalog = SatelliteCatalog.load()
print(catalog.summary())
# {
#     "total_svns": 291,
#     "constellations": {"GPS": 78, "GLONASS": 67, "Galileo": 36, ...},
#     "prn_assignments": 487,
#     "tx_power_records": 312,
#     "mass_records": 285,
#     "frequency_channels": 67,
#     "plane_slots": 410,
# }
```

---

## Data Classes Reference

| Class | Fields | Description |
|-------|--------|-------------|
| `SatelliteIdentity` | svn, cospar_id, satcat, block, comment | Static satellite info |
| `PrnAssignment` | svn, prn, start, end | PRN ↔ SVN with validity period |
| `TxPowerRecord` | svn, power_watts, start, end, comment | TX power with validity |
| `MassRecord` | svn, mass_kg, start, end, comment | Mass with validity |
| `FrequencyChannel` | svn, channel, start, end, comment | GLONASS FDMA channel |
| `PlaneSlot` | svn, plane, slot, start, end, comment | Orbital plane and slot |
| `Reassignment` | prn, old_svn, new_svn, old_end, new_start | PRN reassignment event |

---

## References

- [IGS Satellite Metadata SINEX](https://files.igs.org/pub/station/general/igs_satellite_metadata.snx)
- Steigenberger, P., et al. (2023). "GNSS satellite transmit power and its impact on orbit determination." *Journal of Geodesy*, 97(4).
- IGS SINEX format specification v2.02

---

!!! example "Try it"
    [07 · Satellite Catalog](../../notebooks/_build/07_satellite_catalog.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/07_satellite_catalog.py)
