# Architecture and Design Patterns

This page documents the design principles and extensibility patterns used throughout canVODpy.

---

## Design Principles

<div class="grid cards" markdown>

-   :fontawesome-solid-cubes: &nbsp; **Modularity**

    ---

    Independent packages with minimal coupling.
    Install only what you need; replace only what you must.

-   :fontawesome-solid-puzzle-piece: &nbsp; **Extensibility**

    ---

    ABC + Factory pattern throughout. Add a custom reader, grid,
    or VOD algorithm in < 50 lines — no framework internals to understand.

-   :fontawesome-solid-shield-halved: &nbsp; **Type Safety**

    ---

    Modern Python type hints + Pydantic validation at every boundary.
    Errors surface at construction time, not during analysis.

-   :fontawesome-solid-microscope: &nbsp; **Scientific Focus**

    ---

    Explicit over implicit. Reproducible by default — every dataset
    is traceable to a config version, file hash, and Icechunk snapshot ID.

</div>

---

## The Sollbruchstellen Principle

canVODpy applies the engineering concept of *Sollbruchstellen* (predetermined breaking points): packages are designed to be independent so they can be used separately or replaced without affecting the rest of the system.

```
Foundation (0 inter-package dependencies):
  canvod-readers, canvod-grids, canvod-vod, canvod-utils

Consumer (1–2 dependencies each):
  canvod-auxiliary      → canvod-readers
  canvod-viz            → canvod-grids
  canvod-store          → canvod-grids
  canvod-store-metadata → canvod-utils
  canvod-ops            → canvod-grids, canvod-utils

Orchestration:
  canvodpy              → all packages
```

---

## ABC + Factory Pattern

```mermaid
flowchart TD
    subgraph ABCS["Abstract Base Classes"]
        READER_ABC["`**GNSSDataReader**
        to_ds, iter_epochs, file_hash`"]
        GRID_ABC["`**BaseGridBuilder**
        build`"]
        VOD_ABC["`**VODCalculator**
        calculate_vod`"]
    end

    subgraph FACTORIES["Factory Registry"]
        RF["ReaderFactory"]
        GF["GridFactory"]
        VF["VODFactory"]
    end

    subgraph BUILTIN["Built-in"]
        RINEX3["Rnxv3Obs"]
        EA["EqualAreaBuilder"]
        HP["EqualAngleBuilder"]
        TO["TauOmegaZerothOrder"]
    end

    subgraph CUSTOM["User Extension"]
        IMPL["`**Custom class**
        inherits ABC`"]
        REG["Factory.register()"]
    end

    READER_ABC --> RF
    GRID_ABC   --> GF
    VOD_ABC    --> VF

    RINEX3 --> RF
    EA     --> GF
    HP     --> GF
    TO     --> VF

    IMPL --> REG --> RF
```

### Registration + Usage

```python
from typing import ClassVar

from pydantic import ConfigDict
from canvodpy import ReaderFactory
from canvod.readers import GNSSDataReader
from canvod.readers.builder import DatasetBuilder


class MyLabReader(GNSSDataReader):
    """GNSSDataReader is a Pydantic BaseModel + ABC — one parent is enough."""

    model_config = ConfigDict(frozen=True)
    # fpath is inherited from GNSSDataReader — no need to redeclare
    file_type: ClassVar[str] = "mlb"  # TYPE field of the files' canVOD names

    def to_ds(self, keep_data_vars=None, **kwargs) -> xr.Dataset:
        builder = DatasetBuilder(self, time_system="GPS")
        for epoch in self.iter_epochs():
            ei = builder.add_epoch(epoch.timestamp)
            for obs in epoch.observations:
                sig = builder.add_signal(sv=obs.sv, band=obs.band, code=obs.code)
                builder.set_value(ei, sig, "SNR", obs.snr)
        return builder.build(keep_data_vars=keep_data_vars)

    # ... implement remaining abstract methods ...


# Register for this Python session; for canvodpy run, install it as a
# plugin instead (guides/plugins.md)
ReaderFactory.register("mylab_v1", MyLabReader)

# Use anywhere
reader = ReaderFactory.create("mylab_v1", fpath=path)
ds = reader.to_ds()
```

---

## Unified API Surface

canvodpy exposes two supported surfaces, plus the CLI on top of one of them —
all backed by the same packages. See [API Levels](api-levels.md) for full
detail.

=== "CLI — Running the Pipeline"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025007
    ```

=== "Site.pipeline() — Python-native"

    ```python
    from canvodpy import Site

    site = Site("ExampleSite")
    with site.pipeline(n_workers=8) as pipeline:
        for date_key, datasets in pipeline.process_range("2025001", "2025007"):
            site.vod.compute_day(datasets, "canopy_01_vs_reference_01")
    ```

=== "Direct Package Access — lowest level"

    Bypassing the orchestrator entirely; used internally by both surfaces
    above.

    ```python
    from canvod.readers import Rnxv3Obs
    from canvod.grids import EqualAreaBuilder
    from canvod.vod import TauOmegaZerothOrder

    reader = Rnxv3Obs(fpath=Path("station.25o"))
    ds = reader.to_ds(keep_data_vars=["SNR"])
    ```

---

## Configuration Management

```mermaid
flowchart TD
    subgraph FILES["Config Sources"]
        YAML["canvod-settings.yaml"]
        ENV[".env / env vars"]
        DEF["Package defaults"]
    end

    subgraph LOAD["Loader"]
        MERGE["`**Deep merge**
        user overrides defaults`"]
        PYDANTIC["Pydantic validation"]
    end

    subgraph VALIDATED["CanvodConfig"]
        PC["ProcessingConfig"]
        SC["SitesConfig"]
        SIC["SidsConfig"]
    end

    YAML & ENV & DEF --> MERGE --> PYDANTIC
    PYDANTIC --> PC & SC & SIC
```

```python
from canvod.config import load_config

cfg = load_config()
cfg.processing.aux_data.nasa_earthdata_acc_mail
cfg.processing.storage.stores_root_dir
```

```bash
canvodpy config init      # Scaffold canvod-settings.yaml from template
canvodpy config validate  # Validate current config
canvodpy config show      # Print resolved config
```

---

## Provenance and Reproducibility

Every dataset produced by canVODpy is fully traceable:

!!! success "Full provenance chain"
    | Field | Source |
    |-------|--------|
    | `ds.attrs["File Hash"]` | SHA-256 of raw input file |
    | `ds.attrs["Software"]` | `canvod-readers x.y.z` |
    | `ds.attrs["Created"]` | ISO 8601 timestamp |
    | Icechunk snapshot ID | Hash-addressable, immutable |
    | Config version | Committed alongside code |

---

## Airflow / Distributed Execution

An optional Airflow extension (see
[Optional extensions](extensions.md)) builds its DAGs on
`canvodpy.workflows.tasks`, which uses the same file discovery and processing
code as `canvodpy run`.

Factory registration happens at module import time — each worker process has access to all registered implementations automatically.
