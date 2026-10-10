# Product registry

The product registry provides declarative configuration for 23 final and rapid SP3/CLK products from 14 analysis centers (agency codes). Products are defined in TOML; no hardcoded URLs in the processing code. Every product was checked against the file listings of ESA GSSC and NASA CDDIS (2025-001 and 2026-244, checked 2026-10-05); `just check-products` repeats the check (see [Checking the registry](#checking-the-registry)).

---

## Product types

<div class="grid cards" markdown>

-   :fontawesome-solid-star: &nbsp; **Final**

    ---

    Latency **14–21 days** · Accuracy **cm-level**

    Highest quality. Use for scientific research, reprocessing campaigns,
    and publication-quality VOD products.

-   :fontawesome-solid-bolt: &nbsp; **Rapid**

    ---

    Latency **17–24 hours** · Accuracy **near-final (cm-level)**

    Available the following day. Use for near-real-time processing when
    final products have not yet been released.

</div>

| Type | Latency | Orbit accuracy | Clock accuracy |
|------|---------|---------------|----------------|
| Final | 14–21 d | < 2.5 cm | < 75 ps |
| Rapid | 17–24 h | < 2.5 cm | < 75 ps |

Ultra-rapid, real-time and near-real-time products are not supported: they
are issued several times a day, are partly predicted, and their file names
carry the issue hour. The settings reject `product_type: ultra-rapid`.

---

## Available products

Systems: G GPS, R GLONASS, E Galileo, C BeiDou, J QZSS, read from the SP3
header of 2026-09-01. A run drops the observations of satellites the product
has no orbits for (warning `sids_dropped_no_ephemeris`, once per file), so those
signals get no VOD: choose a product that covers the systems of your
[signal selection](../../guides/configuration.md), or narrow the selection.

| Code | Agency | Final | Rapid |
|------|--------|-------|-------|
| COD | Center for Orbit Determination in Europe | GRECJ | GRE |
| EMR | Natural Resources Canada | G | GR |
| ESA | European Space Agency | GRECJ | GR |
| GFZ | GeoForschungsZentrum Potsdam | GRE | GRECJ |
| GRG | CNES | GEC | GEC |
| IAC | Information-Analytical Centre | GRECJ | – |
| IGS | International GNSS Service | G (NASA CDDIS only) | G |
| JAX | JAXA (multi-GNSS) | GRECJ | – |
| JGX | JAXA | GRE | GRE |
| JPL | Jet Propulsion Laboratory | GE | GE |
| MIT | Massachusetts Institute of Technology | GE | – |
| NGS | National Geodetic Survey | G, no clocks | – |
| SIO | Scripps Institution of Oceanography | G, no clocks | G, no clocks |
| USN | US Naval Observatory | – | G |

`canvod.auxiliary.list_products()` lists them; the registry is the truth. The
default, COD final, covers all five systems. Products without clock files need
`fetch_clock: false`; a run, and `canvodpy config validate`, stops before any
download if the configured product does not exist or has no clocks while
`fetch_clock` is true, and names the closest products.

!!! note "Several samplings per product"
    Agencies have changed the sampling of their files over the years (for example ESA
    rapid: 15 min SP3 and 5 min CLK in 2025, 5 min SP3 and 30 s CLK in 2026).
    The registry lists every sampling a product has been published with, and
    the readers try them in that order, locally and then on each server. The
    sampling of the file used is recorded in the `sampling_rate` attribute
    of the orbit dataset.

!!! tip "Servers and fallback"
    Products are downloaded from ESA GSSC (no account needed). NASA CDDIS is a
    fallback, tried when ESA fails, once `credentials.nasa_earthdata_acc_mail`
    holds the email of a free NASA Earthdata account. Products that only NASA
    CDDIS hosts need that account.

---

## Usage

=== "Look up a product"

    ```python
    from canvod.auxiliary import get_product_spec

    spec = get_product_spec("COD", "final")
    spec.prefix  # "COD0MGXFIN"
    spec.sp3_samplings  # ["05M"], tried in this order
    spec.clk_samplings  # ["30S"]; [] if the product has no clocks
    spec.systems  # "GRECJ"
    spec.sp3_filenames("2025001")  # ["COD0MGXFIN_20250010000_01D_05M_ORB.SP3"]
    [s.url for s in spec.ftp_servers]  # ESA first, then NASA CDDIS
    ```

=== "In a run"

    Runs pick the product from the settings; no manual lookup is needed:

    ```yaml
    processing:
      aux_data:
        agency: COD
        product_type: final
        fetch_clock: true   # false: skip CLK, which VOD does not use
    ```

    To add satellite geometry to a dataset in your own code, use an ephemeris
    provider (see [canvod-auxiliary](overview.md)).

---

## Registry format

Products are declared in
`packages/canvod-auxiliary/src/canvod/auxiliary/products/products.toml`, one
`[[products]]` table each, with its servers in priority order:

```toml
[[products]]
agency = "COD"
type = "final"
prefix = "COD0MGXFIN"
sp3_sampling = ["05M"]
clk_sampling = ["30S"]
systems = "GRECJ"
description = "CODE final multi-GNSS"
ftp_path = "/gnss/products/{gps_week}/{file}"

[[products.ftp_servers]]
url = "ftp://gssc.esa.int"
priority = 1
description = "ESA GSSC"

[[products.ftp_servers]]
url = "ftps://gdc.cddis.eosdis.nasa.gov"
priority = 2
requires_auth = true
description = "NASA CDDIS"
```

`type` is `final` or `rapid`. Every file covers one day (`01D`).

---

## Checking the registry

```bash
just check-products                    # 2025-001 and the day three weeks ago
just check-products 2025001 2026244    # chosen days (YYYYDOY)
```

The recipe lists each server's GPS-week directory once per day and looks up
every product's SP3 file, and CLK file if it has clocks, under each of its
samplings. It prints the file found per product and day, or, for a missing
product, the files of that product the servers do have, and exits with 1 if
any product is missing. NASA CDDIS is checked when the settings hold
`credentials.nasa_earthdata_acc_mail`; otherwise products hosted only there
are reported as skipped. Run it after editing `products.toml`, and from time
to time: agencies rename products, change samplings, and stop publishing.
