# canvod-auxiliary

## Purpose

The `canvod-auxiliary` package provides auxiliary data management for [GNSS Transmissometry](https://gssc.esa.int/navipedia/index.php/GNSS){:target="_blank"} (GNSS-T) analysis. It handles downloading, parsing, preprocessing, and interpolating [SP3 ephemerides](https://igs.org/formats-and-standards/){:target="_blank"} to augment RINEX observation data with precise satellite positions. By default it also fetches CLK [clock corrections](https://gssc.esa.int/navipedia/index.php/Precise_GNSS_Satellite_Coordinates_Computation){:target="_blank"}, though these are unused by the VOD formula and can be skipped via `aux_data.fetch_clock: false`.

---

## The dimension alignment problem

GNSS-T analysis requires combining two data sources with fundamentally different indexing:

<div class="grid" markdown>

!!! abstract "RINEX Observations"

    - High temporal resolution: 30 s, 15 s, or sub-second
    - Signal-level indexing by SID: `"G01|L1|C"`
    - Dimensions: `(epoch: 2880, sid: 384)`

!!! abstract "SP3 / CLK Auxiliary"

    - Low temporal resolution: 5–15 min
    - Satellite-level indexing by SV: `"G01"`
    - Dimensions: `(epoch: 96, sv: 32)`
    - CLK is optional (`aux_data.fetch_clock`, default `true`); SP3 is always required

</div>

Combining these requires:

1. **Dimension conversion** from `sv` (32 satellites) to `sid` (384 signal IDs)
2. **Temporal interpolation** from 15 min to the observations' sampling interval, on a grid from 00:00
3. **Coordinate transform** from ECEF to geodetic to spherical $(r, \theta, \varphi)$
4. **Physically correct interpolation** per data type

```mermaid
graph TD
    A["`**SP3 File**
    sv dimension`"]
    A -->|Download| B["`**Raw Dataset**
    96 epochs, 32 svs`"]
    B -->|Preprocess| C["`**Preprocessed**
    96 epochs, 384 sids`"]
    C -->|Interpolate| D["`**Interpolated**
    2880 epochs, 384 sids`"]
    D -->|Augment| E["`**RINEX Dataset**
    2880 epochs, 384 sids`"]
```

---

## Interpolation strategies

Different data types require different methods based on the underlying physics:

<div class="grid cards" markdown>

-   :fontawesome-solid-circle-nodes: &nbsp; **SP3 (Hermite cubic splines)**

    ---

    Satellite orbital motion is smooth and predictable.
    Hermite splines exploit available velocity data for C1-continuity
    and sub-millimeter interpolation accuracy.

    ```python
    config = Sp3Config(use_velocities=True, fallback="linear")
    strategy = Sp3InterpolationStrategy(config=config)
    ```

-   :fontawesome-solid-clock: &nbsp; **CLK (piecewise linear)**

    ---

    Clock corrections may have discontinuities from satellite maneuvers
    and uploads. No derivative information is available.
    Piecewise linear interpolation handles these jumps safely.

    ```python
    config = ClkConfig(window_size=9, jump_threshold=1e-6)
    strategy = ClockInterpolationStrategy(config=config)
    ```

</div>

---

## Key components

<div class="grid cards" markdown>

-   :fontawesome-solid-file-arrow-down: &nbsp; **File Handlers**

    ---

    `Sp3File` reads SP3a/c/d files: positions (X, Y, Z) and velocities (VX, VY, VZ)

    `ClkFile` reads RINEX clock files: satellite clock biases

    `ProductSpec` describes a product: its URLs, latency, and authentication

-   :fontawesome-solid-arrows-rotate: &nbsp; **Preprocessing**

    ---

    `prep_aux_ds()` runs four steps: map `sv` to `sid`, pad to the global SIDs,
    normalize the dtype, strip `_FillValue`

    ```python
    sp3_sid = prep_aux_ds(sp3_raw)
    # {'epoch': 96, 'sid': 384}
    ```

-   :fontawesome-solid-location-crosshairs: &nbsp; **Coordinate Classes**

    ---

    `ECEFPosition` holds [Earth-Centered Earth-Fixed](https://gssc.esa.int/navipedia/index.php/Reference_Frames_in_GNSS){:target="_blank"} (X, Y, Z)

    `GeodeticPosition` holds [WGS84](https://gssc.esa.int/navipedia/index.php/Reference_Frames_in_GNSS){:target="_blank"} latitude, longitude, and altitude

    [Spherical coordinates](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates){:target="_blank"} $(r, \theta, \varphi)$ relative to receiver position

-   :fontawesome-solid-cloud-arrow-down: &nbsp; **FTP Download**

    ---

    Without a NASA Earthdata account, from ESA GSSC only

    With one, from NASA CDDIS first and from ESA GSSC if that fails

    Per-DOY caching prevents redundant downloads

</div>

---

## Usage

=== "Add satellite geometry to a dataset"

    In a run, an ephemeris provider does every step below; use it the same
    way in your own code:

    ```python
    from canvod.auxiliary import ECEFPosition
    from canvod.auxiliary.ephemeris.provider import AgencyEphemerisProvider
    from canvod.config import load_config
    from canvod.readers import Rnxv3Obs

    site_config = load_config().sites.sites["ExampleSite"]
    ds = Rnxv3Obs(fpath="ROSA01TUW_R_20250010000_01D_05S_AA.rnx").to_ds()

    provider = AgencyEphemerisProvider(agency="COD", product_type="final", fetch_clock=True)
    provider.preprocess_day("2025001", site_config)  # download and read SP3 (and CLK)
    augmented = provider.augment_dataset(ds, ECEFPosition.from_ds_metadata(ds))
    # augmented has theta and phi (radians) on (epoch, sid)
    ```

    `augment_dataset` interpolates the day once onto the epoch grid (00:00 plus
    multiples of the dataset's sampling interval,
    `canvod.auxiliary.interpolation.day_grid`), caches it, gives each observation
    the nearest grid epoch and converts ECEF positions to $\theta$, $\varphi$ relative to the
    receiver position from the data.

=== "Data flow"

    ```mermaid
    sequenceDiagram
        participant User
        participant Sp3File
        participant Preprocessor
        participant Interpolator
        participant Coordinates

        User->>Sp3File: Sp3File(date, agency, product_type, ...)
        Sp3File->>Sp3File: FTP download + parse
        Sp3File-->>User: to_dataset() {epoch: 96, sv: 32}

        User->>Preprocessor: prep_aux_ds(sp3_raw)
        Preprocessor-->>User: {epoch: 96, sid: 384}

        User->>Interpolator: interpolate onto the day's epoch grid
        Interpolator->>Interpolator: Hermite splines
        Interpolator-->>User: {epoch: 2880, sid: 384}

        User->>Coordinates: compute_spherical_coordinates()
        Coordinates-->>User: (r, θ, φ) arrays

        User->>User: add_spherical_coords_to_dataset()
    ```
