"""The preprocessing record: kept in the log book, never in the data.

A store group never mixes data preprocessed with different operations or
settings; the check reads the group's log book.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr
from _helpers import GROUP, make_synthetic_dataset
from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingMismatchError,
    preprocessing_record,
    vod_preprocessing_record,
)

from canvod.store import MyIcechunkStore

AGGREGATE = {
    "op": "temporal_aggregate",
    "settings": {"freq": "1min", "method": "median"},
    "result": {"aggregated": True, "input_sampling_s": 5.0, "output_sampling_s": 60.0},
}
SOFTWARE = {"canvod-ops": "1.0.0"}
AGGREGATED = preprocessing_record([AGGREGATE], SOFTWARE)
NONE = preprocessing_record([], SOFTWARE)


def _with_record(slot: int, record: str | None) -> xr.Dataset:
    ds = make_synthetic_dataset(slot=slot)
    if record is not None:
        ds.attrs[PREPROCESSING_ATTR] = record
    return ds


def _log_column(store: MyIcechunkStore, group: str, column: str) -> list[str]:
    with store.readonly_session("main") as session:
        table = zarr.open_group(session.store, mode="r")[f"{group}/metadata/table"]
        return [str(v) for v in table[column][:]]


def test_new_group_accepts_any(tmp_store):
    tmp_store.check_preprocessing_matches(GROUP, _with_record(0, AGGREGATED))


def test_record_goes_to_the_log_book_not_the_data(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    tmp_store.write_or_append_group(_with_record(1, AGGREGATED), group_name=GROUP)

    assert _log_column(tmp_store, GROUP, "preprocessing") == [AGGREGATED] * 2
    for attrs in _log_column(tmp_store, GROUP, "attrs"):
        assert PREPROCESSING_ATTR not in json.loads(attrs)
    stored = tmp_store.read_group(GROUP)
    assert PREPROCESSING_ATTR not in stored.attrs
    with tmp_store.readonly_session("main") as session:
        assert (
            PREPROCESSING_ATTR
            not in zarr.open_group(session.store, mode="r")[GROUP].attrs
        )


def test_results_may_differ_settings_may_not(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    from_1s = preprocessing_record(
        [{**AGGREGATE, "result": {**AGGREGATE["result"], "input_sampling_s": 1.0}}],
        {"canvod-ops": "1.0.1"},
    )
    tmp_store.write_or_append_group(_with_record(1, from_1s), group_name=GROUP)

    other_freq = preprocessing_record(
        [{**AGGREGATE, "settings": {"freq": "30s", "method": "median"}}], SOFTWARE
    )
    with pytest.raises(PreprocessingMismatchError, match="freq=30s"):
        tmp_store.write_or_append_group(_with_record(2, other_freq), group_name=GROUP)


def test_unrecorded_group_counts_as_not_preprocessed(tmp_store):
    """Groups written before the record existed hold unprocessed data."""
    tmp_store.write_or_append_group(_with_record(0, None), group_name=GROUP)
    assert _log_column(tmp_store, GROUP, "preprocessing") == [""]
    tmp_store.check_preprocessing_matches(GROUP, _with_record(1, NONE))
    with pytest.raises(PreprocessingMismatchError, match="must not mix"):
        tmp_store.write_or_append_group(_with_record(1, AGGREGATED), group_name=GROUP)


def test_format_1_records_stay_readable(tmp_store):
    """Format 1 named one version (``canvod_ops_version``); the steps are alike."""
    format_1 = json.dumps(
        {"canvod_ops_version": "0.4.0", "format_version": 1, "steps": [AGGREGATE]},
        sort_keys=True,
    )
    tmp_store.write_or_append_group(_with_record(0, format_1), group_name=GROUP)
    tmp_store.write_or_append_group(_with_record(1, AGGREGATED), group_name=GROUP)
    with pytest.raises(PreprocessingMismatchError, match="must not mix"):
        tmp_store.write_or_append_group(_with_record(2, NONE), group_name=GROUP)


def test_different_preprocessing_is_refused(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    with pytest.raises(PreprocessingMismatchError, match="temporal_aggregate"):
        tmp_store.write_or_append_group(_with_record(1, NONE), group_name=GROUP)


def test_mismatch_is_not_a_value_error():
    """A run's per-file handlers catch ValueError; the mismatch must stop it."""
    assert not issubclass(PreprocessingMismatchError, ValueError)


def test_pipeline_rows_are_json(tmp_store):
    """Rows of a run (``dataset_attrs`` as a dict) are stored as JSON."""
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    ds = _with_record(1, AGGREGATED)
    fname = Path("/data/b.rnx")
    row = {
        "fname": fname,
        "rinex_hash": "b",
        "start": ds.epoch.values[0],
        "end": ds.epoch.values[-1],
        "dataset_attrs": dict(ds.attrs),
        "action": "written",
    }
    tmp_store.append_metadata_bulk(GROUP, [row])

    attrs = _log_column(tmp_store, GROUP, "attrs")[-1]
    assert json.loads(attrs) == {
        k: v for k, v in ds.attrs.items() if k != PREPROCESSING_ATTR
    }
    assert _log_column(tmp_store, GROUP, "preprocessing")[-1] == AGGREGATED
    # The path is stored as text in the form of the operating system
    # (\data\b.rnx on Windows).
    assert _log_column(tmp_store, GROUP, "fname")[-1] == str(fname)


def test_records_of_a_time_range(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    ds = make_synthetic_dataset(slot=0)
    assert tmp_store.preprocessing_records(
        GROUP, ds.epoch.values[0], ds.epoch.values[-1]
    ) == [AGGREGATED]
    later = np.datetime64("2025-01-02T00:00")
    assert tmp_store.preprocessing_records(GROUP, later, later) == []
    assert tmp_store.preprocessing_records("missing") == []


class TestVodRecord:
    def test_receivers_preprocessed_alike(self):
        record = vod_preprocessing_record(
            {"canopy_01": [AGGREGATED], "reference_01": [AGGREGATED]}
        )
        assert json.loads(record) == {
            "canopy_01": [AGGREGATED],
            "reference_01": [AGGREGATED],
        }

    def test_receivers_preprocessed_differently(self):
        with pytest.raises(PreprocessingMismatchError, match="same way"):
            vod_preprocessing_record(
                {"canopy_01": [AGGREGATED], "reference_01": [NONE]}
            )


class TestCheckSettingsMatch:
    """The check a run makes before it processes any data."""

    def test_new_group_accepts_any(self, tmp_store):
        tmp_store.check_settings_match(GROUP, [])

    def test_same_settings_pass_other_settings_refused(self, tmp_store):
        tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
        same = [{"op": AGGREGATE["op"], "settings": AGGREGATE["settings"]}]
        tmp_store.check_settings_match(GROUP, same)

        other = [
            {
                "op": "temporal_aggregate",
                "settings": {"freq": "30s", "method": "median"},
            }
        ]
        with pytest.raises(PreprocessingMismatchError, match="this run has .*freq=30s"):
            tmp_store.check_settings_match(GROUP, other)
        with pytest.raises(PreprocessingMismatchError, match="this run has none"):
            tmp_store.check_settings_match(GROUP, [])
