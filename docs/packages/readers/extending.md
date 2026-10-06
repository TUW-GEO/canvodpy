# Extending Readers

Add support for a new GNSS data format by implementing the `GNSSDataReader` abstract base class. canvod-readers uses the ABC pattern to enforce a consistent contract — any reader that passes the checklist below can be used anywhere `GNSSDataReader` is accepted.

---

## Implementation Checklist

<div class="grid cards" markdown>

-   :fontawesome-solid-code: &nbsp; **1. Inherit correctly**

    ---

    `class MyReader(GNSSDataReader)` — just one parent!
    `GNSSDataReader` is already a Pydantic `BaseModel` with `fpath`
    and file validation built in.

-   :fontawesome-solid-list-check: &nbsp; **2. Implement abstract methods**

    ---

    `file_hash`, `source_format`, `to_ds()`, `iter_epochs()`, `start_time`,
    `end_time`, `systems` and `num_satellites`. (`num_epochs` has a default that counts via
    `iter_epochs()` — override for O(1) if your format stores the count.)

-   :fontawesome-solid-shield-halved: &nbsp; **3. Use `DatasetBuilder` (recommended)**

    ---

    Use `DatasetBuilder` in your `to_ds()` to construct the output Dataset.
    It handles coordinate arrays, frequency resolution, dtype enforcement,
    and calls `validate_dataset()` automatically.

-   :fontawesome-solid-vial: &nbsp; **4. Write tests**

    ---

    Test structure, file hash, error paths, and the validation round-trip.
    Aim for >90 % coverage.

</div>

---

## Contract Constants

The output Dataset contract is defined by importable constants in
`canvod.readers.base` — these are the **single source of truth**:

```python
from canvod.readers.base import (
    REQUIRED_DIMS,       # ("epoch", "sid")
    REQUIRED_COORDS,     # {name: dtype, ...}
    REQUIRED_ATTRS,      # {"Created", "Software", "Institution", "File Hash"}
    DEFAULT_REQUIRED_VARS,  # ["SNR"]
)
```

Use `validate_dataset(ds)` to check any Dataset against them.
It collects **all** violations and raises a single `ValueError`
listing every problem.

---

## Step-by-Step Implementation

### Step 1 — Reader Class

`GNSSDataReader` is a Pydantic `BaseModel` with `fpath: Path` and file
validation built in. You only need to set reader-specific config:

```python
from pydantic import ConfigDict
from canvod.readers.base import GNSSDataReader

class MyFormatReader(GNSSDataReader):
    """Reader for My Custom Format."""

    model_config = ConfigDict(frozen=True)   # no arbitrary_types needed
    # no fpath field needed — inherited from GNSSDataReader

    @property
    def source_format(self) -> str:
        return "my_format"
```

### Step 2 — File Hash

```python
from canvod.utils.tools import file_hash

class MyFormatReader(GNSSDataReader):
    ...

    @property
    def file_hash(self) -> str:
        """16-character SHA-256 prefix of the file — used for deduplication."""
        return file_hash(self.fpath)
```

### Step 3 — Metadata Properties

```python
class MyFormatReader(GNSSDataReader):
    ...

    @property
    def start_time(self) -> datetime:
        return self._parse_start_time()

    @property
    def end_time(self) -> datetime:
        return self._parse_end_time()

    @property
    def systems(self) -> list[str]:
        return self._parse_systems()   # e.g. ["G", "E"]

    # num_epochs has a default (iterates via iter_epochs);
    # override for O(1) if your format stores the count in the header.

    @property
    def num_satellites(self) -> int:
        return self._count_satellites()
```

### Step 4 — Epoch Iterator

```python
from collections.abc import Iterator

class MyFormatReader(GNSSDataReader):
    ...

    def iter_epochs(self) -> Iterator:
        """Lazily yield one epoch at a time — keep memory bounded."""
        with self.fpath.open("rb") as f:
            self._skip_header(f)
            for raw in self._raw_epoch_generator(f):
                yield self._decode_epoch(raw)
```

### Step 5 — Dataset Conversion with DatasetBuilder

`DatasetBuilder` handles coordinate assembly, frequency resolution,
dtype enforcement, and validation — so your `to_ds()` stays simple:

```python
from canvod.readers.builder import DatasetBuilder

class MyFormatReader(GNSSDataReader):
    ...

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs,
    ) -> xr.Dataset:
        # the time scale of the epochs: must be "GPS" (required)
        builder = DatasetBuilder(self, time_system="GPS")
        for epoch in self.iter_epochs():
            ei = builder.add_epoch(epoch.timestamp)
            for obs in epoch.observations:
                sig = builder.add_signal(
                    sv=obs.sv, band=obs.band, code=obs.code
                )
                builder.set_value(ei, sig, "SNR", obs.snr_value)
        return builder.build(
            keep_data_vars=keep_data_vars,
            extra_attrs={"Source Format": "My Custom Format"},
        )
```

??? note "Manual Dataset construction (advanced)"

    If you need more control than `DatasetBuilder` provides, you can
    construct the Dataset manually using `SignalIDMapper` and
    `validate_dataset()`:

    ```python
    import numpy as np
    import xarray as xr
    from canvod.readers.gnss_specs.signals import SignalIDMapper
    from canvod.readers.gnss_specs.metadata import (
        COORDS_METADATA,
        SNR_METADATA,
        epoch_coord_attrs,
    )
    from canvod.readers.base import validate_dataset

    class MyFormatReader(GNSSDataReader):
        ...

        def to_ds(
            self,
            keep_data_vars: list[str] | None = None,
            **kwargs,
        ) -> xr.Dataset:
            all_epochs = list(self.iter_epochs())
            mapper = SignalIDMapper()

            # Build SID index, coordinate arrays, data arrays...
            # (see existing readers for full example). The epoch
            # coordinate carries epoch_coord_attrs("GPS") (its time scale).

            ds = xr.Dataset(
                data_vars={"SNR": (("epoch", "sid"), snr, SNR_METADATA)},
                coords={...},
                attrs={**self._build_attrs(), "Source Format": "My Custom Format"},
            )

            # MANDATORY — validate before returning
            validate_dataset(ds, required_vars=keep_data_vars)
            return ds
    ```

### Step 6 — `to_ds_and_auxiliary()` (optional)

If your format embeds metadata beyond observations (like SBF embeds
satellite geometry), override `to_ds_and_auxiliary()` to collect
both datasets in a single file scan:

```python
def to_ds_and_auxiliary(
    self,
    keep_data_vars: list[str] | None = None,
    **kwargs,
) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
    obs_ds = ...   # build obs dataset
    meta_ds = ...  # build metadata dataset
    return obs_ds, {"my_format_meta": meta_ds}
```

The default implementation calls `to_ds()` and returns an empty dict.

---

## Validation Requirements

=== "Dimensions"

    ```python
    assert "epoch" in ds.dims
    assert "sid"   in ds.dims
    ```

=== "Coordinates"

    ```python
    from canvod.readers.base import REQUIRED_COORDS

    # REQUIRED_COORDS = {
    #     "epoch":       "datetime64[ns]",
    #     "sid":         "object",     # string
    #     "sv":          "object",
    #     "system":      "object",
    #     "band":        "object",
    #     "code":        "object",
    #     "freq_center": "float32",    # must be float32
    #     "freq_min":    "float32",
    #     "freq_max":    "float32",
    # }
    ```

=== "Attributes"

    ```python
    from canvod.readers.base import REQUIRED_ATTRS

    # REQUIRED_ATTRS = {
    #     "Created",
    #     "Software",
    #     "Institution",
    #     "File Hash",    # for storage deduplication
    # }
    ```

=== "Data Variables"

    ```python
    # SNR required by default
    assert "SNR" in ds.data_vars

    # All variables must be (epoch, sid)
    for var in ds.data_vars:
        assert ds[var].dims == ("epoch", "sid")
    ```

---

## Testing

=== "Unit Tests"

    ```python
    # tests/test_my_format_reader.py
    import pytest
    from pathlib import Path
    from my_package.readers import MyFormatReader

    class TestMyFormatReader:

        def test_file_hash_is_deterministic(self, tmp_path):
            f = tmp_path / "test.dat"
            f.write_bytes(b"content")
            reader = MyFormatReader(fpath=f)
            assert reader.file_hash == reader.file_hash
            assert len(reader.file_hash) == 16

        def test_dataset_dimensions(self, real_test_file):
            ds = MyFormatReader(fpath=real_test_file).to_ds()
            assert "epoch" in ds.dims
            assert "sid"   in ds.dims

        def test_dataset_variables(self, real_test_file):
            ds = MyFormatReader(fpath=real_test_file).to_ds()
            assert "SNR" in ds.data_vars

        def test_sid_dimensions(self, real_test_file):
            ds = MyFormatReader(fpath=real_test_file).to_ds()
            for var in ds.data_vars:
                assert ds[var].dims == ("epoch", "sid")

        def test_file_hash_in_attrs(self, real_test_file):
            ds = MyFormatReader(fpath=real_test_file).to_ds()
            assert "File Hash" in ds.attrs
    ```

=== "Integration Test"

    ```python
    @pytest.mark.integration
    def test_full_pipeline(real_test_file):
        reader = MyFormatReader(fpath=real_test_file)
        ds = reader.to_ds(keep_data_vars=["SNR"])

        # Filter GPS only
        gps = ds.where(ds.system == "G", drop=True)
        assert len(gps.sid) > 0

        # Sanity-check values
        assert float(gps.SNR.mean()) > 0
    ```

=== "Validation Round-Trip"

    ```python
    from canvod.readers.base import validate_dataset

    def test_validation_passes(real_test_file):
        ds = MyFormatReader(fpath=real_test_file).to_ds()
        # validate_dataset() is already called inside to_ds() —
        # this test verifies it didn't raise
        validate_dataset(ds)   # should not raise
    ```

---

## Common Pitfalls

!!! failure "Wrong dtype for frequency coordinates"
    ```python
    # WRONG — float64 fails the dtype check
    freq_center = np.array([...], dtype=np.float64)

    # CORRECT — DatasetBuilder handles this automatically
    freq_center = np.array([...], dtype=np.float32)
    ```

!!! failure "Skipping validation"
    ```python
    # WRONG — missing mandatory validation
    def to_ds(self, **kwargs) -> xr.Dataset:
        ds = self._build_dataset()
        return ds   # ← will silently produce invalid datasets downstream

    # CORRECT — DatasetBuilder.build() calls validate_dataset() for you
    def to_ds(self, **kwargs) -> xr.Dataset:
        builder = DatasetBuilder(self, time_system="GPS")
        # ... add epochs, signals, values ...
        return builder.build()  # validates automatically
    ```

!!! failure "Wrong dimension names"
    ```python
    # WRONG
    data_vars={"SNR": (("time", "signal"), data)}

    # CORRECT — DatasetBuilder uses the right names automatically
    data_vars={"SNR": (("epoch", "sid"), data)}
    ```

---

## Registering with ReaderFactory

```python
from canvodpy import ReaderFactory
from my_package.readers import MyFormatReader

# Register by name
ReaderFactory.register("my_format", MyFormatReader)

# Create by name
reader = ReaderFactory.create("my_format", fpath="file.dat")
```

`ReaderFactory.create_from_file(path)` detects RINEX 2, RINEX 3 and NMEA
from the file content. Custom formats use the name-based API above.

!!! note "Readers in runs"
    `canvodpy run` picks readers by the receiver's `reader_format`
    setting, which accepts only the built-in formats (`auto`, `rinex3`,
    `rinex3_stripped`, `rinex2`, `sbf`, `nmea`). A registered custom
    reader works in your own scripts; to use a new format in runs, add
    the reader to canvod-readers (see [Building a Reader](building-a-reader.md)).
