"""Tests for VodComputer — inline and bulk VOD computation strategies."""

from __future__ import annotations

import json
import unittest.mock

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from canvodpy.vod_computer import VodComputer

from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingMismatchError,
    preprocessing_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


NO_PREPROCESSING = preprocessing_record([], {"canvod-ops": "1.0.0"})


def _make_site(vod_analyses: dict | None = None):
    site = unittest.mock.MagicMock()
    site.name = "TestSite"
    site.vod_analyses = vod_analyses or {}
    site._site.preprocessing_records_for.return_value = [NO_PREPROCESSING]
    return site


def _make_ds(n_epochs: int = 5, n_sids: int = 3) -> xr.Dataset:
    epochs = pd.date_range("2025-01-01", periods=n_epochs, freq="30s")
    sids = [f"G0{i}|L1|C" for i in range(1, n_sids + 1)]
    return xr.Dataset(
        {
            "SNR": (["epoch", "sid"], np.ones((n_epochs, n_sids))),
            "theta": (["epoch", "sid"], np.full((n_epochs, n_sids), 0.5)),
            "phi": (["epoch", "sid"], np.zeros((n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


def _make_analysis_cfg(canopy: str = "canopy_01", reference: str = "reference_01"):
    cfg = unittest.mock.MagicMock()
    cfg.canopy_receiver = canopy
    cfg.reference_receiver = reference
    cfg.reference_store_group = f"{reference}_{canopy}"
    return cfg


# ---------------------------------------------------------------------------
# Construction and repr
# ---------------------------------------------------------------------------


class TestVodComputerInit:
    def test_default_rechunk(self):
        vc = VodComputer(_make_site())
        assert vc._rechunk == {"epoch": 17280, "sid": -1}

    def test_custom_rechunk(self):
        vc = VodComputer(_make_site(), rechunk={"epoch": 1000, "sid": -1})
        assert vc._rechunk["epoch"] == 1000

    def test_repr(self):
        vc = VodComputer(_make_site(), calculator="tau_omega_zeroth")
        r = repr(vc)
        assert "TestSite" in r
        assert "tau_omega_zeroth" in r


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestVodComputerStaticHelpers:
    def test_filter_time_start_only(self):
        ds = _make_ds(n_epochs=10)
        cutoff = ds.epoch.values[5]
        result = VodComputer._filter_time(ds, start=cutoff, end=None)
        assert result.sizes["epoch"] == 5

    def test_filter_time_end_only(self):
        ds = _make_ds(n_epochs=10)
        cutoff = ds.epoch.values[4]
        result = VodComputer._filter_time(ds, start=None, end=cutoff)
        assert result.sizes["epoch"] == 5

    def test_filter_time_both_bounds(self):
        ds = _make_ds(n_epochs=10)
        start = ds.epoch.values[2]
        end = ds.epoch.values[6]
        result = VodComputer._filter_time(ds, start=start, end=end)
        assert result.sizes["epoch"] == 5

    def test_filter_time_no_bounds_returns_unchanged(self):
        ds = _make_ds(n_epochs=10)
        result = VodComputer._filter_time(ds, start=None, end=None)
        assert result.sizes["epoch"] == 10

    def test_dedup_sort_removes_duplicate_epochs(self):
        epochs = pd.date_range("2025-01-01", periods=3, freq="30s")
        # Repeat the middle epoch
        dup_epochs = [epochs[0], epochs[1], epochs[1], epochs[2]]
        ds = xr.Dataset(
            {"x": (["epoch"], np.arange(4))},
            coords={"epoch": dup_epochs},
        )
        result = VodComputer._dedup_sort(ds)
        assert result.sizes["epoch"] == 3
        assert len(np.unique(result.epoch.values)) == 3

    def test_dedup_sort_preserves_sorted_unique(self):
        ds = _make_ds(n_epochs=5)
        result = VodComputer._dedup_sort(ds)
        assert result.sizes["epoch"] == 5
        assert np.all(np.diff(result.epoch.values.astype(np.int64)) > 0)

    def test_dedup_sort_sorts_unsorted_epochs(self):
        epochs = pd.date_range("2025-01-01", periods=5, freq="30s")
        shuffled = [epochs[2], epochs[0], epochs[4], epochs[1], epochs[3]]
        ds = xr.Dataset({"x": (["epoch"], np.arange(5))}, coords={"epoch": shuffled})
        result = VodComputer._dedup_sort(ds)
        assert np.all(np.diff(result.epoch.values.astype(np.int64)) > 0)


# ---------------------------------------------------------------------------
# Config and pair extraction
# ---------------------------------------------------------------------------


class TestVodComputerConfig:
    def test_get_analysis_config_known(self):
        cfg = _make_analysis_cfg()
        vc = VodComputer(_make_site({"my_analysis": cfg}))
        result = vc._get_analysis_config("my_analysis")
        assert result is cfg

    def test_get_analysis_config_unknown_raises(self):
        vc = VodComputer(_make_site({}))
        with pytest.raises(ValueError, match="not configured"):
            vc._get_analysis_config("nonexistent")

    def test_aligned_pair_happy_path(self):
        cfg = _make_analysis_cfg(canopy="c", reference="r")
        vc = VodComputer(_make_site({"a": cfg}))
        canopy_ds = _make_ds()
        ref_ds = _make_ds()
        # Reference data lives under the paired store group "r_c", never "r".
        c, r = vc._aligned_pair({"c": canopy_ds, "r_c": ref_ds}, "a")
        xr.testing.assert_identical(c, canopy_ds)
        xr.testing.assert_identical(r, ref_ds)

    def test_aligned_pair_restricts_to_shared_coords(self):
        cfg = _make_analysis_cfg(canopy="c", reference="r")
        vc = VodComputer(_make_site({"a": cfg}))
        c, r = vc._aligned_pair(
            {
                "c": _make_ds(n_epochs=5, n_sids=3),
                "r_c": _make_ds(n_epochs=4, n_sids=2),
            },
            "a",
        )
        assert dict(c.sizes) == dict(r.sizes) == {"epoch": 4, "sid": 2}

    def test_aligned_pair_missing_canopy_raises(self):
        cfg = _make_analysis_cfg(canopy="canopy_01", reference="ref_01")
        vc = VodComputer(_make_site({"a": cfg}))
        with pytest.raises(KeyError, match="canopy_01"):
            vc._aligned_pair({"ref_01": _make_ds()}, "a")

    def test_aligned_pair_missing_reference_raises(self):
        cfg = _make_analysis_cfg(canopy="canopy_01", reference="ref_01")
        vc = VodComputer(_make_site({"a": cfg}))
        with pytest.raises(KeyError, match="ref_01"):
            vc._aligned_pair({"canopy_01": _make_ds()}, "a")


# ---------------------------------------------------------------------------
# Computing and writing
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _vod_output_params(monkeypatch):
    """Default VOD output options, without reading a config file."""
    params = unittest.mock.MagicMock(store_delta_snr=False, store_radial_diff=False)
    config = unittest.mock.MagicMock()
    config.processing.params = params
    monkeypatch.setattr("canvod.config.load_config", lambda *a, **k: config)
    return params


def _day_datasets(canopy_epochs: int = 6, ref_epochs: int = 4) -> dict:
    canopy = _make_ds(n_epochs=canopy_epochs, n_sids=3)
    canopy["SNR"] = canopy["SNR"] * 30.0
    ref = _make_ds(n_epochs=ref_epochs, n_sids=2)
    ref["SNR"] = ref["SNR"] * 40.0
    return {"canopy_01": canopy, "reference_01_canopy_01": ref}


class TestVodComputerCompute:
    def test_compute_day_without_write_returns_aligned_vod(self):
        site = _make_site({"a": _make_analysis_cfg()})
        vc = VodComputer(site)

        vod_ds = vc.compute_day(_day_datasets(), "a", write=False)

        # Only epochs and signals present in both receivers.
        assert dict(vod_ds.sizes) == {"epoch": 4, "sid": 2}
        assert not vod_ds["VOD"].isnull().any()
        site._site.store_vod_analyses_batch.assert_not_called()

    def test_compute_day_all_writes_one_batch_then_metadata(self):
        analyses = {
            "a": _make_analysis_cfg(),
            "b": _make_analysis_cfg(),
        }
        site = _make_site(analyses)
        order: list[str] = []

        def write(items):
            order.append(f"write {len(items)}")
            return {}

        site._site.store_vod_analyses_batch.side_effect = write
        vc = VodComputer(site)

        with unittest.mock.patch(
            "canvodpy.vod_computer.ensure_vod_store_metadata",
            side_effect=lambda *a: order.append("metadata"),
        ):
            results = vc.compute_day_all(_day_datasets())

        assert set(results) == {"a", "b"}
        # The store metadata is checked first, then one commit for both.
        assert order == ["metadata", "write 2"]
        items = site._site.store_vod_analyses_batch.call_args.kwargs["items"]
        assert [i["commit_message"] for i in items] == [
            "VOD a 2025001",
            "VOD b 2025001",
        ]
        assert {i["calculator_name"] for i in items} == {"tau_omega"}
        assert set(items[0]["source_file_hashes"]) == {"canopy_01", "reference_01"}

    def test_source_hashes_use_aligned_epochs(self):
        site = _make_site({"a": _make_analysis_cfg()})
        vc = VodComputer(site)

        with unittest.mock.patch("canvodpy.vod_computer.ensure_vod_store_metadata"):
            vc.compute_day(_day_datasets(canopy_epochs=6, ref_epochs=4), "a")

        calls = site._site.source_file_hashes_for.call_args_list
        assert [c.args[0] for c in calls] == ["canopy_01", "reference_01_canopy_01"]
        assert all(c.args[1].sizes["epoch"] == 4 for c in calls)

    def test_vod_carries_the_receivers_preprocessing(self):
        site = _make_site({"a": _make_analysis_cfg()})
        vc = VodComputer(site)

        with unittest.mock.patch("canvodpy.vod_computer.ensure_vod_store_metadata"):
            vc.compute_day(_day_datasets(), "a")

        (item,) = site._site.store_vod_analyses_batch.call_args.kwargs["items"]
        assert json.loads(item["vod_dataset"].attrs[PREPROCESSING_ATTR]) == {
            "canopy_01": [NO_PREPROCESSING],
            "reference_01": [NO_PREPROCESSING],
        }
        calls = site._site.preprocessing_records_for.call_args_list
        assert [c.args[0] for c in calls] == ["canopy_01", "reference_01_canopy_01"]

    def test_receivers_preprocessed_differently_are_refused(self):
        site = _make_site({"a": _make_analysis_cfg()})
        aggregated = preprocessing_record(
            [
                {
                    "op": "temporal_aggregate",
                    "settings": {"freq": "1min", "method": "mean"},
                    "result": {},
                }
            ],
            {"canvod-ops": "1.0.0"},
        )
        site._site.preprocessing_records_for.side_effect = [
            [aggregated],
            [NO_PREPROCESSING],
        ]
        vc = VodComputer(site)

        with pytest.raises(PreprocessingMismatchError, match="same way"):
            vc.compute_day(_day_datasets(), "a")
        site._site.store_vod_analyses_batch.assert_not_called()

    def test_prepare_for_store_drops_encodings_without_mutating(self):
        vc = VodComputer(_make_site(), rechunk={"epoch": 2, "sid": -1})
        vod_ds = _make_ds()
        vod_ds["SNR"].encoding["dtype"] = "float32"
        vod_ds["epoch"].encoding["units"] = "seconds"

        prepared = vc._prepare_for_store(vod_ds)

        assert all(prepared[v].encoding == {} for v in prepared.variables)
        assert prepared["SNR"].chunks[0] == (2, 2, 1)
        assert vod_ds["SNR"].encoding == {"dtype": "float32"}

    def test_date_label(self):
        assert VodComputer._date_label(_make_ds()) == "2025001"
        two_days = xr.Dataset(
            coords={"epoch": pd.to_datetime(["2025-01-01", "2025-01-02"])}
        )
        assert VodComputer._date_label(two_days) == "2025001-2025002"


class TestCliVodForDay:
    """``canvodpy run`` computes through VodComputer, skipping failures."""

    def test_skips_missing_groups_and_failures(self):
        from canvodpy.cli.run import _compute_vod_for_day

        analyses = {
            "ok": _make_analysis_cfg(),
            "missing": _make_analysis_cfg(canopy="canopy_02"),
            "broken": _make_analysis_cfg(),
        }
        vc = VodComputer(_make_site(analyses))
        datasets = _day_datasets()
        real_compute_day = vc.compute_day

        def compute_day(ds, name, *, write):
            if name == "broken":
                raise ValueError("boom")
            return real_compute_day(ds, name, write=write)

        reporter = unittest.mock.MagicMock()
        with unittest.mock.patch.object(vc, "compute_day", side_effect=compute_day):
            results = _compute_vod_for_day(vc, datasets, analyses, "2025001", reporter)

        assert set(results) == {"ok"}
        xr.testing.assert_identical(
            results["ok"], vc.compute_day(datasets, "ok", write=False)
        )
        reporter.on_vod_failed.assert_called_once_with("broken", "boom")


class TestVodOutputOptions:
    def test_delta_snr_dropped_by_default(self):
        vc = VodComputer(_make_site({"a": _make_analysis_cfg()}))
        vod_ds = vc.compute_day(_day_datasets(), "a", write=False)
        assert "delta_snr" not in vod_ds
        assert vod_ds.attrs["analysis_name"] == "a"
        assert vod_ds.attrs["calculator"] == "tau_omega"

    def test_delta_snr_kept_when_enabled(self, _vod_output_params):
        _vod_output_params.store_delta_snr = True
        vc = VodComputer(_make_site({"a": _make_analysis_cfg()}))
        vod_ds = vc.compute_day(_day_datasets(), "a", write=False)
        assert "delta_snr" in vod_ds

    def test_radial_diff_when_enabled(self, _vod_output_params):
        _vod_output_params.store_radial_diff = True
        datasets = _day_datasets()
        datasets["canopy_01"]["r"] = datasets["canopy_01"]["SNR"] * 0 + 2.0e7
        datasets["reference_01_canopy_01"]["r"] = (
            datasets["reference_01_canopy_01"]["SNR"] * 0 + 2.0e7 - 5.0
        )
        vc = VodComputer(_make_site({"a": _make_analysis_cfg()}))
        vod_ds = vc.compute_day(datasets, "a", write=False)
        np.testing.assert_allclose(vod_ds["radial_diff"].values, 5.0)


class TestComputeBulkAll:
    def test_one_commit_for_all_analyses(self):
        site = _make_site({"a": _make_analysis_cfg(), "b": _make_analysis_cfg()})
        vc = VodComputer(site)
        datasets = _day_datasets()

        def entry(name, start, end):
            c, r = vc._aligned_pair(datasets, name)
            return vc._compute(c, r, name), c, r

        with (
            unittest.mock.patch.object(vc, "_compute_bulk_entry", side_effect=entry),
            unittest.mock.patch("canvodpy.vod_computer.ensure_vod_store_metadata"),
        ):
            results = vc.compute_bulk_all()

        assert set(results) == {"a", "b"}
        site._site.store_vod_analyses_batch.assert_called_once()
        items = site._site.store_vod_analyses_batch.call_args.kwargs["items"]
        assert [i["analysis_name"] for i in items] == ["a", "b"]


class TestAirflowVodTask:
    def test_calculate_vod_goes_through_vod_computer(self):
        from canvodpy.workflows import tasks

        vod_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], np.array([[1.0, 3.0], [np.nan, 2.0]]))}
        )
        site = unittest.mock.MagicMock()
        site.vod.compute_bulk_all.return_value = {"a": vod_ds}
        with unittest.mock.patch("canvodpy.api.Site", return_value=site):
            result = tasks.calculate_vod("TestSite", "2025001")

        kwargs = site.vod.compute_bulk_all.call_args.kwargs
        assert kwargs["start"].isoformat() == "2025-01-01T00:00:00"
        assert kwargs["end"].date().isoformat() == "2025-01-01"
        assert result["analyses"]["a"] == {
            "mean_vod": 2.0,
            "std_vod": pytest.approx(np.std([1.0, 3.0, 2.0])),
            "n_epochs": 2,
        }


class TestVodStoreMetadata:
    def test_failed_metadata_check_stops_before_the_write(self, monkeypatch):
        """Nothing is written when the store metadata cannot be ensured."""
        import canvod.config

        def _fail():
            raise OSError("disk full")

        monkeypatch.setattr(canvod.config, "load_config", _fail)
        site = _make_site({"a": _make_analysis_cfg()})
        vc = VodComputer(site)

        with pytest.raises(OSError, match="disk full"):
            vc.compute_day(_day_datasets(), "a")
        site._site.store_vod_analyses_batch.assert_not_called()
