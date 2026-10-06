"""Tests for DatasetBuilder helper."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.base import GNSSDataReader, SignalID, validate_dataset
from canvod.readers.builder import DatasetBuilder, sid_coords
from canvod.readers.gnss_specs.signals import SignalIDMapper

# ---------------------------------------------------------------------------
# Concrete reader stub for tests
# ---------------------------------------------------------------------------


class _StubReader(GNSSDataReader):
    """Minimal concrete reader for testing DatasetBuilder."""

    @property
    def file_hash(self) -> str:
        return "abcdef1234567890"

    @property
    def source_format(self) -> str:
        return "stub"

    def to_ds(self, keep_data_vars=None, **kwargs):
        raise NotImplementedError

    def iter_epochs(self) -> Iterator[object]:
        return iter([])

    @property
    def start_time(self) -> datetime:
        return datetime(2025, 1, 1, tzinfo=UTC)

    @property
    def end_time(self) -> datetime:
        return datetime(2025, 1, 2, tzinfo=UTC)

    @property
    def systems(self) -> list[str]:
        return ["G"]

    @property
    def num_satellites(self) -> int:
        return 1


@pytest.fixture()
def stub_file(tmp_path: Path) -> Path:
    """Create a temporary file so the fpath validator passes."""
    f = tmp_path / "test.dat"
    f.write_bytes(b"dummy data")
    return f


@pytest.fixture()
def reader(stub_file: Path) -> _StubReader:
    return _StubReader(fpath=stub_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reader_must_name_its_source_format(stub_file: Path) -> None:
    """A reader without ``source_format`` cannot be created."""

    class _NoFormat(_StubReader):
        source_format = GNSSDataReader.source_format

    with pytest.raises(TypeError, match="source_format"):
        _NoFormat(fpath=stub_file)


class TestDatasetBuilder:
    """End-to-end DatasetBuilder tests."""

    def test_basic_build(self, reader: _StubReader):
        """Build a minimal Dataset with one epoch, one signal, one value."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars
        assert ds.sizes["epoch"] == 1
        assert ds.sizes["sid"] == 1
        assert float(ds["SNR"].values[0, 0]) == pytest.approx(42.0)

    def test_multiple_signals_and_epochs(self, reader: _StubReader):
        """Build with multiple signals across multiple epochs."""
        builder = DatasetBuilder(reader, time_system="GPS")

        e0 = builder.add_epoch(datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC))
        e1 = builder.add_epoch(datetime(2025, 1, 1, 0, 0, 30, tzinfo=UTC))

        sig_g01 = builder.add_signal(sv="G01", band="L1", code="C")
        sig_e25 = builder.add_signal(sv="E25", band="E5a", code="I")

        builder.set_value(e0, sig_g01, "SNR", 40.0)
        builder.set_value(e0, sig_e25, "SNR", 35.0)
        builder.set_value(e1, sig_g01, "SNR", 41.0)
        builder.set_value(e1, sig_e25, "SNR", 36.0)

        ds = builder.build()

        assert ds.sizes["epoch"] == 2
        assert ds.sizes["sid"] == 2
        # Check that sids are sorted
        sids = list(ds["sid"].values)
        assert sids == sorted(sids)

    def test_add_signal_is_idempotent(self, reader: _StubReader):
        """Calling add_signal with same args returns same SignalID."""
        builder = DatasetBuilder(reader, time_system="GPS")
        sig1 = builder.add_signal(sv="G01", band="L1", code="C")
        sig2 = builder.add_signal(sv="G01", band="L1", code="C")
        assert sig1 == sig2

        builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        builder.set_value(0, sig1, "SNR", 42.0)
        ds = builder.build()
        assert ds.sizes["sid"] == 1

    def test_set_value_accepts_string(self, reader: _StubReader):
        """set_value accepts a string SID instead of SignalID."""
        builder = DatasetBuilder(reader, time_system="GPS")
        builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(0, "G01|L1|C", "SNR", 42.0)
        ds = builder.build()
        assert float(ds["SNR"].values[0, 0]) == pytest.approx(42.0)

    def test_missing_values_are_nan(self, reader: _StubReader):
        """Unset values should be NaN for float vars."""
        builder = DatasetBuilder(reader, time_system="GPS")
        builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        builder.add_epoch(datetime(2025, 1, 1, 0, 0, 30, tzinfo=UTC))
        builder.add_signal(sv="G01", band="L1", code="C")
        builder.add_signal(sv="G02", band="L1", code="C")
        # Only set one value
        builder.set_value(0, "G01|L1|C", "SNR", 42.0)
        ds = builder.build()
        assert np.isnan(ds["SNR"].values[0, 1])  # G02 at epoch 0
        assert np.isnan(ds["SNR"].values[1, 0])  # G01 at epoch 1

    def test_multiple_variables(self, reader: _StubReader):
        """Build with SNR and Pseudorange."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        builder.set_value(ei, sig, "Pseudorange", 20_000_000.0)
        ds = builder.build()

        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert ds["SNR"].dtype == np.float32
        assert ds["Pseudorange"].dtype == np.float64

    def test_keep_data_vars_filter(self, reader: _StubReader):
        """keep_data_vars filters output variables."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        builder.set_value(ei, sig, "Pseudorange", 20_000_000.0)
        ds = builder.build(keep_data_vars=["SNR"])

        assert "SNR" in ds.data_vars
        assert "Pseudorange" not in ds.data_vars

    def test_extra_attrs(self, reader: _StubReader):
        """extra_attrs are merged into global attributes."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build(extra_attrs={"Source Format": "Test"})
        assert ds.attrs["Source Format"] == "Test"

    def test_coordinates_have_correct_dtypes(self, reader: _StubReader):
        """Frequency coordinates must be float32."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        assert ds["freq_center"].dtype == np.float32
        assert ds["freq_min"].dtype == np.float32
        assert ds["freq_max"].dtype == np.float32

    def test_frequency_resolution(self, reader: _StubReader):
        """GPS L1 frequency should be resolved correctly."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        fc = float(ds["freq_center"].values[0])
        assert fc == pytest.approx(1575.42, rel=1e-4)

    def test_validate_dataset_called(self, reader: _StubReader):
        """build() calls validate_dataset; result passes validation."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        # Should not raise
        validate_dataset(ds)

    def test_required_attrs_present(self, reader: _StubReader):
        """Dataset must have all required attributes."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        assert "File Hash" in ds.attrs
        assert "Created" in ds.attrs
        assert "Software" in ds.attrs
        assert "Institution" in ds.attrs

    def test_file_hash_from_reader(self, reader: _StubReader):
        """File Hash attribute should match reader.file_hash."""
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        ds = builder.build()

        assert ds.attrs["File Hash"] == reader.file_hash

    def test_signal_validation_rejects_bad_sv(self, reader: _StubReader):
        """add_signal should reject invalid SVs."""
        builder = DatasetBuilder(reader, time_system="GPS")
        with pytest.raises(Exception, match="Invalid SV"):
            builder.add_signal(sv="X01", band="L1", code="C")

    def test_epoch_records_time_system(self, reader: _StubReader):
        builder = DatasetBuilder(reader, time_system="GPS")
        ei = builder.add_epoch(datetime(2025, 1, 1, tzinfo=UTC))
        sig = builder.add_signal(sv="G01", band="L1", code="C")
        builder.set_value(ei, sig, "SNR", 42.0)
        assert builder.build()["epoch"].attrs["time_system"] == "GPS"

    @pytest.mark.parametrize("scale", ["UTC", "GLO", "LOCAL"])
    def test_other_time_systems_are_rejected(self, reader: _StubReader, scale):
        with pytest.raises(ValueError, match="stores every epoch in GPS time"):
            DatasetBuilder(reader, time_system=scale)


class TestSidCoords:
    def test_coordinates_of_signals(self):
        signals = [
            SignalID(sv="E05", band="E5a", code="Q"),
            SignalID(sv="G01", band="L1", code="u"),
        ]
        coords = sid_coords(signals, mapper=SignalIDMapper())
        ds = xr.Dataset(coords=coords)
        assert list(ds["sid"].values) == ["E05|E5a|Q", "G01|L1|u"]
        assert list(ds["system"].values) == ["E", "G"]
        assert list(ds["code"].values) == ["Q", "u"]
        assert ds["freq_center"].dtype == np.float32
        np.testing.assert_allclose(ds["freq_center"].values, [1176.45, 1575.42])
        assert np.all(ds["freq_min"].values < ds["freq_center"].values)
        assert np.all(ds["freq_max"].values > ds["freq_center"].values)
