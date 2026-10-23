"""Tests for auxiliary data preprocessing pipelines (prep_aux_ds and friends).

The underlying SID-space primitives (pad_to_global_sid, map_aux_sv_to_sid,
create_sv_to_sid_mapping, normalize_sid_dtype, strip_fillvalue,
add_future_datavars) moved to canvod.readers.preprocessing (see
packages/canvod-readers/tests/test_preprocessing.py for their tests) --
they only depend on canvod.readers.gnss_specs, not on anything
auxiliary-specific, and living here made canvod-readers depend on
canvod-auxiliary, which already depends on canvod-readers.
"""

import xarray as xr

from canvod.auxiliary.preprocessing import (
    prep_aux_ds,
    preprocess_aux_for_interpolation,
)


class TestPrepAuxDs:
    """Test prep_aux_ds function (complete 4-step pipeline)."""

    def test_complete_pipeline(self, sample_sp3_data):
        """Test complete preprocessing pipeline."""
        result = prep_aux_ds(sample_sp3_data)

        # Check dimension conversion
        assert "sid" in result.sizes
        assert "sv" not in result.sizes

        # Check padding applied
        assert result.sizes["sid"] > 1000

        # Check dtype normalization
        assert result.sid.dtype == object

        # Check _FillValue removed
        for var in result.data_vars:
            assert "_FillValue" not in result[var].attrs
            assert "_FillValue" not in result[var].encoding

    def test_output_structure(self, sample_sp3_data):
        """Test the output keeps the epochs and has an object sid coordinate."""
        result = prep_aux_ds(sample_sp3_data)

        # Should have these characteristics
        assert isinstance(result, xr.Dataset)
        assert result.sizes["epoch"] == sample_sp3_data.sizes["epoch"]
        assert "sid" in result.coords
        assert result.sid.dtype == object


class TestPreprocessAuxForInterpolation:
    """Test preprocess_aux_for_interpolation function."""

    def test_minimal_preprocessing(self, sample_sp3_data):
        """Test minimal preprocessing (sv→sid only)."""
        result = preprocess_aux_for_interpolation(sample_sp3_data)

        # Should have sid dimension
        assert "sid" in result.sizes
        assert "sv" not in result.sizes

        # Should NOT be padded to global sids
        assert result.sizes["sid"] < 1000

    def test_full_preprocessing_option(self, sample_sp3_data):
        """Test full preprocessing when requested."""
        result = preprocess_aux_for_interpolation(
            sample_sp3_data, full_preprocessing=True
        )

        # Should be fully preprocessed (padded)
        assert result.sizes["sid"] > 1000
        assert result.sid.dtype == object

    def test_preserves_epoch_count(self, sample_sp3_data):
        """Test epoch count is preserved."""
        result = preprocess_aux_for_interpolation(sample_sp3_data)

        assert result.sizes["epoch"] == sample_sp3_data.sizes["epoch"]


class TestPreprocessingIntegration:
    """Integration tests for preprocessing pipeline."""

    def test_sp3_to_interpolation_ready(self, sample_sp3_data):
        """Test complete workflow from SP3 to interpolation-ready."""
        # Step 1: Preprocess
        preprocessed = preprocess_aux_for_interpolation(sample_sp3_data)

        # Step 2: Verify ready for interpolation
        assert "sid" in preprocessed.sizes
        assert preprocessed.sizes["epoch"] == 96
        assert preprocessed.sizes["sid"] > 0

        # Step 3: Verify coordinates exist
        assert "epoch" in preprocessed.coords
        assert "sid" in preprocessed.coords

    def test_clk_preprocessing(self, sample_clk_data):
        """Test CLK data preprocessing."""
        preprocessed = preprocess_aux_for_interpolation(sample_clk_data)

        assert "sid" in preprocessed.sizes
        assert "clock_bias" in preprocessed.data_vars

    def test_dimension_compatibility(self, sample_sp3_data, sample_rinex_data):
        """Test preprocessed data is compatible with RINEX."""
        preprocessed = preprocess_aux_for_interpolation(sample_sp3_data)

        # Should have 'sid' dimension like RINEX
        assert "sid" in preprocessed.sizes
        assert "sid" in sample_rinex_data.sizes

        # Signal IDs should overlap
        preprocessed_sids = set(preprocessed.sid.values)
        rinex_sids = set(sample_rinex_data.sid.values)

        # Some overlap expected
        overlap = preprocessed_sids & rinex_sids
        assert len(overlap) > 0
