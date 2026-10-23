"""The snapshot summary is updated commit by commit and equals a full rebuild.

Seam: ``commit_with_rebase`` on a GNSS store with day blocks and log
books written as a run writes them (``append_metadata_bulk``), compared
with :func:`~canvod.store_metadata.snapshot.snapshot_summary` rebuilt from
the committed snapshot (ADR 0021, #422).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
import xarray as xr
import zarr
from _helpers import new_gnss_store
from canvod.store_metadata import summary_state as summary_state_module
from canvod.store_metadata.io import commit_with_rebase
from canvod.store_metadata.snapshot import SNAPSHOT_SUMMARY_ATTR, snapshot_summary

from canvod.store.day_blocks import add_day_block

CANOPY = "canopy_01"
REFERENCE = "reference_01_canopy_01"
SIDS = ["G01|L1|C", "E11|E1|C"]
DAY0 = np.datetime64("2025-01-01", "D")
# Fangorn, near Bloemfontein (ECEF, m).
FANGORN = (5_004_310.0, 2_463_120.0, -3_084_250.0)


def _template() -> xr.Dataset:
    epoch = DAY0.astype("M8[ns]")
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.zeros((1, len(SIDS)), dtype="f4"))},
        coords={
            "epoch": xr.Variable("epoch", [epoch], {"time_system": "GPS"}),
            "sid": SIDS,
        },
    )


def _row(
    group: str,
    day: int,
    quarter: int,
    *,
    epochs: int = 180,
    tag: str = "",
    shift: float = 0,
) -> dict[str, Any]:
    """The log-book row of one 15-minute file of ``day`` (days after DAY0)."""
    start = (DAY0 + np.timedelta64(day, "D")).astype("M8[ns]") + np.timedelta64(
        15 * quarter, "m"
    )
    name = f"FANG{group[:3].upper()}_{day:03d}_{quarter:02d}.rnx"
    x, y, z = (FANGORN[0] + shift, FANGORN[1], FANGORN[2] - shift)
    return {
        "rinex_hash": f"{name}:{tag}",
        "canonical_name": name,
        "fname": name,
        "action": "written",
        "start": start,
        "end": start + np.timedelta64(895, "s"),
        "epochs": epochs,
        "attrs": json.dumps(
            {
                "APPROX POSITION X": str(x),
                "APPROX POSITION Y": str(y),
                "APPROX POSITION Z": str(z),
                "MARKER NAME": "JRRT",
            }
        ),
    }


def _commit_day(store, rows: dict[str, list[dict[str, Any]]], days: list[int]) -> None:
    """Grow the days' blocks and commit their log-book rows, as a run does."""
    session = store.repo.writable_session("main")
    for group in rows:
        for day in days:
            add_day_block(
                session, group, DAY0 + np.timedelta64(day, "D"), 5, _template()
            )
        store.append_metadata_bulk(group_name=group, rows=rows[group], session=session)
    commit_with_rebase(
        session, f"days {days}", store_path=store.store_path, config=store.settings
    )


def _assert_summary_is_a_full_rebuild(store) -> None:
    session = store.repo.readonly_session(branch="main")
    root = zarr.open_group(session.store, mode="r")
    written = root.attrs[SNAPSHOT_SUMMARY_ATTR]
    rebuilt = snapshot_summary(
        root, store.repo.get_metadata(), written["temporal"]["updated"]
    )
    assert written == json.loads(json.dumps(rebuilt))


REREAD: list[str] = []


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A GNSS store; its commits never rebuild the summary in full."""
    summary_state_module._states.clear()
    REREAD.clear()
    full = []
    real = summary_state_module.summarize_root
    monkeypatch.setattr(
        summary_state_module,
        "summarize_root",
        lambda *a, **k: full.append(1) or real(*a, **k),
    )
    refresh = summary_state_module._Group.refresh

    def recording(self, group, frame):
        result = refresh(self, group, frame)
        if result[0]:
            REREAD.append(self.path)
        return result

    monkeypatch.setattr(summary_state_module._Group, "refresh", recording)
    store = new_gnss_store(tmp_path / "store")
    yield store
    assert not full
    summary_state_module._states.clear()


def test_days_out_of_order_and_a_file_written_again(store):
    for days in ([3], [1], [2, 5]):
        _commit_day(
            store,
            {
                group: [_row(group, d, q, shift=q) for d in days for q in range(3)]
                for group in (CANOPY, REFERENCE)
            },
            days,
        )
        _assert_summary_is_a_full_rebuild(store)
    # Written again with fewer epochs and another position: replaces it.
    _commit_day(
        store,
        {CANOPY: [_row(CANOPY, 3, 0, epochs=40, tag="again", shift=50.0)]},
        [3],
    )
    _assert_summary_is_a_full_rebuild(store)
    # Every commit read only the rows it added.
    assert not REREAD


def test_a_commit_rebased_onto_another_runs_commit(store):
    _commit_day(store, {CANOPY: [_row(CANOPY, 1, 0)]}, [1])
    ours = store.repo.writable_session("main")
    add_day_block(ours, CANOPY, DAY0 + np.timedelta64(2, "D"), 5, _template())
    store.append_metadata_bulk(
        group_name=CANOPY, rows=[_row(CANOPY, 2, 0)], session=ours
    )
    # Another run (another process: its own summary state) commits the
    # reference receiver in between.
    kept = dict(summary_state_module._states)
    summary_state_module._states.clear()
    _commit_day(store, {REFERENCE: [_row(REFERENCE, 1, q) for q in range(4)]}, [1])
    summary_state_module._states.clear()
    summary_state_module._states.update(kept)
    commit_with_rebase(ours, "ours", store_path=store.store_path, config=store.settings)
    _assert_summary_is_a_full_rebuild(store)
    # The other run's rows were read as new rows, not by reading again.
    assert not REREAD


def test_a_log_book_written_anew_is_read_whole_again(store):
    _commit_day(store, {CANOPY: [_row(CANOPY, 1, q) for q in range(4)]}, [1])
    # The table written anew with other rows (as restore_metadata_table does).
    session = store.repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    del root[f"{CANOPY}/metadata/table"]
    session.commit("table written anew")
    _commit_day(store, {CANOPY: [_row(CANOPY, 1, 0, tag="new")]}, [1])
    _assert_summary_is_a_full_rebuild(store)
    assert REREAD == [CANOPY]


def test_a_failed_commit_drops_the_state(store, monkeypatch):
    _commit_day(store, {CANOPY: [_row(CANOPY, 1, 0)]}, [1])
    session = store.repo.writable_session("main")
    store.append_metadata_bulk(
        group_name=CANOPY, rows=[_row(CANOPY, 1, 1)], session=session
    )

    def fail(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail)
    with pytest.raises(RuntimeError, match="commit failed"):
        commit_with_rebase(
            session, "fails", store_path=store.store_path, config=store.settings
        )
    assert not summary_state_module._states
    _commit_day(store, {CANOPY: [_row(CANOPY, 1, 2)]}, [1])
    _assert_summary_is_a_full_rebuild(store)
