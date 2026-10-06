"""``preprocess_files``: the configured operations on one receiver's day."""

import json

import numpy as np
import xarray as xr

from canvod.config.models import PreprocessingConfig
from canvod.ops import TemporalAggregate, preprocess_files
from canvod.ops.base import software_versions

CONFIG = PreprocessingConfig.model_validate(
    {
        "temporal_aggregation": {
            "freq": "1min",
            "method": "median",
            "integer_method": "first",
        },
        "grid_assignment": {"grid_type": "equal_area", "angular_resolution": 10.0},
    }
)


def _file(start: str, n: int, sids: list[str], file_hash: str, seed: int):
    rng = np.random.default_rng(seed)
    epochs = np.datetime64(start, "ns") + np.arange(n) * np.timedelta64(5, "s")
    shape = (n, len(sids))
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), rng.uniform(20, 50, shape).astype("float32")),
            "phi": (("epoch", "sid"), rng.uniform(0, 2 * np.pi, shape)),
            "theta": (("epoch", "sid"), rng.uniform(0, 1.5, shape)),
        },
        coords={
            "epoch": epochs,
            "sid": sids,
            "sv": ("sid", [s.split("|")[0] for s in sids]),
            "band": ("sid", [s.split("|")[1] for s in sids]),
            "freq_center": ("sid", [1575.42 if "L1" in s else 1227.6 for s in sids]),
        },
        attrs={"File Hash": file_hash},
    )


# 00:00:00-00:01:25 and 00:01:30-00:02:55: the 00:01 bin spans both files.
FILE_A = _file("2025-01-01T00:00:00", 18, ["G01|L1", "G02|L1"], "A", 0)
FILE_B = _file("2025-01-01T00:01:30", 18, ["G01|L1", "G03|L2"], "B", 1)


def test_nothing_set_only_records_it():
    out = preprocess_files([("a", FILE_A)], None)
    assert out[0][0] == "a"
    xr.testing.assert_identical(out[0][1].drop_attrs(), FILE_A.drop_attrs())
    assert out[0][1].attrs["File Hash"] == "A"
    assert json.loads(out[0][1].attrs["Preprocessing"]) == {
        "format_version": 2,
        "software": software_versions(["canvod-ops"]),
        "steps": [],
    }


def test_bin_spanning_two_files_uses_both():
    out = preprocess_files([("b", FILE_B), ("a", FILE_A)], CONFIG)

    # Time order; the shared bin belongs to the file with its first observation.
    assert [key for key, _ in out] == ["a", "b"]
    np.testing.assert_array_equal(
        out[0][1]["epoch"].values,
        np.array(["2025-01-01T00:00", "2025-01-01T00:01"], dtype="datetime64[ns]"),
    )
    np.testing.assert_array_equal(
        out[1][1]["epoch"].values,
        np.array(["2025-01-01T00:02"], dtype="datetime64[ns]"),
    )

    # Same values as aggregating the joined day at once.
    joined = xr.concat(
        [f.drop_vars(["sv", "band", "freq_center"]) for f in (FILE_A, FILE_B)],
        "epoch",
        join="outer",
    )
    expected, _ = TemporalAggregate("1min", "median", integer_method="first")(joined)
    got = xr.concat([ds for _, ds in out], "epoch")
    np.testing.assert_array_equal(
        got["SNR"].values, expected["SNR"].sel(sid=got["sid"]).values
    )


def test_each_file_keeps_its_attrs_and_records_the_operations():
    out = dict(preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG))
    assert out["a"].attrs["File Hash"] == "A"
    assert out["b"].attrs["File Hash"] == "B"
    record = json.loads(out["a"].attrs["Preprocessing"])
    assert out["b"].attrs["Preprocessing"] == out["a"].attrs["Preprocessing"]
    assert record["format_version"] == 2
    assert record["software"] == software_versions(["canvod-ops", "canvod-grids"])
    assert list(record["software"]) == ["canvod-grids", "canvod-ops"]
    aggregate, grid = record["steps"]
    assert aggregate == {
        "op": "temporal_aggregate",
        "settings": {"freq": "1min", "method": "median", "integer_method": "first"},
        "result": {
            "aggregated": True,
            "input_sampling_s": 5.0,
            "output_sampling_s": 60.0,
        },
    }
    assert grid["op"] == "grid_assign"
    assert grid["settings"] == {"grid_type": "equal_area", "angular_resolution": 10.0}
    assert grid["result"]["variable"] == "cell_id_equal_area_10.0deg"
    assert grid["result"]["n_cells"] > 0
    assert "cell_id_equal_area_10.0deg" in out["b"].data_vars


def test_signals_of_all_files_keep_their_coordinates():
    """All sid coordinates survive, not only one (lost before 2026-10-05)."""
    out = dict(preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG))
    for ds in out.values():
        assert list(ds["sid"].values) == ["G01|L1", "G02|L1", "G03|L2"]
        assert list(ds["sv"].values) == ["G01", "G02", "G03"]
        assert list(ds["band"].values) == ["L1", "L1", "L2"]
        assert list(ds["freq_center"].values) == [1575.42, 1575.42, 1227.6]


def test_signature_of_each_file_is_kept():
    """Same variables, dtypes, attributes as the files; only the record added."""
    out = dict(preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG))
    for key, src in (("a", FILE_A), ("b", FILE_B)):
        ds = out[key]
        assert list(ds.coords) == list(src.coords)
        assert list(ds.data_vars) == [*src.data_vars, "cell_id_equal_area_10.0deg"]
        for name, var in src.variables.items():
            assert ds[name].dtype == var.dtype, name
            assert ds[name].attrs == var.attrs, name
        assert set(ds.attrs) == {"File Hash", "Preprocessing"}


def test_file_inside_an_earlier_bin_is_left_out():
    short = _file("2025-01-01T00:00:30", 3, ["G01|L1", "G02|L1"], "S", 2)
    out = preprocess_files([("a", FILE_A), ("s", short)], CONFIG)
    assert [key for key, _ in out] == ["a"]


def test_planned_settings_are_the_recorded_settings():
    """A run compares its planned settings with stored records before it runs."""
    from canvod.config.models import preprocessing_settings
    from canvod.ops import planned_settings

    out = preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG)
    recorded = preprocessing_settings(out[0][1].attrs["Preprocessing"])
    assert planned_settings(CONFIG) == recorded
    assert [step["op"] for step in recorded] == ["temporal_aggregate", "grid_assign"]


def test_nothing_set_plans_nothing():
    from canvod.config.models import preprocessing_settings
    from canvod.ops import planned_settings

    out = preprocess_files([("a", FILE_A)], None)
    assert planned_settings(None) == []
    assert preprocessing_settings(out[0][1].attrs["Preprocessing"]) == []
