"""Tests for RinexDataProcessor's cross-group fork/merge batch write path.

dev/cross_group_fork_merge_plan.md. Exercises `_prepare_group_write` /
`_write_group_into_fork` / `_write_receiver_batch_forked` directly against a
real throwaway Icechunk store, via a minimal `RinexDataProcessor` subclass
that skips the real (heavy, Config/Site-coupled) `__init__` and only sets
the handful of attributes the batch-write path actually touches. There's no
existing precedent for constructing a full `RinexDataProcessor` in tests
(nothing in this suite does), and the underlying fork/merge primitive itself
is already covered by `_cooperative_distributed_writing`'s existing
intra-group use -- these tests target the new orchestration logic on top of
it: pre-pass reconciliation for new groups, action/metadata bookkeeping, and
fail-fast merge/commit semantics.

The "overwrite" strategy still goes through `_append_to_icechunk`; its
tests at the end check that the promote to main never drops a commit made
to main meanwhile.

Note on commit count: a batch that creates brand-new groups costs *two*
commits (a sequential pre-pass commit, then the fork/merge batch commit),
not one -- verified empirically that a session can't have its own pending
writes before `.fork()` is called on it (`session.merge(fork)` silently
drops the fork's data in that case), so the pre-pass must commit on its own
clean session before the fork/merge phase opens a fresh one. A batch with
only pre-existing groups still costs exactly one commit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import structlog
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.store import MyIcechunkStore
from canvod.store_metadata.testing import create_test_store, give_test_metadata

_SIDS = [f"G{i:02d}|L1|C" for i in range(1, 6)]


def _make_ds(
    file_id: str, slot: int, n_epochs: int = 10, day: str = "2025-03-28"
) -> xr.Dataset:
    """Small synthetic (epoch, sid) dataset with the required "File Hash" attr.

    ``slot`` offsets the epoch range so distinct files in a batch don't
    temporally overlap -- the dedup guardrail's temporal-overlap check
    (correctly) treats overlapping ranges as duplicates, same as
    `make_synthetic_dataset`'s ``slot`` param in
    ``packages/canvod-store/tests/_helpers.py``.
    """
    base = np.datetime64(f"{day}T00:00:00") + slot * n_epochs * np.timedelta64(5, "s")
    epochs = base + np.arange(n_epochs) * np.timedelta64(5, "s")
    rng = np.random.default_rng(
        int(hashlib.sha256(file_id.encode()).hexdigest()[:8], 16)
    )
    s1c = rng.uniform(30.0, 55.0, (n_epochs, len(_SIDS))).astype(np.float32)
    return xr.Dataset(
        {"S1C": xr.DataArray(s1c, dims=["epoch", "sid"])},
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": _SIDS},
        attrs={
            "File Hash": hashlib.sha256(file_id.encode()).hexdigest()[:16],
            "canonical_name": file_id,
            "physical_path": file_id,
        },
    )


class _FakeSite:
    def __init__(self, store: MyIcechunkStore) -> None:
        self.gnss_store = store
        self.site_name = "testsite"


class _FakeYyyyDoy:
    def __str__(self) -> str:
        return "2025087"

    def to_str(self) -> str:
        return "2025087"


class _FakeMatchedDataDirs:
    yyyydoy = _FakeYyyyDoy()


class _TestProcessor(RinexDataProcessor):
    """Minimal RinexDataProcessor stand-in for the batch-write path only."""

    def __init__(self, store: MyIcechunkStore, strategy: str = "skip") -> None:
        self.site = _FakeSite(store)
        self.matched_data_dirs = _FakeMatchedDataDirs()
        self._logger = structlog.get_logger(__name__)
        self._icechunk_log = structlog.get_logger(__name__)
        self._gnss_store_strategy = strategy
        self._keeper_tags_enabled = False
        self._config = SimpleNamespace(sites=SimpleNamespace(sites={}))
        self._reader_name = "rinex3"

    def _ensure_gnss_store_metadata(self, receivers, reader_format) -> None:
        """The ``store`` fixture has its metadata: these tests are about the
        batch writes (metadata first is tested in canvod-store-metadata and
        end to end).
        """


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "throwaway_store"
    store_path.mkdir()
    store = MyIcechunkStore(create_test_store(store_path))
    give_test_metadata(store_path)
    return store


def _group_input(name: str, files: list[tuple[Path, xr.Dataset]]):
    return (name, files, [f for f, _ in files], None, None, "rinex3")


def _warm_up_source_format(proc: _TestProcessor) -> None:
    """Consume the store's one-time ``source_format`` root-attr commit.

    `MyIcechunkStore.set_root_attrs` (STEP 7, fired once per store on the
    first-ever write when ``source_format`` is still ``None``) does its own
    separate commit -- unrelated to the pre-pass/batch commits under test.
    Call this first in any test that asserts an exact commit count on a
    fresh store, on a throwaway group name, so the real assertions aren't
    coupled to this orthogonal one-time side effect.
    """
    proc._write_receiver_batch_forked(
        [_group_input("_warmup", [(Path("warmup.rnx"), _make_ds("warmup", slot=0))])]
    )


def test_case_a_steady_state_writes_to_two_pre_existing_groups(
    store: MyIcechunkStore,
) -> None:
    """Two pre-existing groups, write new files to each via the batch path."""
    proc = _TestProcessor(store)

    seed_ref = [(Path("ref_seed.rnx"), _make_ds("ref_seed", slot=0))]
    seed_can = [(Path("can_seed.rnx"), _make_ds("can_seed", slot=0))]
    proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", seed_ref),
            _group_input("canopy_01", seed_can),
        ],
    )
    assert set(store.list_groups() or []) == {"reference_01", "canopy_01"}

    ref_files = [
        (Path("ref_2.rnx"), _make_ds("ref_2", slot=1)),
        (Path("ref_3.rnx"), _make_ds("ref_3", slot=2)),
    ]
    can_files = [(Path("can_2.rnx"), _make_ds("can_2", slot=1))]

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", ref_files),
            _group_input("canopy_01", can_files),
        ],
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1, (
        "a batch with only pre-existing groups (no pre-pass) must be exactly "
        "one shared commit, not one per group"
    )
    assert results["reference_01"].actions["written"] == 2
    assert results["canopy_01"].actions["written"] == 1

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 30  # seed(10) + 2 new(10 each)
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 20  # seed(10) + 1 new(10)

    assert store.metadata_row_count("reference_01") == 3
    assert store.metadata_row_count("canopy_01") == 2


def test_case_b_new_groups_pre_pass_creates_both_before_any_fork(
    store: MyIcechunkStore,
) -> None:
    """Two never-seen groups in one batch.

    The sequential pre-pass must create both groups (on its own committed
    session) before any fork runs, so `Session.merge()` never has to
    reconcile two forks that each independently create a sibling group --
    an unverified case per dev/cross_group_fork_merge_plan.md §4. Also
    verifies the pre-pass's consumed file isn't double-written or
    double-counted in the subsequent fork write (§4 reconciliation fix), and
    that this costs exactly two commits (pre-pass + batch), not one.
    """
    proc = _TestProcessor(store)
    _warm_up_source_format(proc)
    ref_files = [(Path(f"ref_{i}.rnx"), _make_ds(f"ref_{i}", slot=i)) for i in range(3)]
    can_files = [(Path(f"can_{i}.rnx"), _make_ds(f"can_{i}", slot=i)) for i in range(2)]

    assert set(store.list_groups() or []) == {"_warmup"}
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", ref_files),
            _group_input("canopy_01", can_files),
        ],
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 2, (
        "a batch creating new groups must cost exactly two commits: the "
        "sequential pre-pass, then the fork/merge batch"
    )
    assert set(store.list_groups() or []) == {"_warmup", "reference_01", "canopy_01"}
    assert results["reference_01"].actions == {
        "initial": 1,
        "skipped": 0,
        "appended": 0,
        "written": 2,
    }
    assert results["canopy_01"].actions == {
        "initial": 1,
        "skipped": 0,
        "appended": 0,
        "written": 1,
    }

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 30  # 3 files x 10 epochs, none dropped/doubled
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 20

    # The pre-pass-consumed file must appear exactly once in the metadata
    # table (not zero -- dropped -- and not two -- double-written).
    assert store.metadata_row_count("reference_01") == 3
    assert store.metadata_row_count("canopy_01") == 2


def test_case_b_single_file_new_group_needs_no_fork(store: MyIcechunkStore) -> None:
    """A brand-new group whose only file is fully consumed by the pre-pass
    still produces a correct result with no fork/thread involved -- the
    empty-plan-after-trim path (`plans = {... if aug}` filters it out), and
    costs exactly one commit (the pre-pass alone; the fork/merge phase never
    opens a session since `plans` is empty)."""
    proc = _TestProcessor(store)
    _warm_up_source_format(proc)
    ref_files = [(Path("ref_only.rnx"), _make_ds("ref_only", slot=0))]

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [_group_input("reference_01", ref_files)]
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1
    assert results["reference_01"].actions["initial"] == 1
    assert results["reference_01"].fork is None
    assert results["reference_01"].snapshot_id is not None
    assert set(store.list_groups() or []) == {"_warmup", "reference_01"}
    ds = store.read_group("reference_01").compute()
    assert ds.sizes["epoch"] == 10
    assert store.metadata_row_count("reference_01") == 1


def test_case_c_fail_fast_no_partial_merge(
    store: MyIcechunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If one group's write raises, nothing merges or commits.

    Under one shared batch commit, "groups before the failure stay
    committed" (today's sequential-loop property) is structurally
    impossible -- so a failing group must prevent the *whole* batch commit
    from landing, not just itself (dev/cross_group_fork_merge_plan.md §6).
    """
    proc = _TestProcessor(store)

    # Seed two pre-existing groups so this batch only exercises fork writes
    # (not the pre-pass), isolating the fail-fast path under test.
    proc._write_receiver_batch_forked(
        [
            _group_input(
                "reference_01",
                [(Path("ref_seed.rnx"), _make_ds("ref_seed", slot=0))],
            ),
            _group_input(
                "canopy_01",
                [(Path("can_seed.rnx"), _make_ds("can_seed", slot=0))],
            ),
        ],
    )

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))

    real_write = RinexDataProcessor._write_group_into_fork

    def _boom(self: RinexDataProcessor, fork_session, plan):
        if plan.receiver_name == "canopy_01":
            raise RuntimeError("simulated mid-batch failure")
        return real_write(self, fork_session, plan)

    monkeypatch.setattr(RinexDataProcessor, "_write_group_into_fork", _boom)

    ref_files = [(Path("ref_2.rnx"), _make_ds("ref_2", slot=1))]
    can_files = [(Path("can_2.rnx"), _make_ds("can_2", slot=1))]

    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        proc._write_receiver_batch_forked(
            [
                _group_input("reference_01", ref_files),
                _group_input("canopy_01", can_files),
            ],
        )

    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))
    assert n_snapshots_after == n_snapshots_before, "no commit must land on failure"

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 10  # still just the seed -- ref_2 never landed
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 10  # still just the seed -- can_2 never landed


class _SbfConfig:
    """The processing.params.store_sbf_metadata switch, and no site."""

    def __init__(self, store_sbf_metadata: bool) -> None:
        params = type("P", (), {"store_sbf_metadata": store_sbf_metadata})()
        dumped = {"params": {"store_sbf_metadata": store_sbf_metadata}}
        # Commits record the settings as commit metadata, through model_dump.
        self.processing = type(
            "C", (), {"params": params, "model_dump": lambda self, mode: dumped}
        )()
        self.sites = SimpleNamespace(sites={})


def _sbf_obs_for(ds: xr.Dataset) -> xr.Dataset:
    return xr.Dataset(
        {"pdop": xr.DataArray(np.ones(ds.sizes["epoch"], np.float32), dims=["epoch"])},
        coords={"epoch": ("epoch", ds["epoch"].values, {"time_system": "GPS"})},
    )


def test_sbf_obs_lands_with_observations_and_is_not_duplicated(
    store: MyIcechunkStore,
) -> None:
    """sbf_obs is written in the observations' commits, for written files only.

    Day 1 creates the group (pre-pass + fork), day 2 appends; a rerun of
    day 2 skips its files, so sbf_obs must not grow. Before, sbf_obs was
    written in a separate commit after the data, and each call replaced
    the whole dataset with the current day.
    """
    proc = _TestProcessor(store)
    proc._config = _SbfConfig(store_sbf_metadata=True)

    def batch(day: str, ids: list[str]):
        files = [
            (Path(f"{i}.sbf"), _make_ds(i, slot=n, day=day)) for n, i in enumerate(ids)
        ]
        aux = {fname: {"sbf_obs": _sbf_obs_for(ds)} for fname, ds in files}
        return [("canopy_01", files, [f for f, _ in files], aux, None, "sbf")]

    proc._write_receiver_batch_forked(batch("2025-03-28", ["d1a", "d1b"]))
    proc._write_receiver_batch_forked(batch("2025-03-29", ["d2a", "d2b"]))
    n_snapshots = len(list(store.repo.ancestry(branch="main")))
    proc._write_receiver_batch_forked(batch("2025-03-29", ["d2a", "d2b"]))

    obs = store.read_group("canopy_01")
    meta = store.read_metadata_dataset("canopy_01", "sbf_obs").compute()
    np.testing.assert_array_equal(
        np.sort(meta["epoch"].values), np.sort(obs["epoch"].values)
    )
    assert meta.sizes["epoch"] == 4 * 10
    # The skipped rerun commits only its log-book rows, no sbf_obs commit
    assert len(list(store.repo.ancestry(branch="main"))) == n_snapshots + 1


def test_store_sbf_metadata_false_skips_sbf_obs(store: MyIcechunkStore) -> None:
    proc = _TestProcessor(store)
    proc._config = _SbfConfig(store_sbf_metadata=False)
    ds = _make_ds("only", slot=0)
    aux = {Path("only.sbf"): {"sbf_obs": _sbf_obs_for(ds)}}
    proc._write_receiver_batch_forked(
        [("canopy_01", [(Path("only.sbf"), ds)], [Path("only.sbf")], aux, None, "sbf")]
    )
    assert not store.metadata_dataset_exists("canopy_01", "sbf_obs")


def test_overwrite_promotes_temp_branch_to_main(store: MyIcechunkStore) -> None:
    proc = _TestProcessor(store, strategy="overwrite")
    files = [(Path("ref_1.rnx"), _make_ds("ref_1", slot=0))]

    proc._append_to_icechunk(files, "reference_01", [f for f, _ in files])

    assert "reference_01" in (store.list_groups() or [])
    assert store.repo.list_branches() == {"main"}


def test_overwrite_keeps_commit_made_to_main_meanwhile(
    store: MyIcechunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another writer commits to main during an overwrite: it is not lost."""
    from canvod.store.store import BranchMovedError

    proc = _TestProcessor(store, strategy="overwrite")
    files = [(Path("ref_1.rnx"), _make_ds("ref_1", slot=0))]
    promote = store.promote_branch

    def promote_after_other_writer(*args, **kwargs):
        store.set_root_attrs({"other_writer": "yes"}, branch="main")
        return promote(*args, **kwargs)

    monkeypatch.setattr(store, "promote_branch", promote_after_other_writer)

    with pytest.raises(BranchMovedError):
        proc._append_to_icechunk(files, "reference_01", [f for f, _ in files])

    assert store.get_root_attrs()["other_writer"] == "yes"
    assert "overwrite_reference_01_2025087" in store.repo.list_branches()


def _overwrite_after_two_files(
    store: MyIcechunkStore, store_sbf_metadata: bool
) -> tuple[xr.Dataset, xr.Dataset]:
    """Write files a and b with sbf_obs, then overwrite b (same file again).

    Returns the stored sbf_obs of a and b before the overwrite.
    """
    files = [(Path(f"{i}.sbf"), _make_ds(i, slot=n)) for n, i in enumerate("ab")]
    aux = {fname: {"sbf_obs": _sbf_obs_for(ds)} for fname, ds in files}
    proc = _TestProcessor(store)
    proc._config = _SbfConfig(store_sbf_metadata=True)
    proc._append_to_icechunk(files, "canopy_01", [f for f, _ in files], aux)

    proc = _TestProcessor(store, strategy="overwrite")
    proc._config = _SbfConfig(store_sbf_metadata=store_sbf_metadata)
    fname, ds = files[1]
    new_obs = _sbf_obs_for(ds)
    new_obs["pdop"] = new_obs["pdop"] * 0 + 9.0
    proc._append_to_icechunk(
        [(fname, ds)], "canopy_01", [fname], {fname: {"sbf_obs": new_obs}}
    )
    return aux[files[0][0]]["sbf_obs"], new_obs


def test_overwrite_replaces_sbf_obs_of_rewritten_file(store: MyIcechunkStore) -> None:
    kept, replaced = _overwrite_after_two_files(store, store_sbf_metadata=True)

    meta = store.read_metadata_dataset("canopy_01", "sbf_obs").compute()
    expected = xr.concat([kept, replaced], dim="epoch")
    np.testing.assert_array_equal(meta["epoch"].values, expected["epoch"].values)
    np.testing.assert_array_equal(meta["pdop"].values, expected["pdop"].values)


def test_overwrite_without_sbf_obs_keeps_other_files_sbf_obs(
    store: MyIcechunkStore,
) -> None:
    """A batch without sbf_obs drops only the rewritten file's epochs."""
    kept, _ = _overwrite_after_two_files(store, store_sbf_metadata=False)

    meta = store.read_metadata_dataset("canopy_01", "sbf_obs").compute()
    np.testing.assert_array_equal(meta["epoch"].values, kept["epoch"].values)


def test_overwrite_keeps_other_metadata_datasets(store: MyIcechunkStore) -> None:
    files = [(Path(f"{i}.rnx"), _make_ds(i, slot=n)) for n, i in enumerate("ab")]
    proc = _TestProcessor(store)
    proc._append_to_icechunk(files, "canopy_01", [f for f, _ in files])
    other = xr.Dataset({"x": ("station", np.arange(3.0))})
    with store.writable_session("main") as session:
        store.write_metadata_parts([other], "canopy_01", "other", session)
        session.commit("other metadata")

    proc = _TestProcessor(store, strategy="overwrite")
    proc._append_to_icechunk(files[1:], "canopy_01", [files[1][0]])

    xr.testing.assert_equal(
        store.read_metadata_dataset("canopy_01", "other").compute(), other
    )
