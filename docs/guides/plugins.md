# Your own readers and VOD calculators

`canvodpy run` can read a file format and compute VOD with a model that
canvodpy does not ship. Both come from a small Python package of your own,
a **plugin**. Once the plugin is installed in the same environment as
canvodpy, its reader is a `reader_format` in the settings and its VOD
calculator a choice of `--vod-calculator`. You change nothing in canvodpy.

This page shows a complete plugin package. Copy it and replace the parts
marked as yours.

!!! example "Try it in a notebook"

    Open [Your Own VOD Calculator](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/21_plugins.py?mode=edit) in molab, the online notebook service of marimo.

## Base classes and factories

Each kind of component has an abstract base class, which lists the methods
an implementation must have, and a factory, which maps names to the
implementing classes. canvodpy registers its built-in classes when it is
imported, and the plugins after them.

| Factory | Base class | Built-in names | Used by |
|---|---|---|---|
| `ReaderFactory` | `canvod.readers.base.GNSSDataReader` | `rinex3`, `rinex3_stripped`, `rinex2`, `sbf`, `nmea` | `reader_format` of a receiver |
| `VODFactory` | `canvod.vod.calculator.VODCalculator` | `tau_omega` | `canvodpy run --vod-calculator` |
| `GridFactory` | `canvod.grids.core.grid_builder.BaseGridBuilder` | `equal_area`, `equal_angle`, `equirectangular`, `htm`, `geodesic`, `healpix`, `fibonacci` | your own scripts only |

All three are importable from `canvodpy` and share these methods:

- `register(name, cls)` adds a class. It raises a `TypeError` if the class
  doesn't inherit the factory's base class, and a `ValueError` if the name
  is already registered. To replace a registered class, pass
  `replace=True`.
- `create(name, **kwargs)` creates an instance. It raises a `ValueError`
  that lists the registered names if `name` isn't one of them.
- `list_available()` returns the registered names.

Because each class inherits an abstract base class, Python refuses to
create an instance of a class that lacks one of the required methods: the
error comes when the object is created, not halfway through a run.

Plugins can add readers and VOD calculators. A grid builder can only be
registered in your own scripts; `canvodpy run` creates its grids from the
settings.

## How canvodpy finds a plugin

A plugin declares **entry points** in its `pyproject.toml`: a name and the
class it stands for. canvodpy reads two entry point groups:

| Group | Class inherits | The name is used as |
|---|---|---|
| `canvodpy.readers` | `canvod.readers.base.GNSSDataReader` | `reader_format` of a receiver |
| `canvodpy.vod_calculators` | `canvod.vod.calculator.VODCalculator` | `canvodpy run --vod-calculator <name>` |

When canvodpy is imported, it imports every installed plugin and checks it.
A plugin that cannot be used stops canvodpy with an error that names the
plugin's package (see [Checks](#checks)). Fix the plugin or uninstall it.

## The package

```text
my-canvod-plugin/
├── pyproject.toml
└── src/
    └── my_canvod_plugin/
        ├── __init__.py
        ├── reader.py
        └── calculator.py
```

```toml
# pyproject.toml
[project]
name = "my-canvod-plugin"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["canvodpy"]

[project.entry-points."canvodpy.readers"]
my_format = "my_canvod_plugin.reader:MyFormatReader"

[project.entry-points."canvodpy.vod_calculators"]
my_model = "my_canvod_plugin.calculator:MyModel"

[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
```

A plugin can declare a reader, a calculator, or both. Each name must be new:
`auto`, the built-in reader formats (`rinex3`, `rinex3_stripped`, `rinex2`,
`sbf`, `nmea`) and the built-in calculator `tau_omega` are taken.

## The reader

```python
# src/my_canvod_plugin/reader.py
from collections.abc import Iterator
from datetime import datetime
from typing import ClassVar

import xarray as xr
from canvod.readers.base import GNSSDataReader
from canvod.readers.builder import DatasetBuilder
from canvod.utils.tools import file_hash


class MyFormatReader(GNSSDataReader):
    """Reader for the files of my receiver."""

    #: The TYPE field of the files' canVOD names: ...AA.myf
    file_type: ClassVar[str] = "myf"

    @property
    def source_format(self) -> str:
        return "my_format"

    @property
    def file_hash(self) -> str:
        return file_hash(self.fpath)

    def iter_epochs(self) -> Iterator:
        # yours: parse the file, yield one epoch at a time
        ...

    def to_ds(self, keep_data_vars=None, **kwargs) -> xr.Dataset:
        builder = DatasetBuilder(self, time_system="GPS")
        for epoch in self.iter_epochs():
            ei = builder.add_epoch(epoch.timestamp)
            for obs in epoch.observations:
                sig = builder.add_signal(sv=obs.sv, band=obs.band, code=obs.code)
                builder.set_value(ei, sig, "SNR", obs.snr)
        return builder.build(keep_data_vars=keep_data_vars)

    @property
    def start_time(self) -> datetime: ...  # yours: first epoch

    @property
    def end_time(self) -> datetime: ...  # yours: last epoch

    @property
    def systems(self) -> list[str]: ...  # yours: e.g. ["G", "E"]

    @property
    def num_satellites(self) -> int: ...  # yours
```

What the reader must do:

- **`file_type`**: the file type of its files, 2 to 8 lowercase letters and
  digits. It is the TYPE field of their canVOD names, so a run finds
  `ROSA01TUW_R_20250010000_15M_05S_AA.myf`. Files with other names need a
  naming recipe (see [Configuration](configuration.md)).
- **GPS time**: the stores hold GPS time only. `DatasetBuilder` records the
  time scale you give it; convert other time scales while reading.
- **GLONASS channels**: a run passes `processing.params.aggregate_glonass_fdma`
  to every reader. A reader that gives GLONASS FDMA signals as aggregated
  G1/G2 bands only needs nothing more: it refuses `false`. A reader that can
  give them per frequency channel sets `per_channel_glonass: ClassVar[bool] =
  True` and passes `self.aggregate_glonass_fdma` on to `DatasetBuilder`.
- Every abstract member of `GNSSDataReader`; Python refuses to create a
  reader that lacks one. [Building a Reader](../packages/readers/building-a-reader.md)
  explains each of them, the dataset the reader must return and how to test
  it.

The satellite angles come from the orbit files, as for RINEX.

## The VOD calculator

```python
# src/my_canvod_plugin/calculator.py
import numpy as np
import xarray as xr
from canvod.vod.calculator import VODCalculator


class MyModel(VODCalculator):
    """VOD from the canopy and reference signal strengths, my way."""

    def calculate_vod(self) -> xr.Dataset:
        delta_snr = self.canopy_ds["SNR"] - self.sky_ds["SNR"]
        vod = ...  # yours: from delta_snr and self.canopy_ds["theta"]
        cell_ids = {
            name: self.canopy_ds[name]
            for name in self.canopy_ds.data_vars
            if str(name).startswith("cell_id_")
        }
        return xr.Dataset(
            {
                "VOD": vod,
                "phi": self.canopy_ds["phi"],
                "theta": self.canopy_ds["theta"],
                **cell_ids,
            },
            coords=self.canopy_ds.coords,
        )
```

`canopy_ds` holds the data of the canopy receiver and `sky_ds` the data of
the reference receiver. Both are restricted to the epochs and signals they
share. Return `VOD`,
`phi` and `theta`, and keep the `cell_id_*` variables that a grid
assignment (`processing.preprocessing`) added.

## Install and run

Install the plugin into the environment canvodpy runs in:

```bash
uv add --editable ./my-canvod-plugin
```

Name the reader in the receivers that record that format (canopy and
reference must use the same reader):

```yaml
# canvod-settings.yaml
sites:
  ExampleSite:
    receivers:
      canopy_01:
        type: canopy
        directory: 02_canopy
        reader_format: my_format
      reference_01:
        type: reference
        directory: 01_reference
        reader_format: my_format
```

and run with the calculator:

```bash
canvodpy run --site ExampleSite --start 2025001 --end 2025007 --vod-calculator my_model
```

`reader_format: auto` never chooses a plugin; name it.

The VOD store records the calculator's name in its group names
(`my_model/<analysis>`).

## Checks

When canvodpy is imported, each plugin is checked. Any of these stops
canvodpy with an error that names the plugin's package:

- the class cannot be imported, or the entry point does not name a class;
- the reader does not inherit `GNSSDataReader`, the calculator not
  `VODCalculator`;
- the name is a built-in name, or two installed packages use it;
- the reader sets no valid `file_type`.

A `reader_format` that is neither built in nor an installed plugin is an
error when the settings are loaded; the message lists the known formats.

## In your own scripts

Without a package, register a class for the current Python session:

```python
from canvodpy import ReaderFactory, VODFactory

ReaderFactory.register("my_format", MyFormatReader)
VODFactory.register("my_model", MyModel)
reader = ReaderFactory.create(
    "my_format", fpath="ROSA01TUW_R_20250010000_15M_05S_AA.myf"
)
```

This does not reach `canvodpy run`, which starts its own Python process;
`run` sees installed plugins only.
