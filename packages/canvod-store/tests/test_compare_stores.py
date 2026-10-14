"""Tests for ``canvod.store.compare_stores`` (spec #318, seam B).

The seam is the public function, on small stores written with the test
helpers. Expected values come from the data each test builds, never
recomputed the way the comparison does.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import make_synthetic_vod_dataset, new_gnss_store, new_vod_store
from icechunk.xarray import to_icechunk

from canvod.store import DiffKind, StoreComparison, compare_stores

_SIDS = ["G01|L1|C", "G02|L1|C", "E01|L1|C", "R01|L1|C", "C01|L1|C"]
_GROUP = "canopy_01"

_UNITS = {
    "SNR": "dB-Hz",
    "Pseudorange": "m",
    "Phase": "cycles",
    "Doppler": "Hz",
    "S1C": "dB-Hz",
}


def _epochs(n: int, day: str = "2025-01-01", step_s: int = 5) -> np.ndarray:
    start = np.datetime64(f"{day}T00:00:00")
    return start + np.arange(n) * np.timedelta64(step_s, "s")


def _gnss_ds(seed: int = 0, n_epochs: int = 4) -> xr.Dataset:
    """A small GNSS dataset with the contract variables and their units."""
    rng = np.random.default_rng(seed)
    shape = (n_epochs, len(_SIDS))
    paths = {
        "SNR": (rng.uniform(30, 55, shape).astype("float32"), "float32"),
        "Pseudorange": (rng.uniform(2.0e7, 2.6e7, shape).astype("float64"), "float64"),
        "Phase": (rng.uniform(-5.0e4, 5.0e4, shape).astype("float64"), "float64"),
        "Doppler": (rng.uniform(-5.0e3, 5.0e3, shape).astype("float32"), "float32"),
        "LLI": (rng.integers(0, 2, shape).astype("int8"), "int8"),
        "SSI": (rng.integers(0, 9, shape).astype("int8"), "int8"),
        "S1C": (rng.uniform(30, 55, shape).astype("float64"), "float64"),
    }
    ds = xr.Dataset(
        {name: (("epoch", "sid"), values) for name, (values, _dtype) in paths.items()},
        coords={
            "epoch": ("epoch", _epochs(n_epochs), {"time_system": "GPS"}),
            "sid": ("sid", _SIDS),
        },
    )
    for name in paths:
        if name in _UNITS:
            ds[name].attrs["units"] = _UNITS[name]
    return ds


def _vod_ds(seed: int = 0) -> xr.Dataset:
    """A small VOD dataset with VOD, delta_snr, theta and phi and their units."""
    ds = make_synthetic_vod_dataset(slot=0, seed=seed, n_epochs=6)
    rng = np.random.default_rng(seed)
    delta_snr = rng.uniform(0, 5, ds["VOD"].shape).astype("float32")
    delta_snr[np.isnan(ds["VOD"].values)] = np.nan
    ds["delta_snr"] = (("epoch", "sid"), delta_snr)
    ds["VOD"].attrs["units"] = "1"
    ds["delta_snr"].attrs["units"] = "dB"
    ds["theta"].attrs["units"] = "rad"
    ds["phi"].attrs["units"] = "rad"
    return ds


def _write_group(store, group_name: str, ds: xr.Dataset) -> None:
    with store.writable_session("main") as session:
        to_icechunk(ds, session, group=group_name)
        session.commit("test group")


def _gnss_store(path: Path, ds: xr.Dataset, group: str = _GROUP):
    store = new_gnss_store(path)
    _write_group(store, group, ds)
    return store


def _vod_store(path: Path, ds: xr.Dataset, group: str = _GROUP):
    store = new_vod_store(path)
    _write_group(store, group, ds)
    return store


def _perturb(
    ds: xr.Dataset, var: str, cells: list[tuple[int, int]], delta: float
) -> xr.Dataset:
    """Return a deep copy of ``ds`` with ``delta`` added to ``cells`` of ``var``."""
    out = ds.copy(deep=True)
    idx = tuple(np.array(cells).T)
    values = out[var].values
    values[idx] = values[idx] + delta
    out[var].values = values
    return out


def _first_non_nan_cells(ds: xr.Dataset, var: str, n: int = 3) -> list[tuple[int, int]]:
    """The first ``n`` (epoch, sid) cells of ``var`` that hold a value."""
    idx = np.argwhere(~np.isnan(ds[var].values))
    return [tuple(int(i) for i in idx[row]) for row in range(min(n, len(idx)))]


def _float_kinds(result: StoreComparison) -> dict[str, list]:
    """Map variable name to the list of value/no-tolerance diffs for it."""
    by_name: dict[str, list] = {}
    for d in result.differences:
        if d.kind in (DiffKind.VALUE, DiffKind.NO_TOLERANCE, DiffKind.MISSING_VALUE):
            by_name.setdefault(d.variable or "", []).append(d)
    return by_name


def _value_diff(result: StoreComparison, var: str) -> list:
    return [
        d
        for d in result.differences
        if d.variable == var and d.kind in (DiffKind.VALUE, DiffKind.NO_TOLERANCE)
    ]


# --- Test 1: identical stores match ---------------------------------------


def test_identical_stores_match(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds)

    result = compare_stores(ref, new)

    assert result.matches
    assert result.differences == []
    assert result.groups_only_in_reference == []
    assert result.groups_only_in_new == []
    assert result == StoreComparison(
        groups_in_reference=1,
        groups_in_new=1,
    )


# --- Test 2: floats within / beyond tolerance -----------------------------


@pytest.mark.parametrize(
    ("build", "var", "delta_beyond"),
    [
        (_gnss_ds, "SNR", 1.5 * 5e-4),
        (_vod_ds, "VOD", 1.5 * 2e-4),
        (_vod_ds, "theta", 1.5 * 1e-6),
    ],
)
def test_float_change_above_tolerance_is_reported(
    tmp_path, build, var, delta_beyond
) -> None:
    store_factory = _vod_store if build is _vod_ds else _gnss_store
    ds = build(seed=1)
    cells = _first_non_nan_cells(ds, var)
    assert len(cells) >= 3
    ref = store_factory(tmp_path / "ref", ds)
    new = store_factory(tmp_path / "new", _perturb(ds, var, cells, delta_beyond))

    result = compare_stores(ref, new)

    diffs = _value_diff(result, var)
    assert len(diffs) == 1, [d.kind for d in result.differences]
    d = diffs[0]
    assert d.kind == DiffKind.VALUE
    assert d.n_values == 3
    assert d.largest_diff == pytest.approx(delta_beyond, abs=1e-5)
    assert d.tolerance is not None
    assert not result.matches


@pytest.mark.parametrize(
    ("build", "var", "delta_within"),
    [
        (_gnss_ds, "SNR", 0.5 * 5e-4),
        (_vod_ds, "VOD", 0.5 * 2e-4),
        (_vod_ds, "theta", 0.5 * 1e-6),
    ],
)
def test_float_change_within_tolerance_is_not_reported(
    tmp_path, build, var, delta_within
) -> None:
    ds = build(seed=1)
    cells = [(0, 0), (1, 1), (2, 2)]
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", _perturb(ds, var, cells, delta_within))

    result = compare_stores(ref, new)

    assert result.matches, [d.kind for d in result.differences]


def test_delta_snr_and_phi_tolerances_are_used(tmp_path) -> None:
    ds = _vod_ds(seed=2)
    cells = _first_non_nan_cells(ds, "delta_snr")
    assert len(cells) >= 3
    ref = _vod_store(tmp_path / "ref", ds)
    new = _vod_store(tmp_path / "new", _perturb(ds, "delta_snr", cells, 1.5 * 1e-3))

    result = compare_stores(ref, new)
    assert _value_diff(result, "delta_snr")[0].n_values == 3


# --- Test 3: a float without a tolerance is reported, named as such -------


def test_no_tolerance_float_differs_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    cells = [(0, 0), (1, 1)]
    ref = _gnss_store(tmp_path / "ref", ds)
    # S1C has no tolerance; a 1e-12 change is still reported.
    new = _gnss_store(tmp_path / "new", _perturb(ds, "S1C", cells, 1e-12))

    result = compare_stores(ref, new)

    diffs = _value_diff(result, "S1C")
    assert len(diffs) == 1
    assert diffs[0].kind == DiffKind.NO_TOLERANCE
    assert diffs[0].n_values == 2
    assert diffs[0].largest_diff == pytest.approx(1e-12, abs=1e-12)
    assert diffs[0].detail == "no tolerance set"
    assert not result.matches


# --- Test 4: exact differences are reported -------------------------------


def test_lost_epoch_is_reported(tmp_path) -> None:
    ref = _gnss_store(tmp_path / "ref", _gnss_ds(seed=0, n_epochs=4))
    new = _gnss_store(tmp_path / "new", _gnss_ds(seed=0, n_epochs=3))

    result = compare_stores(ref, new)

    kinds = {d.kind for d in result.differences}
    assert DiffKind.DIMENSION in kinds
    assert DiffKind.COORDINATE_CHANGE in kinds
    assert not result.matches


def test_extra_sid_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds_extra = _gnss_ds(seed=0).isel(sid=slice(0, 4))
    ref = _gnss_store(tmp_path / "ref", ds)  # 5 sids
    new = _gnss_store(tmp_path / "new", ds_extra)  # 4 sids (dropped C01)

    result = compare_stores(ref, new)

    assert DiffKind.DIMENSION in {d.kind for d in result.differences}
    assert not result.matches


def test_renamed_sid_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds_renamed = _gnss_ds(seed=0)
    ds_renamed.coords["sid"] = [
        "G01|L1|C",
        "G02|L1|C",
        "E01|L1|C",
        "R01|L1|C",
        "C99|L1|C",
    ]
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds_renamed)

    result = compare_stores(ref, new)

    assert DiffKind.COORDINATE_CHANGE in {d.kind for d in result.differences}
    assert not result.matches


def test_changed_integer_value_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds_int = ds.copy(deep=True)
    ds_int["LLI"].values[(0, 0)] = 9
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds_int)

    result = compare_stores(ref, new)

    assert _value_diff(result, "LLI")[0].n_values == 1
    assert not result.matches


# --- Test 5: missing values -----------------------------------------------


def test_value_missing_in_one_store_only_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds1 = ds.copy(deep=True)
    ds2 = ds.copy(deep=True)
    ds1["SNR"].values[(0, 0)] = np.nan  # missing in ref only
    ref = _gnss_store(tmp_path / "ref", ds1)
    new = _gnss_store(tmp_path / "new", ds2)

    result = compare_stores(ref, new)

    assert DiffKind.MISSING_VALUE in {d.kind for d in result.differences}
    assert not result.matches


def test_value_missing_in_both_is_equal(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds1 = ds.copy(deep=True)
    ds2 = ds.copy(deep=True)
    ds1["SNR"].values[(0, 0)] = np.nan
    ds2["SNR"].values[(0, 0)] = np.nan
    ref = _gnss_store(tmp_path / "ref", ds1)
    new = _gnss_store(tmp_path / "new", ds2)

    result = compare_stores(ref, new)

    assert result.matches


# --- Test 6: a group in one store only ------------------------------------


def test_group_in_one_store_only_is_reported(tmp_path) -> None:
    ref = _gnss_store(tmp_path / "ref", _gnss_ds(seed=0))
    new = _gnss_store(tmp_path / "new", _gnss_ds(seed=0))
    # Write a second group only to the new store.
    _write_group(new, "reference_01_canopy_01", _gnss_ds(seed=1))

    result = compare_stores(ref, new)

    assert result.groups_only_in_new == ["reference_01_canopy_01"]
    assert result.groups_only_in_reference == []
    assert not result.matches


# --- Test 7: compared vs ignored attributes --------------------------------


def test_changed_units_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds2 = _gnss_ds(seed=0)
    ds2["SNR"].attrs["units"] = "dB"
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds2)

    result = compare_stores(ref, new)

    attr_diffs = [d for d in result.differences if d.kind == DiffKind.ATTRIBUTE]
    assert any(d.variable == "SNR" and "units" in (d.detail or "") for d in attr_diffs)
    assert not result.matches


def test_changed_provenance_attribute_is_ignored(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds2 = _gnss_ds(seed=0).copy(deep=True)
    ds2.attrs["Software"] = "a different version"
    ds2.attrs["File Hash"] = "another hash"
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds2)

    result = compare_stores(ref, new)

    assert result.matches


def test_changed_store_source_format_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ref = _gnss_store(tmp_path / "ref2", ds)
    new = _gnss_store(tmp_path / "new2", ds)
    ref.set_root_attrs({"source_format": "rinex3"}, branch="main")
    new.set_root_attrs({"source_format": "sbf"}, branch="main")

    result = compare_stores(ref, new)

    attr_diffs = [d for d in result.differences if d.kind == DiffKind.ATTRIBUTE]
    assert any(d.variable == "source_format" for d in attr_diffs)
    assert not result.matches


# --- Test 8: JSON round-trip ----------------------------------------------


def test_json_round_trips(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(
        tmp_path / "new", _perturb(ds, "SNR", [(0, 0), (1, 1)], 1.5 * 5e-4)
    )
    new.set_root_attrs({"source_format": "sbf"}, branch="main")

    result = compare_stores(ref, new)

    dumped = result.model_dump_json()
    # The matches field is in the JSON, and a computed field does not break
    # model_validate_json (matches is recomputed, not read from the input).
    assert json.loads(dumped)["matches"] is False
    loaded = StoreComparison.model_validate_json(dumped)
    assert loaded == result
    assert loaded.matches is False

    # Identical stores carry matches True and still round-trip.
    same = compare_stores(ref, _gnss_store(tmp_path / "new2", ds))
    assert json.loads(same.model_dump_json())["matches"] is True
    assert StoreComparison.model_validate_json(same.model_dump_json()).matches is True


# --- Text report ------------------------------------------------------------


def test_to_text_lists_groups_sections(tmp_path) -> None:
    ref = _gnss_store(tmp_path / "ref", _gnss_ds(seed=0), group="canopy_01")
    _write_group(ref, "reference_01", _gnss_ds(seed=1))
    new = _gnss_store(tmp_path / "new", _gnss_ds(seed=2), group="new_01")

    result = compare_stores(ref, new)

    assert result.groups_only_in_reference == ["canopy_01", "reference_01"]

    text = result.to_text()
    assert "Groups only in the reference: canopy_01, reference_01" in text
    assert "Groups only in the new store: new_01" in text


def test_to_text_value_difference_line(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    ds["LLI"] = (
        ("epoch", "sid"),
        np.zeros((ds.sizes["epoch"], ds.sizes["sid"]), dtype="int8"),
    )
    ref = _gnss_store(tmp_path / "ref", ds)
    new_ds = ds.copy(deep=True)
    new_ds["LLI"].values[(0, 0)] = 7
    new = _gnss_store(tmp_path / "new", new_ds)

    result = compare_stores(ref, new)

    # The line carries group/variable, kind, count and largest difference.
    assert result.to_text() == "canopy_01/LLI: value: 1 value(s), largest |diff| 7"


# --- Datetime values use NaT -------------------------------------------------


def test_datetime_nat_in_both_is_equal(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    shape = (ds.sizes["epoch"], ds.sizes["sid"])
    ds["obs_time"] = (
        ("epoch", "sid"),
        np.full(shape, np.datetime64("NaT"), dtype="datetime64[ns]"),
    )
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds)

    result = compare_stores(ref, new)

    assert result.matches


def test_datetime_nat_in_one_store_only_is_reported(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    shape = (ds.sizes["epoch"], ds.sizes["sid"])
    ds["obs_time"] = (("epoch", "sid"), np.zeros(shape, dtype="datetime64[ns]"))
    ds_nat = ds.copy(deep=True)
    ds_nat["obs_time"].values[(0, 0)] = np.datetime64("NaT")
    ref = _gnss_store(tmp_path / "ref", ds)
    new = _gnss_store(tmp_path / "new", ds_nat)

    result = compare_stores(ref, new)

    assert DiffKind.MISSING_VALUE in {d.kind for d in result.differences}
    assert not result.matches


# --- Exact integer differences -----------------------------------------------


def test_uint8_largest_difference_is_exact(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    shape = (ds.sizes["epoch"], ds.sizes["sid"])
    ds["qc"] = (("epoch", "sid"), np.zeros(shape, dtype="uint8"))
    ref = _gnss_store(tmp_path / "ref", ds)
    new_ds = ds.copy(deep=True)
    new_ds["qc"].values[(0, 0)] = 7
    new = _gnss_store(tmp_path / "new", new_ds)

    result = compare_stores(ref, new)

    diffs = [
        d for d in result.differences if d.variable == "qc" and d.kind == DiffKind.VALUE
    ]
    assert len(diffs) == 1
    assert diffs[0].n_values == 1
    assert diffs[0].largest_diff == 7


def test_int8_largest_difference_does_not_wrap(tmp_path) -> None:
    ds = _gnss_ds(seed=0)
    shape = (ds.sizes["epoch"], ds.sizes["sid"])
    ds["qflag"] = (("epoch", "sid"), np.zeros(shape, dtype="int8"))
    ds["qflag"].values[(0, 0)] = -100
    ref = _gnss_store(tmp_path / "ref", ds)
    new_ds = ds.copy(deep=True)
    new_ds["qflag"].values[(0, 0)] = 100
    new = _gnss_store(tmp_path / "new", new_ds)

    result = compare_stores(ref, new)

    diffs = [
        d
        for d in result.differences
        if d.variable == "qflag" and d.kind == DiffKind.VALUE
    ]
    assert len(diffs) == 1
    assert diffs[0].n_values == 1
    assert diffs[0].largest_diff == 200
