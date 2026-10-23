"""Tests for SID-space preprocessing utilities (sv -> sid conversion, global padding)."""

import numpy as np
import pytest
import xarray as xr

from canvod.readers.preprocessing import (
    add_future_datavars,
    create_sv_to_sid_mapping,
    map_aux_sv_to_sid,
    normalize_sid_dtype,
    pad_to_global_sid,
    strip_fillvalue,
)


class TestCreateSvToSidMapping:
    """Test create_sv_to_sid_mapping function."""

    def test_gps_satellite_mapping(self):
        """Test GPS satellite generates correct signal IDs."""
        mapping = create_sv_to_sid_mapping(["G01"])

        assert "G01" in mapping
        sids = mapping["G01"]

        # Check expected signal IDs exist
        assert "G01|L1|C" in sids
        assert "G01|L2|W" in sids
        assert "G01|L5|I" in sids

        # Should have multiple sids
        assert len(sids) > 10

    def test_galileo_satellite_mapping(self):
        """Test Galileo satellite generates correct signal IDs."""
        mapping = create_sv_to_sid_mapping(["E01"])

        assert "E01" in mapping
        sids = mapping["E01"]

        assert "E01|E1|C" in sids
        assert "E01|E5a|Q" in sids
        assert "E01|E5b|I" in sids

    def test_glonass_satellite_mapping(self):
        """Test GLONASS satellite generates correct signal IDs."""
        mapping = create_sv_to_sid_mapping(["R01"])

        assert "R01" in mapping
        sids = mapping["R01"]

        assert "R01|G1|C" in sids
        assert "R01|G2|P" in sids

    def test_beidou_satellite_mapping(self):
        """Test BeiDou satellite generates correct signal IDs."""
        mapping = create_sv_to_sid_mapping(["C01"])

        assert "C01" in mapping
        sids = mapping["C01"]

        # BeiDou has B1, B2, B3 bands
        assert any("B1" in sid for sid in sids)

    def test_multiple_satellites(self):
        """Test mapping multiple satellites at once."""
        svs = ["G01", "G02", "E01", "R01"]
        mapping = create_sv_to_sid_mapping(svs)

        assert len(mapping) == 4
        for sv in svs:
            assert sv in mapping
            assert len(mapping[sv]) > 0

    def test_unknown_system_ignored(self):
        """Test unknown GNSS system is gracefully ignored."""
        mapping = create_sv_to_sid_mapping(["X99"])  # Invalid

        # Should not crash, just skip unknown
        assert "X99" not in mapping or len(mapping["X99"]) == 0


class TestMapAuxSvToSid:
    """Test map_aux_sv_to_sid function."""

    def test_dimension_expansion(self, sample_sp3_data):
        """Test sv dimension expands to sid dimension."""
        result = map_aux_sv_to_sid(sample_sp3_data)

        # Check dimensions
        assert "epoch" in result.sizes
        assert "sid" in result.sizes
        assert "sv" not in result.sizes

        # Epoch count unchanged
        assert result.sizes["epoch"] == sample_sp3_data.sizes["epoch"]

        # sid count = sv count × ~12 signals per satellite
        assert result.sizes["sid"] > sample_sp3_data.sizes["sv"] * 8

    def test_data_replication(self, sample_sp3_data):
        """Test satellite data is replicated across all its signal IDs."""
        result = map_aux_sv_to_sid(sample_sp3_data)

        # Get original position for G01
        g01_x_original = sample_sp3_data["X"].sel(sv="G01")
        first_epoch = g01_x_original.epoch.values[0]
        g01_x_original = g01_x_original.sel(epoch=first_epoch).values
        # All G01 sids should have same position
        g01_sids = [sid for sid in result.sid.values if sid.startswith("G01|")]

        for sid in g01_sids:
            sid_x = result["X"].sel(sid=sid, epoch=first_epoch).values
            np.testing.assert_almost_equal(sid_x, g01_x_original)

    def test_all_data_vars_converted(self, sample_sp3_data):
        """Test all data variables are converted."""
        result = map_aux_sv_to_sid(sample_sp3_data)

        # All original variables should exist
        for var in sample_sp3_data.data_vars:
            assert var in result.data_vars

    def test_coordinates_updated(self, sample_sp3_data):
        """Test coordinates are properly updated."""
        result = map_aux_sv_to_sid(sample_sp3_data)

        assert "sid" in result.coords
        assert "sv" not in result.coords

        # sid coordinate should be strings
        assert all(isinstance(sid, str) for sid in result.sid.values)

    def test_attributes_preserved(self, sample_sp3_data):
        """Test dataset attributes are preserved."""
        result = map_aux_sv_to_sid(sample_sp3_data)

        assert result.attrs == sample_sp3_data.attrs

    def test_fill_value_handling(self, sample_sp3_data):
        """Test custom fill value is used."""
        result = map_aux_sv_to_sid(sample_sp3_data, fill_value=-999.0)

        # Result should have same shape (all filled)
        assert result.sizes["epoch"] == sample_sp3_data.sizes["epoch"]


class TestPadToGlobalSid:
    """Test pad_to_global_sid function."""

    def test_padding_increases_sid_count(self, sample_preprocessed_sp3):
        """Test padding increases sid dimension."""
        result = pad_to_global_sid(sample_preprocessed_sp3)

        # Should have many more sids (all possible across all constellations)
        assert result.sizes["sid"] > sample_preprocessed_sp3.sizes["sid"]
        assert result.sizes["sid"] > 1000  # At least this many

    def test_original_sids_preserved(self, sample_preprocessed_sp3):
        """Test original signal IDs are preserved."""
        original_sids = set(sample_preprocessed_sp3.sid.values)
        result = pad_to_global_sid(sample_preprocessed_sp3)
        result_sids = set(result.sid.values)

        # All original sids should still be present
        assert original_sids.issubset(result_sids)

    def test_new_sids_filled_with_nan(self, sample_preprocessed_sp3):
        """Test new signal IDs are filled with NaN."""
        result = pad_to_global_sid(sample_preprocessed_sp3)

        # Find a sid that wasn't in original
        original_sids = set(sample_preprocessed_sp3.sid.values)
        new_sids = set(result.sid.values) - original_sids

        if new_sids:
            new_sid = next(iter(new_sids))
            first_epoch = result["X"].sel(sid=new_sid).epoch.values[0]
            assert np.isnan(result["X"].sel(sid=new_sid, epoch=first_epoch).values)

    def test_integer_variables_keep_dtype(self):
        """Integer variables are padded with their _FillValue, not NaN."""
        ds = xr.Dataset(
            {
                "SNR": (("sid",), np.array([40.0], dtype=np.float32)),
                "SSI": (("sid",), np.array([7], dtype=np.int8), {"_FillValue": -1}),
            },
            coords={"sid": np.array(["G01|L1|C"], dtype=object)},
        )
        result = pad_to_global_sid(ds, keep_sids=["G01|L1|C", "G02|L1|C"])

        assert result["SSI"].dtype == np.int8
        assert result["SSI"].sel(sid="G02|L1|C").item() == -1
        assert result["SSI"].sel(sid="G01|L1|C").item() == 7
        assert np.isnan(result["SNR"].sel(sid="G02|L1|C").item())

    def test_integer_variable_without_fillvalue_raises(self):
        """An integer variable without _FillValue cannot be padded."""
        ds = xr.Dataset(
            {"SSI": (("sid",), np.array([7], dtype=np.int8))},
            coords={"sid": np.array(["G01|L1|C"], dtype=object)},
        )
        with pytest.raises(ValueError, match="SSI"):
            pad_to_global_sid(ds, keep_sids=["G01|L1|C", "G02|L1|C"])

    def test_keep_sids_filtering(self, sample_preprocessed_sp3):
        """Test keep_sids parameter filters correctly."""
        keep = ["G01|L1|C", "G02|L2|W", "E01|E1|C"]
        result = pad_to_global_sid(sample_preprocessed_sp3, keep_sids=keep)

        # Result should contain ONLY sids from the keep list
        result_sids = set(result.sid.values)
        assert result_sids.issubset(set(keep))


class TestNormalizeSidDtype:
    """Test normalize_sid_dtype function."""

    def test_unicode_to_object_conversion(self):
        """Test Unicode dtype is converted to object."""
        # Create dataset with Unicode dtype
        sids = np.array(["G01|L1|C", "G02|L2|W"], dtype="<U9")
        ds = xr.Dataset({"X": (["sid"], [1.0, 2.0])}, coords={"sid": sids})

        assert ds.sid.dtype.kind == "U"

        result = normalize_sid_dtype(ds)

        assert result.sid.dtype == object

    def test_already_object_unchanged(self):
        """Test object dtype is unchanged."""
        sids = np.array(["G01|L1|C", "G02|L2|W"], dtype=object)
        ds = xr.Dataset({"X": (["sid"], [1.0, 2.0])}, coords={"sid": sids})

        result = normalize_sid_dtype(ds)

        assert result.sid.dtype == object

    def test_none_input_handled(self):
        """Test None input returns None."""
        result = normalize_sid_dtype(None)
        assert result is None


class TestStripFillvalue:
    """Test strip_fillvalue function."""

    def test_fillvalue_removed_from_attrs(self):
        """Test _FillValue is removed from attributes."""
        ds = xr.Dataset({"X": (["epoch"], [1.0, 2.0])}, coords={"epoch": [0, 1]})
        ds["X"].attrs["_FillValue"] = -999.0

        assert "_FillValue" in ds["X"].attrs

        result = strip_fillvalue(ds)

        assert "_FillValue" not in result["X"].attrs

    def test_fillvalue_removed_from_encoding(self):
        """Test _FillValue is removed from encoding."""
        ds = xr.Dataset({"X": (["epoch"], [1.0, 2.0])}, coords={"epoch": [0, 1]})
        ds["X"].encoding["_FillValue"] = -999.0

        assert "_FillValue" in ds["X"].encoding

        result = strip_fillvalue(ds)

        assert "_FillValue" not in result["X"].encoding

    def test_none_input_handled(self):
        """Test None input returns None."""
        result = strip_fillvalue(None)
        assert result is None


class TestAddFutureDatavars:
    """Test add_future_datavars function."""

    def test_new_variables_added(self):
        """Test new data variables are added."""
        ds = xr.Dataset(
            {"X": (["epoch", "sid"], np.zeros((10, 5)))},
            coords={"epoch": range(10), "sid": ["G01|L1|C"] * 5},
        )

        var_config = {
            "new_var": {
                "fill_value": -999.0,
                "dtype": "float64",
                "attrs": {"units": "m"},
            }
        }

        result = add_future_datavars(ds, var_config)

        assert "new_var" in result.data_vars
        assert result["new_var"].shape == (10, 5)
        assert result["new_var"].attrs["units"] == "m"

    def test_existing_variables_unchanged(self):
        """Test existing variables are not overwritten."""
        ds = xr.Dataset(
            {"X": (["epoch", "sid"], np.ones((10, 5)))},
            coords={"epoch": range(10), "sid": ["G01|L1|C"] * 5},
        )

        var_config = {
            "X": {  # Try to overwrite existing
                "fill_value": -999.0,
                "dtype": "float64",
                "attrs": {},
            }
        }

        result = add_future_datavars(ds, var_config)

        # X should still be all ones, not -999
        assert np.all(result["X"].values == 1.0)
