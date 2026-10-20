"""MyIcechunkStore.create_branch takes a full snapshot ID or a prefix of one,
from the history of any branch or tag."""

from __future__ import annotations

import pytest
from _helpers import make_synthetic_dataset, new_gnss_store


@pytest.fixture
def store(tmp_path):
    """A store with data on main and one commit on a side branch."""
    store = new_gnss_store(tmp_path / "branch_test_store")
    store.write_initial_group(make_synthetic_dataset(slot=0), "canopy_01")
    store.repo.create_branch("side", store.repo.lookup_branch("main"))
    store.set_root_attrs({"side": "yes"}, branch="side")
    return store


def test_full_id_on_main(store) -> None:
    tip = store.repo.lookup_branch("main")
    store.create_branch("copy", tip)
    assert store.repo.lookup_branch("copy") == tip


def test_full_id_on_another_branch(store) -> None:
    side_tip = store.repo.lookup_branch("side")
    store.create_branch("from_side", side_tip)
    assert store.repo.lookup_branch("from_side") == side_tip


def test_prefix_on_another_branch(store) -> None:
    side_tip = store.repo.lookup_branch("side")
    store.create_branch("from_side", side_tip[:8].lower())
    assert store.repo.lookup_branch("from_side") == side_tip


def test_snapshot_only_on_a_tag(store) -> None:
    side_tip = store.repo.lookup_branch("side")
    store.repo.create_tag("kept", side_tip)
    store.repo.delete_branch("side")
    store.create_branch("from_tag", side_tip)
    assert store.repo.lookup_branch("from_tag") == side_tip


def test_unknown_id_refused(store) -> None:
    with pytest.raises(ValueError, match="No snapshot found"):
        store.create_branch("nowhere", "ZZZZZZZZ")


def test_empty_id_refused(store) -> None:
    with pytest.raises(ValueError, match="Give a snapshot ID"):
        store.create_branch("any", "")


def test_ambiguous_prefix_refused(store) -> None:
    # Commit until two snapshot IDs share their first character; IDs are
    # base32, so at most 33 snapshots are needed.
    i = 0
    while True:
        ids = {
            a.id
            for b in store.repo.list_branches()
            for a in store.repo.ancestry(branch=b)
        }
        firsts = [x[0] for x in ids]
        shared = next((c for c in firsts if firsts.count(c) > 1), None)
        if shared:
            break
        store.set_root_attrs({"n": str(i)}, branch="side")
        i += 1
    with pytest.raises(ValueError, match="Ambiguous prefix"):
        store.create_branch("any", shared)
