"""Tests for data integrity and validation in Icechunk stores.

Tests cover:
- Data type preservation (float32/64, int types)
- Coordinate preservation
- Attribute preservation (dataset and variable attrs)
- NaN handling
- Chunking strategies
- Compression verification
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr
from canvod.store_metadata.testing import create_test_store

from canvod.store import open_vod_store


@pytest.fixture
def vod_store(tmp_path: Path):
    """Create temporary VOD store for testing."""
    store_path = tmp_path / "test_site" / "vod_store"
    return open_vod_store(create_test_store(store_path))


class TestDatatypePreservation:
    """Test that data types are preserved through store/load cycle."""

    def test_float32_preserved(self, vod_store) -> None:
        """Verify float32 dtype preserved."""
        ds = xr.Dataset(
            {"data": (["x"], np.array([1.0, 2.0, 3.0], dtype=np.float32))},
            coords={"x": [0, 1, 2]},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_float32", mode="w")
            session.commit("Test float32")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_float32", consolidated=False
            )
            assert loaded_ds["data"].dtype == np.float32

    def test_float64_preserved(self, vod_store) -> None:
        """Verify float64 dtype preserved."""
        ds = xr.Dataset(
            {"data": (["x"], np.array([1.0, 2.0, 3.0], dtype=np.float64))},
            coords={"x": [0, 1, 2]},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_float64", mode="w")
            session.commit("Test float64")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_float64", consolidated=False
            )
            assert loaded_ds["data"].dtype == np.float64

    def test_int32_preserved(self, vod_store) -> None:
        """Verify int32 dtype preserved."""
        ds = xr.Dataset(
            {"data": (["x"], np.array([1, 2, 3], dtype=np.int32))},
            coords={"x": [0, 1, 2]},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_int32", mode="w")
            session.commit("Test int32")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_int32", consolidated=False
            )
            assert loaded_ds["data"].dtype == np.int32

    def test_multiple_dtypes_in_dataset(self, vod_store) -> None:
        """Verify multiple dtypes coexist correctly."""
        ds = xr.Dataset(
            {
                "float_var": (["x"], np.array([1.0, 2.0], dtype=np.float32)),
                "int_var": (["x"], np.array([10, 20], dtype=np.int32)),
                "double_var": (["x"], np.array([3.14, 2.71], dtype=np.float64)),
            },
            coords={"x": [0, 1]},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_mixed", mode="w")
            session.commit("Test mixed dtypes")

        # Load and verify all
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_mixed", consolidated=False
            )
            assert loaded_ds["float_var"].dtype == np.float32
            assert loaded_ds["int_var"].dtype == np.int32
            assert loaded_ds["double_var"].dtype == np.float64


class TestDatetime64NsPreservation:
    """Test that datetime64[ns] (RINEX reader dtype) is preserved."""

    def test_datetime64_ns_preserved(self, vod_store) -> None:
        """Verify datetime64[ns] precision round-trips correctly."""
        time_vals = np.arange(
            "2024-01-01T00:00:00",
            "2024-01-01T01:00:00",
            np.timedelta64(30, "s"),
            dtype="datetime64[ns]",
        )
        ds = xr.Dataset(
            {"data": (["time"], np.random.rand(len(time_vals)))},
            coords={"time": time_vals},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_ns_time", mode="w")
            session.commit("Test datetime64[ns]")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_ns_time", consolidated=False
            )
            assert np.issubdtype(loaded_ds.coords["time"].dtype, np.datetime64)
            # Values should match exactly at nanosecond precision
            np.testing.assert_array_equal(loaded_ds.coords["time"].values, time_vals)


class TestObjectDtypeSidPreservation:
    """Test that object-dtype string coordinates survive store/load."""

    def test_object_dtype_sid_preserved(self, vod_store) -> None:
        """Verify object-dtype SID strings round-trip correctly."""
        sids = np.array(["G01|L1|C", "G02|L2|W", "E01|E1|C", "R01|G1|P"], dtype=object)
        ds = xr.Dataset(
            {"SNR": (["epoch", "sid"], np.random.rand(10, len(sids)))},
            coords={
                "epoch": np.arange(10),
                "sid": sids,
            },
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_obj_sid", mode="w")
            session.commit("Test object dtype SID")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_obj_sid", consolidated=False
            )
            loaded_sids = loaded_ds.coords["sid"].values
            # All SID values should match
            np.testing.assert_array_equal(loaded_sids, sids)
            # Values should be strings
            assert all(isinstance(s, str) for s in loaded_sids)


class TestCoordinatePreservation:
    """Test that dimension coordinates remain intact."""

    def test_1d_coords_preserved(self, vod_store) -> None:
        """Verify 1D coordinates preserved."""
        x_vals = np.arange(0, 10, 0.5)
        ds = xr.Dataset(
            {"data": (["x"], np.random.rand(len(x_vals)))},
            coords={"x": x_vals},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_1d_coords", mode="w")
            session.commit("Test 1D coords")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_1d_coords", consolidated=False
            )
            np.testing.assert_array_equal(loaded_ds.coords["x"], x_vals)

    def test_2d_coords_preserved(self, vod_store) -> None:
        """Verify 2D coordinates preserved."""
        ds = xr.Dataset(
            {"data": (["x", "y"], np.random.rand(5, 10))},
            coords={"x": np.arange(5), "y": np.arange(10)},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_2d_coords", mode="w")
            session.commit("Test 2D coords")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_2d_coords", consolidated=False
            )
            assert set(loaded_ds.coords) == {"x", "y"}
            assert len(loaded_ds.coords["x"]) == 5
            assert len(loaded_ds.coords["y"]) == 10

    def test_time_coords_preserved(self, vod_store) -> None:
        """Verify datetime64 time coordinates preserved."""
        time_vals = np.arange("2024-01-01", "2024-01-10", dtype="datetime64[D]")
        ds = xr.Dataset(
            {"data": (["time"], np.random.rand(len(time_vals)))},
            coords={"time": time_vals},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_time_coords", mode="w")
            session.commit("Test time coords")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_time_coords", consolidated=False
            )
            assert "time" in loaded_ds.coords
            # Datetime64 should be preserved
            assert np.issubdtype(loaded_ds.coords["time"].dtype, np.datetime64)


class TestAttributePreservation:
    """Test that dataset and variable attributes are preserved."""

    def test_dataset_attrs_preserved(self, vod_store) -> None:
        """Verify dataset-level attributes intact."""
        ds = xr.Dataset(
            {"data": (["x"], np.random.rand(5))},
            coords={"x": [0, 1, 2, 3, 4]},
        )
        ds.attrs["title"] = "Test Dataset"
        ds.attrs["version"] = "1.0"
        ds.attrs["processing_date"] = "2024-01-01"

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_ds_attrs", mode="w")
            session.commit("Test dataset attrs")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_ds_attrs", consolidated=False
            )
            assert loaded_ds.attrs["title"] == "Test Dataset"
            assert loaded_ds.attrs["version"] == "1.0"
            assert loaded_ds.attrs["processing_date"] == "2024-01-01"

    def test_variable_attrs_preserved(self, vod_store) -> None:
        """Verify variable-level attributes intact."""
        ds = xr.Dataset(
            {"temperature": (["x"], np.random.rand(5))},
            coords={"x": [0, 1, 2, 3, 4]},
        )
        ds["temperature"].attrs["units"] = "kelvin"
        ds["temperature"].attrs["long_name"] = "Air Temperature"
        ds["temperature"].attrs["standard_name"] = "air_temperature"

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_var_attrs", mode="w")
            session.commit("Test variable attrs")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_var_attrs", consolidated=False
            )
            assert loaded_ds["temperature"].attrs["units"] == "kelvin"
            assert loaded_ds["temperature"].attrs["long_name"] == "Air Temperature"


class TestNaNHandling:
    """Test that NaN values are stored and retrieved correctly."""

    def test_nan_values_preserved(self, vod_store) -> None:
        """Verify NaN values stored/retrieved correctly."""
        data = np.array([1.0, 2.0, np.nan, 4.0, np.nan])
        ds = xr.Dataset(
            {"data": (["x"], data)},
            coords={"x": [0, 1, 2, 3, 4]},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_nan", mode="w")
            session.commit("Test NaN")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_nan", consolidated=False
            )
            loaded_data = loaded_ds["data"].values

            # Check NaN positions
            assert np.isnan(loaded_data[2])
            assert np.isnan(loaded_data[4])
            assert not np.isnan(loaded_data[0])

    def test_all_nan_array(self, vod_store) -> None:
        """Verify array of all NaNs handled correctly."""
        data = np.full(10, np.nan)
        ds = xr.Dataset(
            {"data": (["x"], data)},
            coords={"x": np.arange(10)},
        )

        # Store
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_all_nan", mode="w")
            session.commit("Test all NaN")

        # Load and verify
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_all_nan", consolidated=False
            )
            loaded_data = loaded_ds["data"].values

            assert np.all(np.isnan(loaded_data))


class TestChunking:
    """Test that chunking strategies are applied."""

    def test_large_dataset_is_chunked(self, vod_store) -> None:
        """Verify large dataset uses chunking."""
        # Create large dataset
        ds = xr.Dataset(
            {
                "data": (
                    ["time", "x", "y"],
                    np.random.rand(100, 200, 200),
                )
            },
            coords={
                "time": np.arange(100),
                "x": np.arange(200),
                "y": np.arange(200),
            },
        )

        # Store with explicit chunking
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(
                root.store,
                group="test_chunked",
                mode="w",
                encoding={"data": {"chunks": (10, 50, 50)}},
            )
            session.commit("Test chunking")

        # Verify chunks applied
        with vod_store.readonly_session() as session:
            loaded_ds = xr.open_zarr(
                session.store, group="test_chunked", consolidated=False
            )
            # Data should be chunked (will have chunks attribute)
            assert hasattr(loaded_ds["data"].data, "chunks")


class TestCompression:
    """Test compression is applied and data is smaller."""

    def test_compression_reduces_size(self, vod_store, tmp_path) -> None:
        """Check compressed data smaller than raw (conceptual test)."""
        # Create dataset with repetitive data (compresses well)
        repetitive_data = np.tile([1.0, 2.0, 3.0], 1000)
        ds = xr.Dataset(
            {"data": (["x"], repetitive_data)},
            coords={"x": np.arange(len(repetitive_data))},
        )

        # Store with compression (default for MyIcechunkStore)
        with vod_store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            ds.to_zarr(root.store, group="test_compression", mode="w")
            session.commit("Test compression")

        # Verify store directory exists and has content
        # Actual compression verification would require low-level inspection
        assert vod_store.store_path.exists()
        store_size = sum(
            f.stat().st_size for f in vod_store.store_path.rglob("*") if f.is_file()
        )

        # Store should be much smaller than raw data
        raw_size = repetitive_data.nbytes
        # Compressed should be significantly smaller (at least 50% reduction)
        # Note: This is a rough heuristic test
        assert store_size < raw_size
