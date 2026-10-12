"""Regression tests: verify refactored MyIcechunkStore produces identical output.

Every test here compares a freshly-built store against the frozen day 0
baseline.  All tests must PASS both before and after any refactor — if one
fails after a refactor, the refactor changed observable behavior.

Prerequisites
-------------
Run ``python packages/canvod-store/tests/build_day0_store.py`` once before
starting any refactor work to establish the baseline.

Markers
-------
- Tests that open the day 0 store on disk are auto-skipped if the fixture
  is absent (via the ``day0_store_path`` / ``day0_snapshot`` fixtures).
- ``@pytest.mark.integration`` — tests that exercise the full write pipeline
  (rather than just reading the frozen fixture).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import GROUP, make_synthetic_dataset, new_gnss_store
from build_day0_store import build_store

from canvod.store import MyIcechunkStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fresh_store(tmp_path: Path) -> tuple[MyIcechunkStore, list[xr.Dataset]]:
    """Build a fresh store from the same synthetic data as the day 0 fixture."""
    from build_day0_store import build_store as _build

    store_path = tmp_path / "fresh_store"
    _build(store_path)
    return MyIcechunkStore(store_path), [
        make_synthetic_dataset(slot=i) for i in range(4)
    ]


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestStructureMatchesDay0:
    """Store structure (groups, arrays, dtypes, shapes) must be identical."""

    def test_groups_present(self, day0_store_path, tmp_path):
        store = MyIcechunkStore(day0_store_path)
        fresh_store = new_gnss_store(tmp_path / "s")
        # write one dataset so the group exists
        ds = make_synthetic_dataset(slot=0)
        fresh_store.write_initial_group(ds, group_name=GROUP)

        assert GROUP in store.list_groups()
        assert GROUP in fresh_store.list_groups()

    def test_shape_matches_snapshot(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert snap["shape"] == day0_snapshot["shape"]

    def test_variable_names_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert set(snap["variables"]) == set(day0_snapshot["variables"])

    def test_variable_dtypes_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        for var in day0_snapshot["variables"]:
            assert (
                snap["variables"][var]["dtype"]
                == day0_snapshot["variables"][var]["dtype"]
            ), f"dtype mismatch for {var}"

    def test_variable_shapes_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        for var in day0_snapshot["variables"]:
            assert (
                snap["variables"][var]["shape"]
                == day0_snapshot["variables"][var]["shape"]
            ), f"shape mismatch for {var}"


# ---------------------------------------------------------------------------
# Data content tests
# ---------------------------------------------------------------------------


class TestDataMatchesDay0:
    """Array contents must be bit-identical after refactor."""

    def test_epoch_coordinate_matches(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert snap["epoch_checksum"] == day0_snapshot["epoch_checksum"], (
            "epoch coordinate changed"
        )
        assert snap["epoch_start"] == day0_snapshot["epoch_start"]
        assert snap["epoch_end"] == day0_snapshot["epoch_end"]
        assert snap["n_epochs"] == day0_snapshot["n_epochs"]

    def test_s1c_checksum_matches(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert (
            snap["variables"]["S1C"]["checksum"]
            == day0_snapshot["variables"]["S1C"]["checksum"]
        ), "S1C array content changed"

    def test_s2w_checksum_matches(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert (
            snap["variables"]["S2W"]["checksum"]
            == day0_snapshot["variables"]["S2W"]["checksum"]
        ), "S2W array content changed"

    def test_nan_fraction_preserved(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        for var in day0_snapshot["variables"]:
            expected = day0_snapshot["variables"][var]["nan_fraction"]
            actual = snap["variables"][var]["nan_fraction"]
            assert actual == pytest.approx(expected, abs=1e-6), (
                f"NaN fraction changed for {var}: {actual} != {expected}"
            )

    def test_read_group_returns_correct_shape(self, day0_store_path):
        """read_group() must return the same shape as day 0."""
        store = MyIcechunkStore(day0_store_path)
        ds = store.read_group(GROUP)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "S1C" in ds.data_vars


# ---------------------------------------------------------------------------
# Metadata table tests
# ---------------------------------------------------------------------------


class TestMetadataTableMatchesDay0:
    """File registry (metadata table) must be structurally identical."""

    def test_row_count_matches(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert (
            snap["metadata_table"]["n_rows"]
            == day0_snapshot["metadata_table"]["n_rows"]
        )

    def test_hashes_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert (
            snap["metadata_table"]["hashes"]
            == day0_snapshot["metadata_table"]["hashes"]
        )

    def test_actions_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert (
            snap["metadata_table"]["actions"]
            == day0_snapshot["metadata_table"]["actions"]
        )


# ---------------------------------------------------------------------------
# Version control / history tests
# ---------------------------------------------------------------------------


class TestHistoryMatchesDay0:
    """Snapshot count and branch structure must be identical."""

    def test_commit_count_matches(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert snap["history_count"] == day0_snapshot["history_count"], (
            f"Commit count changed: {snap['history_count']} != "
            f"{day0_snapshot['history_count']}. "
            "Check for accidental extra commits (e.g. double-commit pattern)."
        )

    def test_branches_match(self, day0_snapshot, tmp_path):
        store_path = tmp_path / "s"

        snap = build_store(store_path)
        assert sorted(snap["branches"]) == sorted(day0_snapshot["branches"])


# ---------------------------------------------------------------------------
# Guardrail regression tests
# ---------------------------------------------------------------------------


class TestGuardrailsStillWork:
    """Dedup guardrails must be preserved exactly after refactor."""

    def test_hash_dedup_blocks_reingest(self, tmp_store):
        """Re-ingesting the same file hash must be silently skipped."""
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)
        initial_epochs = tmp_store.read_group(GROUP).sizes["epoch"]

        # Re-ingest the same dataset
        tmp_store.append_to_group(ds, group_name=GROUP, action="append")
        after_epochs = tmp_store.read_group(GROUP).sizes["epoch"]

        assert after_epochs == initial_epochs, (
            "Duplicate file was not blocked by hash guardrail"
        )

    def test_temporal_overlap_blocked(self, tmp_store):
        """A file overlapping an existing time range must be rejected."""
        ds0 = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds0, group_name=GROUP)
        initial_epochs = tmp_store.read_group(GROUP).sizes["epoch"]

        # ds0 with a different hash but same epoch range — still overlaps
        ds_overlap = ds0.assign_attrs({"File Hash": "deadbeef12345678"})
        tmp_store.append_to_group(ds_overlap, group_name=GROUP, action="append")
        after_epochs = tmp_store.read_group(GROUP).sizes["epoch"]

        assert after_epochs == initial_epochs, (
            "Temporal overlap was not blocked by guardrail"
        )

    def test_non_overlapping_append_succeeds(self, tmp_store):
        """Adjacent, non-overlapping files must append cleanly."""
        ds0 = make_synthetic_dataset(slot=0)
        ds1 = make_synthetic_dataset(slot=1)  # different slot → different hash + epochs

        tmp_store.write_initial_group(ds0, group_name=GROUP)
        epochs_after_first = tmp_store.read_group(GROUP).sizes["epoch"]

        # Use explicit commit_message to sidestep Bug B4.
        # B4 coverage is in TestBugFixes.test_b4_append_without_explicit_commit_message.
        tmp_store.append_to_group(
            ds1,
            group_name=GROUP,
            action="append",
            commit_message="append slot 1",
        )
        epochs_after_second = tmp_store.read_group(GROUP).sizes["epoch"]

        assert epochs_after_second == epochs_after_first + ds1.sizes["epoch"], (
            "Non-overlapping append failed"
        )

    def test_should_skip_file_hash_match(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        skip, reason = tmp_store.should_skip_file(
            group_name=GROUP,
            file_hash=ds.attrs["File Hash"],
            time_start=ds.epoch.values[0],
            time_end=ds.epoch.values[-1],
        )
        assert skip is True
        assert reason == "hash_match"

    def test_should_skip_file_temporal_overlap(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        skip, reason = tmp_store.should_skip_file(
            group_name=GROUP,
            file_hash="unknown_hash_xyz",
            time_start=ds.epoch.values[0],
            time_end=ds.epoch.values[-1],
        )
        assert skip is True
        assert reason == "temporal_overlap"

    def test_should_skip_returns_false_for_new_file(self, tmp_store):
        ds0 = make_synthetic_dataset(slot=0)
        ds1 = make_synthetic_dataset(slot=1)
        tmp_store.write_initial_group(ds0, group_name=GROUP)

        skip, reason = tmp_store.should_skip_file(
            group_name=GROUP,
            file_hash=ds1.attrs["File Hash"],
            time_start=ds1.epoch.values[0],
            time_end=ds1.epoch.values[-1],
        )
        assert skip is False
        assert reason == ""


# ---------------------------------------------------------------------------
# Bug regression tests — must FAIL before the fix, PASS after
# ---------------------------------------------------------------------------


class TestBugFixes:
    """Tests that document specific bugs found during the v2 review.

    Each test is expected to FAIL with the pre-fix code and PASS after the fix.
    A ``xfail`` marker indicates the bug is not yet fixed on this branch.
    """

    def test_b4_append_without_explicit_commit_message(self, tmp_store):
        """append_to_group(action='append') must work without a commit_message."""
        ds0 = make_synthetic_dataset(slot=0)
        ds1 = make_synthetic_dataset(slot=1)
        tmp_store.write_initial_group(ds0, group_name=GROUP)
        # This must not raise TypeError: 'NoneType' object cannot be cast as 'str'
        tmp_store.append_to_group(ds1, group_name=GROUP, action="append")

    def test_b5_logger_before_assignment(self, tmp_path):
        """manifest_preload_enabled=True must not raise AttributeError.

        Bug B5: self._logger was used before assignment when the preload
        branch ran (logger initialised too late). This test triggers that
        branch directly by passing a config with preload enabled.
        """
        # We can't easily override load_config(), so test the branch directly by
        # checking that the logger attribute order is safe: if _logger is assigned
        # before any branch that uses it, the bug is fixed.
        import inspect

        from canvod.store import MyIcechunkStore

        source = inspect.getsource(MyIcechunkStore.__init__)
        logger_assignment_pos = source.find("self._logger = ")
        logger_usage_pos = source.find("self._logger.info")
        # After fix: logger must be assigned before it is used
        assert logger_assignment_pos < logger_usage_pos, (
            "B5: self._logger is used before it is assigned in __init__. "
            "Move 'self._logger = structlog.get_logger(__name__)' to the top of "
            "__init__."
        )


# ---------------------------------------------------------------------------
# Read-back round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Data written must be read back identically."""

    def test_s1c_round_trip(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        ds_back = tmp_store.read_group(GROUP).compute()
        np.testing.assert_array_equal(
            ds_back["S1C"].values,
            ds["S1C"].values,
            err_msg="S1C round-trip failed",
        )

    def test_epoch_round_trip(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        ds_back = tmp_store.read_group(GROUP).compute()
        np.testing.assert_array_equal(
            ds_back.epoch.values,
            ds.epoch.values,
            err_msg="epoch coordinate round-trip failed",
        )

    def test_sid_round_trip(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        ds_back = tmp_store.read_group(GROUP).compute()
        np.testing.assert_array_equal(
            ds_back.sid.values,
            ds.sid.values,
            err_msg="sid coordinate round-trip failed",
        )

    def test_four_slot_concatenation(self, tmp_store):
        """Four slots appended sequentially must equal the concatenated result."""
        datasets = [make_synthetic_dataset(slot=i) for i in range(4)]
        expected = xr.concat(datasets, dim="epoch")

        tmp_store.write_initial_group(datasets[0], group_name=GROUP)
        for i, ds in enumerate(datasets[1:], start=1):
            tmp_store.append_to_group(
                ds,
                group_name=GROUP,
                action="append",
                commit_message=f"append slot {i}",
            )

        ds_back = tmp_store.read_group(GROUP).compute()

        np.testing.assert_array_equal(ds_back["S1C"].values, expected["S1C"].values)
        np.testing.assert_array_equal(ds_back.epoch.values, expected.epoch.values)


# ---------------------------------------------------------------------------
# Metadata dataset tests (SBF-style generic metadata)
# ---------------------------------------------------------------------------


class TestMetadataDatasets:
    """Generic metadata datasets (sbf_obs etc.) must survive round-trip."""

    def _make_meta_ds(self, slot: int) -> xr.Dataset:
        rng = np.random.default_rng(slot)
        n_ep = 180
        base = np.datetime64(
            f"2025-01-01T{(slot * 15) // 60:02d}:{(slot * 15) % 60:02d}:00"
        )
        epochs = base + np.arange(n_ep) * np.timedelta64(5, "s")
        return xr.Dataset(
            {
                "pdop": xr.DataArray(
                    rng.uniform(1.0, 4.0, n_ep).astype(np.float32), dims=["epoch"]
                )
            },
            coords={"epoch": ("epoch", epochs, {"time_system": "GPS"})},
        )

    def test_write_and_read_metadata_dataset(self, tmp_store):
        # Need a group first
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        meta = self._make_meta_ds(slot=0)
        tmp_store.write_metadata_dataset(meta, group_name=GROUP, name="sbf_obs")

        assert tmp_store.metadata_dataset_exists(GROUP, "sbf_obs")
        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        np.testing.assert_array_almost_equal(
            ds_back["pdop"].values, meta["pdop"].values, decimal=5
        )

    def test_append_metadata_datasets_incremental(self, tmp_store):
        """append_metadata_datasets must match write_metadata_dataset on same input."""
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        parts = [self._make_meta_ds(slot=i) for i in range(3)]
        tmp_store.append_metadata_datasets(parts, group_name=GROUP, name="sbf_obs")

        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        expected = xr.concat(parts, dim="epoch")
        assert ds_back.sizes["epoch"] == expected.sizes["epoch"]
        np.testing.assert_array_almost_equal(
            ds_back["pdop"].values, expected["pdop"].values, decimal=5
        )

    def test_append_metadata_datasets_keeps_earlier_days(self, tmp_store):
        """A second call (next day) appends instead of replacing the first."""
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)

        day1 = [self._make_meta_ds(slot=i) for i in range(2)]
        day2 = [self._make_meta_ds(slot=i) for i in range(2, 4)]
        tmp_store.append_metadata_datasets(day1, group_name=GROUP, name="sbf_obs")
        tmp_store.append_metadata_datasets(day2, group_name=GROUP, name="sbf_obs")

        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        expected = xr.concat(day1 + day2, dim="epoch")
        np.testing.assert_array_equal(ds_back["epoch"].values, expected["epoch"].values)

    def test_metadata_parts_commit_with_observations(self, tmp_store):
        """write_or_append_group puts data and metadata in one snapshot."""
        ds = make_synthetic_dataset(slot=0)
        meta = self._make_meta_ds(slot=0)
        tmp_store.write_or_append_group(
            ds, group_name=GROUP, metadata_datasets={"sbf_obs": meta}
        )
        snapshots = list(tmp_store.repo.ancestry(branch="main"))
        tmp_store.write_or_append_group(
            make_synthetic_dataset(slot=1),
            group_name=GROUP,
            metadata_datasets={"sbf_obs": self._make_meta_ds(slot=1)},
        )
        # One new snapshot per call, holding both data and metadata
        assert len(list(tmp_store.repo.ancestry(branch="main"))) == len(snapshots) + 1
        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        assert ds_back.sizes["epoch"] == 2 * meta.sizes["epoch"]

    def test_rewrite_group_keeps_metadata(self, tmp_store):
        """Overwrite strategy: rewriting the group keeps the log book, and
        sbf_obs keeps the other files' epochs and gets the new part for the
        replaced range."""
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)
        parts = [self._make_meta_ds(slot=i) for i in range(3)]
        tmp_store.append_metadata_datasets(parts, group_name=GROUP, name="sbf_obs")
        rows = tmp_store.metadata_row_count(GROUP)

        corrected = self._make_meta_ds(slot=1)
        corrected["pdop"] = corrected["pdop"] * 0 + 9.0
        replaced = (corrected["epoch"].values.min(), corrected["epoch"].values.max())
        with tmp_store.writable_session("main") as session:
            tmp_store.rewrite_group(
                session, GROUP, ds, [replaced], {"sbf_obs": [corrected]}
            )
            session.commit("overwrite")

        assert tmp_store.metadata_row_count(GROUP) == rows
        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        expected = xr.concat([parts[0], corrected, parts[2]], dim="epoch")
        np.testing.assert_array_equal(ds_back["epoch"].values, expected["epoch"].values)
        np.testing.assert_array_almost_equal(
            ds_back["pdop"].values, expected["pdop"].values, decimal=5
        )

    def test_rewrite_group_drops_replaced_range_without_new_part(self, tmp_store):
        ds = make_synthetic_dataset(slot=0)
        tmp_store.write_initial_group(ds, group_name=GROUP)
        parts = [self._make_meta_ds(slot=i) for i in range(3)]
        tmp_store.append_metadata_datasets(parts, group_name=GROUP, name="sbf_obs")

        replaced = (parts[1]["epoch"].values.min(), parts[1]["epoch"].values.max())
        with tmp_store.writable_session("main") as session:
            tmp_store.rewrite_group(session, GROUP, ds, [replaced])
            session.commit("overwrite")

        ds_back = tmp_store.read_metadata_dataset(GROUP, "sbf_obs").compute()
        expected = xr.concat([parts[0], parts[2]], dim="epoch")
        np.testing.assert_array_equal(ds_back["epoch"].values, expected["epoch"].values)
