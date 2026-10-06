"""Tests for temporal aggregation operation."""

import numpy as np
import pytest
import xarray as xr

from canvod.ops.temporal import TemporalAggregate, temporal_aggregate


class TestTemporalAggregate:
    def test_basic_aggregation(self, sample_ds: xr.Dataset):
        """1-second data aggregated to 1-minute bins should reduce epochs."""
        op = TemporalAggregate(freq="1min", method="mean", integer_method="first")
        out, result = op(sample_ds)

        assert result.op_name == "temporal_aggregate"
        # 120 seconds -> 2 full minutes
        assert out.sizes["epoch"] == 2
        assert out.sizes["sid"] == sample_ds.sizes["sid"]
        assert "SNR" in out.data_vars
        assert "no-op" not in result.notes

    def test_preserves_attrs(self, sample_ds: xr.Dataset):
        """Dataset attrs must survive aggregation."""
        op = TemporalAggregate(freq="1min", integer_method="first")
        out, _ = op(sample_ds)

        assert out.attrs["File Hash"] == "abc123"
        assert out.attrs["source"] == "test"

    def test_preserves_sid_only_coords(self, sample_ds: xr.Dataset):
        """sid-only coords (like sv) must pass through unchanged."""
        op = TemporalAggregate(freq="1min", integer_method="first")
        out, _ = op(sample_ds)

        assert "sv" in out.coords
        assert out.coords["sv"].dims == ("sid",)
        np.testing.assert_array_equal(
            out.coords["sv"].values, sample_ds.coords["sv"].values
        )

    def test_aggregates_phi_theta(self, sample_ds: xr.Dataset):
        """phi and theta (epoch, sid) coords should be aggregated too."""
        op = TemporalAggregate(freq="1min", integer_method="first")
        out, _ = op(sample_ds)

        assert "phi" in out.coords
        assert "theta" in out.coords
        assert out.coords["phi"].dims == ("epoch", "sid")
        assert out.coords["theta"].dims == ("epoch", "sid")

    def test_early_exit_coarse_data(self, coarse_ds: xr.Dataset):
        """Data already on the bin starts is unchanged; the result says so."""
        op = TemporalAggregate(freq="1min", integer_method="first")
        out, result = op(coarse_ds)

        assert "no-op" in result.notes
        xr.testing.assert_identical(out, coarse_ds)
        assert result.step() == {
            "op": "temporal_aggregate",
            "settings": {"freq": "1min", "method": "mean", "integer_method": "first"},
            "result": {
                "aggregated": False,
                "input_sampling_s": 60.0,
                "output_sampling_s": 60.0,
            },
        }

    def test_median_method(self, sample_ds: xr.Dataset):
        """median method should work without errors."""
        op = TemporalAggregate(freq="1min", method="median", integer_method="first")
        out, result = op(sample_ds)

        assert out.sizes["epoch"] == 2
        assert result.parameters["method"] == "median"

    def test_invalid_method_raises(self):
        """Unsupported method should raise ValueError."""
        import pytest

        with pytest.raises(ValueError, match="Unsupported aggregation method"):
            TemporalAggregate(freq="1min", method="sum", integer_method="first")

    def test_convenience_function(self, sample_ds: xr.Dataset):
        """temporal_aggregate convenience wrapper should work."""
        out = temporal_aggregate(sample_ds, freq="1min", integer_method="first")
        assert out.sizes["epoch"] == 2

    def test_result_shapes(self, sample_ds: xr.Dataset):
        """OpResult should record correct input/output shapes."""
        op = TemporalAggregate(freq="1min", integer_method="first")
        _, result = op(sample_ds)

        assert result.input_shape["epoch"] == 120
        assert result.input_shape["sid"] == 3
        assert result.output_shape["epoch"] == 2
        assert result.output_shape["sid"] == 3
        assert result.duration_seconds > 0


def _five_second_ds(snr: np.ndarray, phi: np.ndarray, start: str) -> xr.Dataset:
    epochs = np.datetime64(start, "ns") + np.arange(snr.shape[0]) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), snr, {"units": "dB-Hz"}),
            "phi": (("epoch", "sid"), phi),
        },
        coords={"epoch": epochs, "sid": [f"s{i}" for i in range(snr.shape[1])]},
    )


class TestTemporalAggregateValues:
    def test_missing_values_are_skipped(self):
        snr = np.arange(12, dtype=np.float32).reshape(12, 1)
        snr[3] = np.nan
        ds = _five_second_ds(snr, np.ones_like(snr, dtype=float), "2025-01-01")
        for method, expected in (("mean", np.nanmean(snr)), ("median", 6.0)):
            out, _ = TemporalAggregate("1min", method, integer_method="first")(ds)
            np.testing.assert_allclose(out["SNR"].values[0, 0], expected)

    def test_bin_without_values_stays_nan(self):
        snr = np.full((24, 1), np.nan, dtype=np.float32)
        snr[:12] = 30.0
        ds = _five_second_ds(snr, np.ones((24, 1)), "2025-01-01")
        out, _ = TemporalAggregate("1min", "mean", integer_method="first")(ds)
        assert out["SNR"].values[0, 0] == 30.0
        assert np.isnan(out["SNR"].values[1, 0])

    def test_keeps_dtype_and_attrs(self):
        ds = _five_second_ds(
            np.ones((12, 1), dtype=np.float32), np.ones((12, 1)), "2025-01-01"
        )
        out, _ = TemporalAggregate("1min", "mean", integer_method="first")(ds)
        assert out["SNR"].dtype == np.float32
        assert out["SNR"].attrs == {"units": "dB-Hz"}

    def test_azimuth_crossing_north(self):
        """Half the bin just west of north, half just east: north, not south."""
        phi = np.r_[np.full(6, 2 * np.pi - 0.1), np.full(6, 0.3)].reshape(12, 1)
        ds = _five_second_ds(np.ones((12, 1)), phi, "2025-01-01")
        for method in ("mean", "median"):
            out, _ = TemporalAggregate("1min", method, integer_method="first")(ds)
            np.testing.assert_allclose(out["phi"].values[0, 0], 0.1)

    def test_bins_start_at_freq_multiples(self):
        """Epochs off the bin grid are labeled with their bin start."""
        ds = _five_second_ds(np.ones((24, 1)), np.ones((24, 1)), "2025-01-01T00:00:02")
        out, _ = TemporalAggregate("1min", "mean", integer_method="first")(ds)
        np.testing.assert_array_equal(
            out["epoch"].values,
            np.array(["2025-01-01T00:00", "2025-01-01T00:01"], dtype="datetime64[ns]"),
        )

    def test_one_epoch_per_bin_off_grid_is_relabeled(self):
        """Already 1-min data not on the bin starts still gets bin labels."""
        epochs = np.datetime64("2025-01-01T00:00:02", "ns") + np.arange(
            3
        ) * np.timedelta64(60, "s")
        ds = xr.Dataset(
            {"SNR": (("epoch", "sid"), np.ones((3, 1)))},
            coords={"epoch": epochs, "sid": ["s0"]},
        )
        out, result = TemporalAggregate("1min", "mean", integer_method="first")(ds)
        assert "no-op" not in result.notes
        assert (out["epoch"].values.astype(np.int64) % 60_000_000_000 == 0).all()


def _reader_like_ds(n: int = 36, step_s: int = 5) -> xr.Dataset:
    """Shaped like a reader's output: several sid coordinates, int8 flags."""
    rng = np.random.default_rng(3)
    sids = np.array(["G01|L1|C", "G02|L1|C", "E05|E5a|Q"], dtype=object)
    shape = (n, len(sids))
    missing = rng.random(shape) < 0.3
    snr = np.where(missing, np.nan, rng.uniform(20, 50, shape)).astype("float32")
    lli = np.where(missing, -1, rng.integers(0, 3, shape)).astype("int8")
    epochs = np.datetime64("2025-01-01", "ns") + np.arange(n) * np.timedelta64(
        step_s, "s"
    )
    ds = xr.Dataset(
        {
            "SNR": (("epoch", "sid"), snr, {"units": "dB-Hz"}),
            "theta": (("epoch", "sid"), rng.uniform(0, 1.5, shape), {"units": "rad"}),
            "LLI": (("epoch", "sid"), lli, {"valid_range": [-1, 7]}),
        },
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ("sid", sids, {"long_name": "signal"}),
            "sv": ("sid", np.array(["G01", "G02", "E05"], dtype=object)),
            "band": ("sid", np.array(["L1", "L1", "E5a"], dtype=object)),
            "freq_center": ("sid", np.array([1575.42, 1575.42, 1176.45], "float32")),
        },
        attrs={"File Hash": "abc", "Software": "canVODpy"},
    )
    ds["SNR"].encoding = {"dtype": "float32"}
    return ds


class TestSignature:
    @pytest.mark.parametrize("method", ["mean", "median"])
    def test_same_signature_as_input(self, method):
        ds = _reader_like_ds()
        out, result = TemporalAggregate("1min", method, integer_method="first")(ds)

        assert list(out.data_vars) == list(ds.data_vars)
        assert list(out.coords) == list(ds.coords)
        for name, var in ds.variables.items():
            assert out[name].dims == var.dims, name
            assert out[name].dtype == var.dtype, name
            assert out[name].attrs == var.attrs, name
            assert out[name].encoding == var.encoding, name
        for name in ("sid", "sv", "band", "freq_center"):
            xr.testing.assert_identical(out[name], ds[name])
        assert out.attrs == ds.attrs
        assert result.result == {
            "aggregated": True,
            "input_sampling_s": 5.0,
            "output_sampling_s": 60.0,
        }

    @pytest.mark.parametrize("method", ["mean", "median"])
    def test_values_match_xarray_resample(self, method):
        ds = _reader_like_ds()
        out, _ = TemporalAggregate("1min", method, integer_method="first")(ds)
        expected = getattr(ds[["SNR", "theta"]].resample(epoch="1min"), method)()
        # xarray sums float32 in float32; the operation sums in float64.
        np.testing.assert_allclose(out["SNR"].values, expected["SNR"].values, rtol=1e-6)
        np.testing.assert_allclose(out["theta"].values, expected["theta"].values)

    @pytest.mark.parametrize("integer_method", ["first", "last", "middle"])
    def test_integers_take_one_value_of_the_bin(self, integer_method):
        ds = _reader_like_ds()
        out, _ = TemporalAggregate("1min", "mean", integer_method=integer_method)(ds)
        lli = ds["LLI"].values
        bins = np.arange(ds.sizes["epoch"]) // 12
        for b in range(out.sizes["epoch"]):
            for j in range(ds.sizes["sid"]):
                values = [v for v in lli[bins == b, j] if v != -1]
                index = {"first": 0, "last": -1, "middle": (len(values) - 1) // 2}
                expected = values[index[integer_method]] if values else -1
                assert out["LLI"].values[b, j] == expected

    def test_middle_of_an_even_count_is_the_earlier(self):
        ds = _five_second_ds(np.ones((12, 1)), np.ones((12, 1)), "2025-01-01")
        ds["LLI"] = (
            ("epoch", "sid"),
            np.r_[-1, -1, 1, 2, 3, 4, *[-1] * 6].reshape(12, 1),
        )
        out, _ = TemporalAggregate("1min", "mean", integer_method="middle")(ds)
        assert out["LLI"].values[0, 0] == 2

    def test_integers_are_never_averaged(self):
        """A bin of 0 and 4 gives one of them, never 2."""
        ds = _five_second_ds(np.ones((12, 1)), np.ones((12, 1)), "2025-01-01")
        ds["LLI"] = (("epoch", "sid"), np.r_[[0] * 6, [4] * 6].reshape(12, 1))
        for integer_method, expected in (("first", 0), ("last", 4), ("middle", 0)):
            out, _ = TemporalAggregate("1min", "median", integer_method=integer_method)(
                ds
            )
            assert out["LLI"].values[0, 0] == expected

    def test_integer_method_is_required(self):
        with pytest.raises(TypeError, match="integer_method"):
            TemporalAggregate("1min", "mean")  # ty: ignore[missing-argument]

    def test_unknown_integer_method_raises(self):
        with pytest.raises(ValueError, match="integer method"):
            TemporalAggregate("1min", "mean", integer_method="mean")

    def test_integer_method_is_recorded(self):
        _, result = TemporalAggregate("1min", "mean", integer_method="last")(
            _reader_like_ds()
        )
        assert result.step()["settings"]["integer_method"] == "last"

    def test_bin_without_integer_values_stays_missing(self):
        ds = _reader_like_ds()
        ds["LLI"][:12] = -1
        out, _ = TemporalAggregate("1min", "mean", integer_method="first")(ds)
        assert (out["LLI"].values[0] == -1).all()

    def test_strings_along_epoch_are_refused(self):
        ds = _reader_like_ds()
        ds["label"] = (("epoch",), np.array(["a"] * ds.sizes["epoch"], dtype=object))
        with pytest.raises(TypeError, match="label"):
            TemporalAggregate("1min", "mean", integer_method="first")(ds)
