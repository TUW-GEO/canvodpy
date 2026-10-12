"""Tests for log-book column alignment, source-file provenance and overwrite order.

- Rows from the pipeline (``append_metadata_bulk``) and the store API
  (``append_metadata``) share one table; every column keeps the table's row
  count, including for tables written by versions with fewer columns.
- ``source_file_hashes`` lists every file behind a time range once, ignoring
  audit rows of files skipped as already ingested.
- ``overwrite_file_in_group`` keeps ``epoch`` monotonic when the replaced
  range lies before the latest stored data.
- The VOD store's log book records ``skip``, what VOD writes do with a result
  already in the store.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr
from _helpers import new_gnss_store, new_vod_store


def _make_dataset(start: str, n_epochs: int, file_hash: str) -> xr.Dataset:
    epochs = np.datetime64(start, "ns") + np.arange(n_epochs) * np.timedelta64(5, "s")
    return xr.Dataset(
        {"SNR": (["epoch", "sid"], np.random.rand(n_epochs, 2).astype(np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C"],
        },
        attrs={"File Hash": file_hash},
    )


def _pipeline_row(file_hash: str, start: str, end: str, action: str) -> dict:
    return {
        "fname": f"/data/{file_hash}.rnx",
        "rinex_hash": file_hash,
        "start": np.datetime64(start, "ns"),
        "end": np.datetime64(end, "ns"),
        "dataset_attrs": "{}",
        "exists": action == "skipped",
        "rel_path": f"data/{file_hash}.rnx",
        "canonical_name": "",
        "physical_path": f"/data/{file_hash}.rnx",
        "action": action,
        "write_strategy": "skip",
        "run_id": "run-1",
        "commit_msg": "msg",
        "snapshot_id": "",
    }


def _table(store, group: str) -> zarr.Group:
    with store.readonly_session("main") as session:
        return zarr.open_group(session.store, mode="r")[f"{group}/metadata/table"]


def _column_lengths(store, group: str) -> dict[str, int]:
    table = _table(store, group)
    return {col: table[col].shape[0] for col in table.array_keys()}


@pytest.fixture
def store(tmp_path: Path):
    s = new_gnss_store(tmp_path / "rinex")
    s.write_initial_group(
        dataset=_make_dataset("2025-01-01T00:00:00", 12, "h_day1"),
        group_name="canopy_01",
        commit_message="initial",
    )
    return s


def test_mixed_writers_keep_columns_aligned(store) -> None:
    n0 = _table(store, "canopy_01")["index"].shape[0]  # write_initial_group's row
    # API row first (its schema has attrs/snapshot_id, no pipeline columns)
    store.append_metadata(
        group_name="canopy_01",
        rinex_hash="h_api",
        start=np.datetime64("2025-01-01T00:00:00", "ns"),
        end=np.datetime64("2025-01-01T00:00:55", "ns"),
        snapshot_id="",
        action="write",
        commit_msg="api",
        dataset_attrs={},
    )
    # Then pipeline rows, which add fname/exists/rel_path/run_id/...
    with store.writable_session("main") as session:
        store.append_metadata_bulk(
            "canopy_01",
            [
                _pipeline_row("h1", "2025-01-02T00:00", "2025-01-02T00:14", "written"),
                _pipeline_row("h2", "2025-01-02T00:15", "2025-01-02T00:29", "written"),
            ],
            session=session,
        )
        session.commit("pipeline rows")
    # And one more API row, which lacks the pipeline-only columns
    store.append_metadata(
        group_name="canopy_01",
        rinex_hash="h_api2",
        start=np.datetime64("2025-01-03T00:00:00", "ns"),
        end=np.datetime64("2025-01-03T00:00:55", "ns"),
        snapshot_id="",
        action="write",
        commit_msg="api2",
        dataset_attrs={},
    )

    lengths = _column_lengths(store, "canopy_01")
    assert set(lengths.values()) == {n0 + 4}, lengths

    table = _table(store, "canopy_01")
    assert list(table["index"][:]) == list(range(n0 + 4))
    assert list(table["run_id"][n0:]) == ["", "run-1", "run-1", ""]
    with store.readonly_session("main") as session:
        df = store.load_metadata(session.store, "canopy_01")
    assert df.height == n0 + 4


def test_source_file_hashes_ignores_skipped_audit_rows(store) -> None:
    rows = [
        _pipeline_row("h1", "2025-01-02T00:00", "2025-01-02T00:14", "initial"),
        _pipeline_row("h2", "2025-01-02T00:15", "2025-01-02T00:29", "written"),
        _pipeline_row("h3", "2025-01-03T00:00", "2025-01-03T00:14", "written"),
        # a re-run under "skip" records audit rows for the same files
        _pipeline_row("h1", "2025-01-02T00:00", "2025-01-02T00:14", "skipped"),
        _pipeline_row("h2", "2025-01-02T00:15", "2025-01-02T00:29", "skipped"),
    ]
    with store.writable_session("main") as session:
        store.append_metadata_bulk("canopy_01", rows, session=session)
        session.commit("rows")

    hashes = store.source_file_hashes(
        "canopy_01",
        np.datetime64("2025-01-02T00:00", "ns"),
        np.datetime64("2025-01-02T23:59", "ns"),
    )
    assert hashes == ["h1", "h2"]


def test_overwrite_keeps_epoch_monotonic(store) -> None:
    store.append_to_group(
        dataset=_make_dataset("2025-01-02T00:00:00", 12, "h_day2"),
        group_name="canopy_01",
    )
    # Replace day 1, which lies before the latest stored data (day 2)
    replacement = _make_dataset("2025-01-01T00:00:00", 10, "h_day1")
    store.overwrite_file_in_group(
        dataset=replacement,
        group_name="canopy_01",
        rinex_hash="h_day1",
        start=np.datetime64("2025-01-01T00:00:00", "ns"),
        end=np.datetime64("2025-01-01T23:59:59", "ns"),
    )

    epochs = store.read_group("canopy_01").epoch.values
    assert len(epochs) == 10 + 12
    assert np.all(np.diff(epochs) > np.timedelta64(0, "ns"))


def test_vod_log_book_records_skip(tmp_path: Path) -> None:
    vod = new_vod_store(tmp_path / "site" / "vod_store")
    group = "tau_omega/canopy_01_vs_reference_01"
    vod.write_initial_group(_make_dataset("2025-01-02T00:00", 4, "h1"), group)

    with vod.readonly_session("main") as session:
        df = vod.load_metadata(session.store, group)
    assert df["write_strategy"].to_list() == ["skip"]
