"""End-to-end tests for store ingestion guardrails.

These tests simulate real batch-write patterns (as the orchestrator does)
rather than testing individual store methods in isolation.  They verify that
the *combination* of hash checks, temporal overlap detection, and intra-batch
overlap detection prevents duplicate epochs under realistic scenarios.

Scenarios covered
-----------------
1. Daily concatenation file + 15-min sub-files in the same batch (fresh store)
2. Re-run with ``skip`` strategy does not duplicate data
3. Re-run with ``overwrite`` strategy replaces data cleanly
4. First file in batch skipped → second file becomes initial write
5. Two adjacent (non-overlapping) batches append without duplicates
6. Same file re-ingested after metadata exists is blocked
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
from _helpers import new_gnss_store

from canvod.store import MyIcechunkStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_15min_dataset(
    day: str, slot: int, n_epochs: int = 180
) -> tuple[Path, xr.Dataset]:
    """Create a 15-min sub-file dataset.

    Parameters
    ----------
    day : str
        ISO date string like ``"2025-01-01"``.
    slot : int
        Slot index (0–95 for a 24-hour day at 15-min intervals).
    n_epochs : int
        Number of epochs (180 = 15 min at 5 s).

    Returns
    -------
    tuple[Path, xr.Dataset]
        Fake file path and dataset.
    """
    base_minutes = slot * 15
    start_h, start_m = divmod(base_minutes, 60)
    end_minutes = base_minutes + 15 - 1  # last epoch is 14:55
    end_h, end_m = divmod(end_minutes, 60)

    start = f"{day}T{start_h:02d}:{start_m:02d}:00"
    end_sec = 55 if n_epochs > 1 else 0
    end = f"{day}T{end_h:02d}:{end_m:02d}:{end_sec:02d}"

    epochs = np.linspace(
        np.datetime64(start).astype("int64"),
        np.datetime64(end).astype("int64"),
        n_epochs,
    ).astype("datetime64[ns]")

    ds = xr.Dataset(
        {"SNR": (["epoch", "sid"], np.random.rand(n_epochs, 3).astype(np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C", "G03|L1|C"],
        },
        attrs={"File Hash": f"hash_{day}_slot{slot:02d}"},
    )
    fname = Path(f"/fake/data/{day}/file_slot{slot:02d}.25o")
    return fname, ds


def _make_daily_dataset(day: str, n_epochs: int = 1000) -> tuple[Path, xr.Dataset]:
    """Create a daily concatenation file dataset spanning a full day."""
    start = f"{day}T00:00:00"
    end = f"{day}T23:59:55"

    epochs = np.linspace(
        np.datetime64(start).astype("int64"),
        np.datetime64(end).astype("int64"),
        n_epochs,
    ).astype("datetime64[ns]")

    ds = xr.Dataset(
        {"SNR": (["epoch", "sid"], np.random.rand(n_epochs, 3).astype(np.float32))},
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": ["G01|L1|C", "G02|L1|C", "G03|L1|C"],
        },
        attrs={"File Hash": f"hash_{day}_daily"},
    )
    fname = Path(f"/fake/data/{day}/file_daily.25o")
    return fname, ds


def _batch_write(
    store: MyIcechunkStore,
    group_name: str,
    datasets: list[tuple[Path, xr.Dataset]],
) -> dict[str, int]:
    """Simulate the orchestrator's batch-write loop.

    Reproduces the exact pattern from ``_append_to_icechunk``:
    1. ``batch_check_existing`` for hash dedup
    2. ``check_temporal_overlaps`` for store-level overlap
    3. Intra-batch overlap detection (container files)
    4. Write loop with initial/skip/append branching

    Returns action counts.
    """
    file_hash_map = {fname: ds.attrs["File Hash"] for fname, ds in datasets}

    # --- Check 1: hash dedup against store ---
    valid_hashes = list(file_hash_map.values())
    existing_hashes = store.batch_check_existing(group_name, valid_hashes)

    # --- Check 2: temporal overlap against store metadata ---
    new_hashes = [h for h in valid_hashes if h not in existing_hashes]
    if new_hashes:
        file_intervals = []
        for fname, ds in datasets:
            h = file_hash_map[fname]
            if h and h not in existing_hashes:
                file_intervals.append(
                    (
                        h,
                        np.datetime64(ds.epoch.min().values),
                        np.datetime64(ds.epoch.max().values),
                    )
                )
        if file_intervals:
            temporal_overlaps = store.check_temporal_overlaps(
                group_name, file_intervals
            )
            existing_hashes |= temporal_overlaps

    # --- Check 3: intra-batch overlap ---
    intervals = []
    for fname, ds in datasets:
        h = file_hash_map[fname]
        if h and h not in existing_hashes:
            intervals.append(
                (
                    h,
                    np.datetime64(ds.epoch.min().values),
                    np.datetime64(ds.epoch.max().values),
                    len(ds.epoch),
                )
            )

    if len(intervals) > 1:
        for i, (h_i, s_i, e_i, _n_i) in enumerate(intervals):
            for j, (_h_j, s_j, e_j, _n_j) in enumerate(intervals):
                if i != j and s_i <= s_j and e_i >= e_j:
                    existing_hashes.add(h_i)
                    break

    # --- Write loop ---
    groups = store.list_groups() or []
    actions = {"initial": 0, "skipped": 0, "appended": 0}

    with store.writable_session("main") as session:
        for fname, ds in datasets:
            rinex_hash = file_hash_map[fname]
            exists = rinex_hash in existing_hashes

            if not exists and group_name not in groups:
                # Initial group creation
                from icechunk.xarray import to_icechunk

                to_icechunk(ds, session, group=group_name)
                groups.append(group_name)
                actions["initial"] += 1
            elif exists:
                actions["skipped"] += 1
            else:
                from icechunk.xarray import to_icechunk

                to_icechunk(ds, session, group=group_name, append_dim="epoch")
                actions["appended"] += 1

        has_writes = actions["initial"] + actions["appended"] > 0
        snapshot_id = session.commit("batch write") if has_writes else "no_writes"

    # Write metadata for non-skipped files
    for fname, ds in datasets:
        rinex_hash = file_hash_map[fname]
        exists = rinex_hash in existing_hashes
        store.append_metadata(
            group_name=group_name,
            rinex_hash=rinex_hash,
            start=np.datetime64(ds.epoch.min().values),
            end=np.datetime64(ds.epoch.max().values),
            snapshot_id=snapshot_id if not exists else "skipped",
            action="skip" if exists else "write",
            commit_msg=f"{'skip' if exists else 'write'}: {fname.name}",
            dataset_attrs=ds.attrs.copy(),
        )

    return actions


def _read_epoch_count(store: MyIcechunkStore, group: str) -> int:
    ds = store.read_group(group)
    return len(ds.epoch)


def _read_unique_epoch_count(store: MyIcechunkStore, group: str) -> int:
    ds = store.read_group(group)
    return len(np.unique(ds.epoch.values))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIntraBatchOverlap:
    """Daily concat + sub-files in the same batch on a fresh store."""

    def test_daily_file_skipped_subfiles_written(self, tmp_path: Path) -> None:
        """When a batch contains a daily file and its sub-files,
        the daily file is skipped and only the sub-files are written."""
        store = new_gnss_store(tmp_path / "store")

        # 4 sub-files + 1 daily concat (sorted: daily comes first alphabetically)
        daily_fname, daily_ds = _make_daily_dataset("2025-01-01", n_epochs=40)
        sub_datasets = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]

        # Daily file first (like sorted by filename: "daily" < "slot00")
        batch = [(daily_fname, daily_ds)] + sub_datasets

        actions = _batch_write(store, "canopy_01", batch)

        assert actions["skipped"] == 1, "Daily concat file should be skipped"
        assert actions["initial"] == 1, "First sub-file should be initial write"
        assert actions["appended"] == 3, "Remaining sub-files should be appended"
        assert _read_epoch_count(store, "canopy_01") == 40  # 4 × 10
        assert _read_unique_epoch_count(store, "canopy_01") == 40

    def test_subfiles_only_no_skips(self, tmp_path: Path) -> None:
        """Batch with only non-overlapping sub-files: nothing skipped."""
        store = new_gnss_store(tmp_path / "store")

        sub_datasets = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]
        actions = _batch_write(store, "canopy_01", sub_datasets)

        assert actions["skipped"] == 0
        assert actions["initial"] + actions["appended"] == 4
        assert _read_epoch_count(store, "canopy_01") == 40


class TestReRunIdempotency:
    """Re-running the same batch with skip strategy must not duplicate data."""

    def test_skip_strategy_no_duplicates(self, tmp_path: Path) -> None:
        """Processing the same files twice produces no duplicate epochs."""
        store = new_gnss_store(tmp_path / "store")

        sub_datasets = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]

        # First run
        actions1 = _batch_write(store, "canopy_01", sub_datasets)
        assert actions1["skipped"] == 0
        count_after_first = _read_epoch_count(store, "canopy_01")

        # Second run (same files, same hashes)
        actions2 = _batch_write(store, "canopy_01", sub_datasets)
        assert actions2["skipped"] == 4, "All files should be skipped on re-run"
        assert actions2["initial"] == 0
        assert actions2["appended"] == 0
        count_after_second = _read_epoch_count(store, "canopy_01")

        assert count_after_second == count_after_first, "Epoch count must not change"

    def test_daily_file_blocked_by_existing_subfiles(self, tmp_path: Path) -> None:
        """A daily file arriving after sub-files are already in the store
        is blocked by temporal overlap detection."""
        store = new_gnss_store(tmp_path / "store")

        # First run: write sub-files
        sub_datasets = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]
        _batch_write(store, "canopy_01", sub_datasets)
        count_after_subs = _read_epoch_count(store, "canopy_01")

        # Second run: try to add the daily concat
        daily_fname, daily_ds = _make_daily_dataset("2025-01-01", n_epochs=40)
        actions = _batch_write(store, "canopy_01", [(daily_fname, daily_ds)])

        assert actions["skipped"] == 1, (
            "Daily file should be blocked by temporal overlap"
        )
        assert _read_epoch_count(store, "canopy_01") == count_after_subs


class TestMultipleBatches:
    """Multiple non-overlapping batches append correctly."""

    def test_two_days_no_duplicates(self, tmp_path: Path) -> None:
        """Two separate day batches produce correct combined epoch count."""
        store = new_gnss_store(tmp_path / "store")

        day1 = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]
        day2 = [
            _make_15min_dataset("2025-01-02", slot=i, n_epochs=10) for i in range(4)
        ]

        _batch_write(store, "canopy_01", day1)
        _batch_write(store, "canopy_01", day2)

        total = _read_epoch_count(store, "canopy_01")
        unique = _read_unique_epoch_count(store, "canopy_01")
        assert total == 80  # 4 × 10 × 2 days
        assert unique == 80

    def test_second_batch_after_daily_overlap(self, tmp_path: Path) -> None:
        """Day 1 batch with daily concat skipped, day 2 batch appends fine."""
        store = new_gnss_store(tmp_path / "store")

        # Day 1: daily + sub-files
        daily_fname, daily_ds = _make_daily_dataset("2025-01-01", n_epochs=40)
        day1_subs = [
            _make_15min_dataset("2025-01-01", slot=i, n_epochs=10) for i in range(4)
        ]
        batch1 = [(daily_fname, daily_ds)] + day1_subs
        actions1 = _batch_write(store, "canopy_01", batch1)
        assert actions1["skipped"] == 1  # daily file

        # Day 2: clean batch
        day2 = [
            _make_15min_dataset("2025-01-02", slot=i, n_epochs=10) for i in range(4)
        ]
        actions2 = _batch_write(store, "canopy_01", day2)
        assert actions2["skipped"] == 0

        total = _read_epoch_count(store, "canopy_01")
        assert total == 80  # 40 from day1 subs + 40 from day2


class TestInitialWriteSkipped:
    """First file in sorted order gets skipped → second becomes initial."""

    def test_first_file_skipped_second_initializes(self, tmp_path: Path) -> None:
        """When the alphabetically first file is a daily concat,
        the group is initialized by the second (first sub-file)."""
        store = new_gnss_store(tmp_path / "store")

        # daily file sorts first: "aaa_daily" < "bbb_slot00"
        daily_fname = Path("/fake/aaa_daily.25o")
        daily_ds = _make_daily_dataset("2025-01-01", n_epochs=40)[1]
        daily_ds.attrs["File Hash"] = "hash_daily"

        sub_fname = Path("/fake/bbb_slot00.25o")
        sub_ds = _make_15min_dataset("2025-01-01", slot=0, n_epochs=10)[1]
        sub_ds.attrs["File Hash"] = "hash_slot00"

        batch = [(daily_fname, daily_ds), (sub_fname, sub_ds)]
        actions = _batch_write(store, "canopy_01", batch)

        assert actions["skipped"] == 1, "Daily file skipped"
        assert actions["initial"] == 1, "Sub-file becomes initial write"
        assert "canopy_01" in store.list_groups()
        assert _read_epoch_count(store, "canopy_01") == 10


class TestAppendToGroupGuardrailEndToEnd:
    """Verify append_to_group's built-in guardrail blocks overlapping data."""

    def test_append_to_group_blocks_temporal_overlap(self, tmp_path: Path) -> None:
        """append_to_group refuses to write data that overlaps existing epochs."""
        store = new_gnss_store(tmp_path / "store")

        # Write initial data
        _, ds1 = _make_15min_dataset("2025-01-01", slot=0, n_epochs=10)
        store.write_initial_group(
            dataset=ds1, group_name="canopy_01", commit_message="initial"
        )
        store.append_metadata(
            group_name="canopy_01",
            rinex_hash=ds1.attrs["File Hash"],
            start=np.datetime64(ds1.epoch.min().values),
            end=np.datetime64(ds1.epoch.max().values),
            snapshot_id="snap1",
            action="write",
            commit_msg="wrote slot0",
            dataset_attrs=ds1.attrs.copy(),
        )

        # Try to append overlapping data with a different hash
        _, ds_overlap = _make_15min_dataset("2025-01-01", slot=0, n_epochs=10)
        ds_overlap.attrs["File Hash"] = "hash_different_but_overlapping"

        store.append_to_group(
            dataset=ds_overlap, group_name="canopy_01", action="write"
        )

        # Epoch count should be unchanged
        assert _read_epoch_count(store, "canopy_01") == 10

    def test_append_to_group_allows_non_overlapping(self, tmp_path: Path) -> None:
        """append_to_group allows data that doesn't overlap."""
        store = new_gnss_store(tmp_path / "store")

        _, ds1 = _make_15min_dataset("2025-01-01", slot=0, n_epochs=10)
        store.write_initial_group(
            dataset=ds1, group_name="canopy_01", commit_message="initial"
        )
        store.append_metadata(
            group_name="canopy_01",
            rinex_hash=ds1.attrs["File Hash"],
            start=np.datetime64(ds1.epoch.min().values),
            end=np.datetime64(ds1.epoch.max().values),
            snapshot_id="snap1",
            action="write",
            commit_msg="wrote slot0",
            dataset_attrs=ds1.attrs.copy(),
        )

        # Append non-overlapping data
        _, ds2 = _make_15min_dataset("2025-01-01", slot=1, n_epochs=10)
        store.append_to_group(dataset=ds2, group_name="canopy_01", action="write")

        assert _read_epoch_count(store, "canopy_01") == 20
