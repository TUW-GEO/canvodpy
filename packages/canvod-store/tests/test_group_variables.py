"""Tests for variables added to a whole group, and for the append check (A22).

- An append whose variables along ``epoch`` differ from the group's is
  refused: the variable would end up shorter than the others and the group
  could no longer be opened.
- An append whose ``sid`` labels differ from the group's is refused: the
  labels are stored once per group, so it would relabel the stored data.
- ``add_group_variables`` writes only the new variables, keeps the log book
  and other subgroups, and records one group-wide log-book row.
- The preprocessing of the data already in the group then includes the
  group-wide step (``preprocessing_records``), so the guard accepts only
  later data preprocessed with that step too.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import xarray as xr
import zarr
from _helpers import new_gnss_store, new_vod_store
from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingMismatchError,
    preprocessing_record,
    preprocessing_settings,
    vod_preprocessing_record,
)

from canvod.store.prepare import (
    GroupCoordinatesMismatchError,
    GroupVariablesMismatchError,
)
from canvod.store.store import GROUP_WIDE_ACTION

_SIDS = ["G01|L1|C", "G02|L1|C"]
_STEP = {"op": "grid_assign", "settings": {"grid_type": "equal_area"}, "result": {}}
_SOFTWARE = {"canvod-ops": "1.0.0"}


def _record(steps: list[dict]) -> str:
    return preprocessing_record(steps, _SOFTWARE)


def _dataset(
    day: int,
    file_hash: str,
    record: str,
    extra: dict | None = None,
    sids: list[str] = _SIDS,
) -> xr.Dataset:
    n = 4
    epochs = np.datetime64(f"2025-01-0{day}T00:00:00", "ns") + np.arange(
        n
    ) * np.timedelta64(5, "s")
    data = {"SNR": (["epoch", "sid"], np.full((n, 2), 40.0, dtype=np.float32))}
    for name, value in (extra or {}).items():
        data[name] = (["epoch", "sid"], np.full((n, 2), value))
    return xr.Dataset(
        data,
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": sids},
        attrs={"File Hash": file_hash, PREPROCESSING_ATTR: record},
    )


@pytest.fixture
def store(tmp_path):
    store = new_gnss_store(tmp_path / "site" / "gnss_store")
    store.write_initial_group(_dataset(1, "h1", _record([])), "canopy_01")
    store.append_to_group(_dataset(2, "h2", _record([])), "canopy_01")
    return store


def _cells(store) -> xr.Dataset:
    group = store.read_group("canopy_01")
    return xr.Dataset(
        {"cell_id_x": (("epoch", "sid"), np.ones((group.sizes["epoch"], 2)))},
        coords={
            "epoch": ("epoch", group["epoch"].values, {"time_system": "GPS"}),
            "sid": group["sid"].values,
        },
    )


class TestAppendCheck:
    def test_missing_variable_refused(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)
        with pytest.raises(GroupVariablesMismatchError, match="cell_id_x"):
            store.append_to_group(_dataset(3, "h3", _record([_STEP])), "canopy_01")

    def test_extra_variable_refused(self, store) -> None:
        new = _dataset(3, "h3", _record([]), extra={"cell_id_x": 1.0})
        with pytest.raises(GroupVariablesMismatchError, match="cell_id_x"):
            store.append_to_group(new, "canopy_01")

    def test_matching_variables_appended(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)
        new = _dataset(3, "h3", _record([_STEP]), extra={"cell_id_x": 2.0})
        store.append_to_group(new, "canopy_01")

        group = store.read_group("canopy_01")
        assert group["cell_id_x"].shape == group["SNR"].shape
        assert group["cell_id_x"].values[-1].tolist() == [2.0, 2.0]


class TestAppendCoordinateCheck:
    def test_renamed_sids_refused(self, store) -> None:
        # The GLONASS names of aggregate_glonass_fdma=False, same count.
        new = _dataset(3, "h3", _record([]), sids=["G01|L1|C", "R01|G1_FDMA|C"])
        with pytest.raises(GroupCoordinatesMismatchError, match="1 of 2") as e:
            store.append_to_group(new, "canopy_01")
        assert "'G02|L1|C' -> 'R01|G1_FDMA|C'" in str(e.value)
        assert store.read_group("canopy_01")["sid"].values.tolist() == _SIDS

    def test_reordered_sids_refused(self, store) -> None:
        new = _dataset(3, "h3", _record([]), sids=_SIDS[::-1])
        with pytest.raises(GroupCoordinatesMismatchError):
            store.append_to_group(new, "canopy_01")

    def test_other_sid_count_refused(self, store) -> None:
        new = _dataset(3, "h3", _record([])).isel(sid=slice(0, 1))
        with pytest.raises(GroupCoordinatesMismatchError, match="1 labels"):
            store.append_to_group(new, "canopy_01")

    def test_same_sids_appended(self, store) -> None:
        store.append_to_group(_dataset(3, "h3", _record([])), "canopy_01")
        assert store.read_group("canopy_01").sizes["epoch"] == 12


class TestAddGroupVariables:
    def test_keeps_log_book_and_data(self, store) -> None:
        before = store.read_group("canopy_01").compute()
        rows_before = store.metadata_row_count("canopy_01")

        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)

        after = store.read_group("canopy_01").compute()
        xr.testing.assert_equal(after["SNR"], before["SNR"])
        assert after["cell_id_x"].values.tolist() == [[1.0, 1.0]] * 8
        assert store.metadata_row_count("canopy_01") == rows_before + 1
        with store.readonly_session() as session:
            log_book = store.load_metadata(session.store, "canopy_01")
        row = log_book.sort("index").row(-1, named=True)
        assert row["action"] == GROUP_WIDE_ACTION
        assert row["rinex_hash"] == ""
        assert row["start"] is None
        assert store.repo.list_branches() == {"main"}

    def test_keeps_the_group_attributes(self, store) -> None:
        def stored_attrs() -> dict:
            with store.readonly_session() as session:
                return dict(
                    zarr.open_group(session.store, mode="r", path="canopy_01").attrs
                )

        before = stored_attrs()
        cells = _cells(store)
        cells.attrs = {"File Hash": "other"}

        store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)

        assert before
        assert stored_attrs() == before

    def test_keeps_other_subgroups(self, store) -> None:
        session = store.repo.writable_session("main")
        zarr.open_group(session.store, mode="a").create_group("canopy_01/metadata/x")
        session.commit("subgroup")

        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)

        root = zarr.open_group(store.repo.readonly_session("main").store, mode="r")
        assert "canopy_01/metadata/x" in root

    def test_other_dask_chunks_written(self, store) -> None:
        """Variables computed from read_group carry its dask chunks, not the store's."""
        cells = _cells(store).chunk({"epoch": 3})

        store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)

        after = store.read_group("canopy_01").compute()
        assert after["cell_id_x"].values.tolist() == [[1.0, 1.0]] * 8

    def test_refuses_existing_variable(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)
        with pytest.raises(ValueError, match="already has"):
            store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)

    def test_refuses_other_epochs(self, store) -> None:
        cells = _cells(store).isel(epoch=slice(1, None))
        with pytest.raises(ValueError, match="exactly"):
            store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)


class TestGuardAfterGroupWideStep:
    def test_old_rows_count_with_the_step(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)

        records = store.preprocessing_records("canopy_01")
        assert [preprocessing_settings(r) for r in records] == [
            [{"op": "grid_assign", "settings": {"grid_type": "equal_area"}}]
        ]

    def test_data_with_the_step_accepted(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)
        store.check_preprocessing_matches(
            "canopy_01", _dataset(3, "h3", _record([_STEP]))
        )

    def test_data_without_the_step_refused(self, store) -> None:
        store.add_group_variables("canopy_01", _cells(store), _STEP, _SOFTWARE)
        with pytest.raises(PreprocessingMismatchError):
            store.check_preprocessing_matches(
                "canopy_01", _dataset(3, "h3", _record([]))
            )

    def test_vod_records_include_the_step(self, tmp_path) -> None:
        vod = new_vod_store(tmp_path / "site" / "vod_store")
        sources = {"canopy_01": [_record([])], "reference_01": [_record([])]}
        ds = _dataset(1, "h1", vod_preprocessing_record(sources))
        vod.write_initial_group(ds, "tau_omega/canopy_01_vs_reference_01")
        group = "tau_omega/canopy_01_vs_reference_01"
        cells = xr.Dataset(
            {"cell_id_x": (("epoch", "sid"), np.ones((4, 2)))},
            coords={
                "epoch": ("epoch", ds["epoch"].values, {"time_system": "GPS"}),
                "sid": _SIDS,
            },
        )

        vod.add_group_variables(group, cells, _STEP, _SOFTWARE)

        gridded = {"canopy_01": [_record([_STEP])], "reference_01": [_record([_STEP])]}
        vod.check_preprocessing_matches(
            group, _dataset(2, "h2", vod_preprocessing_record(gridded))
        )
        with pytest.raises(PreprocessingMismatchError):
            vod.check_preprocessing_matches(
                group, _dataset(2, "h2", vod_preprocessing_record(sources))
            )


class TestReadChunks:
    def test_read_group_uses_the_stored_chunks(self, tmp_path) -> None:
        """Reads follow the chunks a group was written with, not the settings."""
        store = new_gnss_store(tmp_path / "site" / "gnss_store")
        store.chunk_strategy = {"epoch": 2, "sid": -1}
        store.write_initial_group(_dataset(1, "h1", _record([])), "canopy_01")
        store.chunk_strategy = {"epoch": 3, "sid": -1}

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            group = store.read_group("canopy_01")

        assert group["SNR"].chunks == ((2, 2), (2,))

    def test_explicit_chunks_still_apply(self, store) -> None:
        group = store.read_group("canopy_01", chunks={"epoch": 8, "sid": -1})
        assert group["SNR"].chunks == ((8,), (2,))


class TestWriteChunks:
    """Writes that create a group store it with ``chunk_strategy``."""

    def _stored_chunks(self, store, group: str) -> tuple[int, ...]:
        with store.readonly_session() as session:
            return zarr.open_group(session.store, mode="r")[group]["SNR"].chunks

    def test_write_initial_group(self, tmp_path) -> None:
        store = new_gnss_store(tmp_path / "site" / "gnss_store")
        store.chunk_strategy = {"epoch": 3, "sid": -1}
        store.write_initial_group(_dataset(1, "h1", _record([])), "canopy_01")
        assert self._stored_chunks(store, "canopy_01") == (3, 2)

    def test_write_or_append_group_rechunks_dask_input(self, tmp_path) -> None:
        store = new_gnss_store(tmp_path / "site" / "gnss_store")
        store.chunk_strategy = {"epoch": 3, "sid": -1}
        dataset = _dataset(1, "h1", _record([])).chunk({"epoch": 2})
        store.write_or_append_group(dataset, "canopy_01")
        assert self._stored_chunks(store, "canopy_01") == (3, 2)


_DAY_1 = np.datetime64("2025-01-01", "D")
_DAY_2 = np.datetime64("2025-01-02", "D")


def _day_file(day: np.datetime64) -> xr.Dataset:
    """Three 15-min epochs of ``day``; its block holds 96 slots, 84 of padding."""
    epochs = day.astype("M8[ns]") + np.arange(3) * np.timedelta64(900, "s")
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((3, 2), 40.0, dtype=np.float32))},
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": _SIDS},
    )


def _log_row(region, file_hash: str) -> dict:
    return {
        "fname": f"/data/{file_hash}.rnx",
        "rinex_hash": file_hash,
        "start": region.start,
        "end": region.end,
        "epochs": region.epochs,
        "dataset_attrs": "{}",
        "exists": False,
        "rel_path": f"data/{file_hash}.rnx",
        "canonical_name": "",
        "physical_path": f"/data/{file_hash}.rnx",
        "action": "initial",
        "write_strategy": "skip",
        "run_id": "run-1",
        "commit_msg": "two days",
        "snapshot_id": "",
    }


@pytest.fixture
def day_block_store(tmp_path):
    """A store whose group holds two days of 15-min data, the later day first."""
    from canvod.store_metadata.io import commit_with_rebase

    from canvod.store.day_blocks import add_day_block, write_file_region

    store = new_gnss_store(tmp_path / "site" / "gnss_store")
    with store.writable_session("main") as session:
        for day in (_DAY_2, _DAY_1):
            add_day_block(session, "canopy_01", day, 900, template=_day_file(day))
            region = write_file_region(session, "canopy_01", _day_file(day))
            store.append_metadata_bulk(
                "canopy_01", [_log_row(region, str(day))], session=session
            )
        commit_with_rebase(
            session, "two days", store_path=store.store_path, config=store.settings
        )
    return store


class TestAddGroupVariablesToDayBlocks:
    def test_the_variables_of_every_slot_are_added(self, day_block_store) -> None:
        group = day_block_store.read_group("canopy_01")
        assert group.sizes["epoch"] == 2 * 96
        cells = _cells(day_block_store)
        cells["cell_id_x"] = (
            cells["cell_id_x"] * np.arange(group.sizes["epoch"])[:, None]
        )

        day_block_store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)

        after = day_block_store.read_group("canopy_01").compute()
        xr.testing.assert_equal(after["cell_id_x"], cells["cell_id_x"])
        xr.testing.assert_equal(after["SNR"], group["SNR"].compute())

    def test_the_padding_stays_missing(self, day_block_store) -> None:
        day_block_store.add_group_variables(
            "canopy_01", _cells(day_block_store), _STEP, _SOFTWARE
        )

        with day_block_store.readonly_session() as session:
            stored = xr.open_zarr(session.store, group="canopy_01", consolidated=False)
            cells = stored["cell_id_x"].values
        assert cells.shape == (2 * 180, 2)
        assert np.isnan(cells).sum() == 2 * 84 * 2

    def test_integer_variables_keep_their_dtype(self, day_block_store) -> None:
        cells = _cells(day_block_store).astype("i4")
        cells["cell_id_x"].attrs["_FillValue"] = -1

        day_block_store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)

        after = day_block_store.read_group("canopy_01")["cell_id_x"]
        assert after.dtype == np.dtype("i4")
        assert (after.values == 1).all()

    def test_variables_on_the_stored_axis_are_refused(self, day_block_store) -> None:
        with day_block_store.readonly_session() as session:
            stored = xr.open_zarr(session.store, group="canopy_01", consolidated=False)
        cells = xr.Dataset(
            {"cell_id_x": (("epoch", "sid"), np.ones((stored.sizes["epoch"], 2)))},
            coords={"epoch": stored["epoch"].values, "sid": _SIDS},
        )
        with pytest.raises(ValueError, match="exactly"):
            day_block_store.add_group_variables("canopy_01", cells, _STEP, _SOFTWARE)
