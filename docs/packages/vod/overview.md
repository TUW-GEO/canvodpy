# canvod-vod

## Purpose

The `canvod-vod` package implements vegetation optical depth (VOD) estimation from GNSS signal-to-noise ratio (SNR) data. It provides the core scientific algorithms for the canVODpy analysis pipeline.

---

## Physical Background

!!! abstract "Tau-Omega Radiative Transfer Model"

    canvod-vod implements the **zeroth-order tau-omega** model for [GNSS-Transmissometry](https://gssc.esa.int/navipedia/index.php/GNSS){:target="_blank"},
    following [Humphrey & Frankenberg (2022)](https://doi.org/10.1016/j.rse.2022.113208){:target="_blank"}.

    A reference receiver in open sky and a canopy receiver beneath vegetation observe
    the same satellite at [polar angle](https://gssc.esa.int/navipedia/index.php/Satellite_Elevation,_Azimuth_and_Visible_Satellites){:target="_blank"} θ. The [SNR](https://gssc.esa.int/navipedia/index.php/GNSS_Measurements){:target="_blank"} difference encodes the two-way
    canopy attenuation:

    $$\Delta\text{SNR} = \text{SNR}_\text{canopy} - \text{SNR}_\text{reference}$$

    $$T = 10^{\Delta\text{SNR} / 10} \qquad \text{(linear transmissivity)}$$

    $$\text{VOD} = -\ln(T) \cdot \cos\theta$$

    Assumptions:
    - Single-scattering approximation (no multiple canopy reflections)
    - Plane-parallel canopy layer
    - Attenuation proportional to path length through canopy

---

## Usage

=== "Direct instantiation"

    ```python
    from canvod.vod import TauOmegaZerothOrder

    calculator = TauOmegaZerothOrder(canopy_ds=canopy_ds, sky_ds=sky_ds)
    vod_result = calculator.calculate_vod()
    ```

=== "From aligned datasets"

    ```python
    from canvod.vod import TauOmegaZerothOrder

    vod_result = TauOmegaZerothOrder.from_datasets(
        canopy_ds=canopy_ds,
        sky_ds=sky_ds,
        align=True,  # auto-align epochs before differencing
    )
    ```

=== "From Icechunk store"

    ```python
    from canvod.vod import TauOmegaZerothOrder

    vod_result = TauOmegaZerothOrder.from_icechunkstore(
        icechunk_store_pth="path/to/store",
        canopy_group="canopy_01",
        sky_group="reference_01",
    )
    ```

!!! info "Input requirements"

    Both datasets must contain an `SNR` data variable.
    Both should be augmented with spherical coordinates (θ, φ) from `canvod-auxiliary`
    and assigned to grid cells by `canvod-grids`.

---

## Output

`calculate_vod()` returns an `xr.Dataset` containing:

| Variable | Description |
| -------- | ----------- |
| `VOD` | Vegetation optical depth |
| `phi` | Azimuth angles (from canopy dataset) |
| `theta` | Polar angles (from canopy dataset) |

---

## Multi-Receiver SCS Expansion

When a single reference receiver serves multiple canopy positions, satellite geometry must be recomputed relative to each canopy location. The `scs_from` field in `canvod-settings.yaml` (`sites.<name>.receivers.<ref>.scs_from`) drives this expansion.

```mermaid
flowchart TD
    subgraph FIELD["Field Setup"]
        C1["`**Canopy 1**
        NE position`"]
        C2["`**Canopy 2**
        SW position`"]
        R1["`**Reference**
        open sky`"]
    end

    subgraph STORE["RINEX Store Groups"]
        SG1["canopy_01"]
        SG2["canopy_02"]
        SG3["`**reference_01_canopy_01**
        geometry at canopy_01 pos.`"]
        SG4["`**reference_01_canopy_02**
        geometry at canopy_02 pos.`"]
    end

    subgraph VOD["VOD Analysis Pairs"]
        VP1["canopy_01 vs reference_01_canopy_01"]
        VP2["canopy_02 vs reference_01_canopy_02"]
    end

    C1 --> SG1
    C2 --> SG2
    R1 --> SG3
    R1 --> SG4
    SG1 --> VP1
    SG3 --> VP1
    SG2 --> VP2
    SG4 --> VP2
    VP1 --> V1["VOD @ canopy_01"]
    VP2 --> V2["VOD @ canopy_02"]
```

!!! note "Configuration"

    ```yaml
    # config/canvod-settings.yaml (sites.<name>.receivers)
    receivers:
      reference_01:
        type: reference
        scs_from:
          - canopy_01    # recompute geometry at canopy_01 position
          - canopy_02    # recompute geometry at canopy_02 position
    ```

---

## References

Humphrey, V. and Frankenberg, C. (2022). GNSS-transmissometry: A new approach for vegetation optical depth estimation. *Remote Sensing of Environment*.

---

!!! example "Try it"
    [10 · VOD Retrieval](../../notebooks/_build/10_vod_retrieval.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_vod_retrieval.py)
