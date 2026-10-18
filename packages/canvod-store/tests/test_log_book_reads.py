"""A run reads a group's log book whole once, then only the rows added since.

Seam: :class:`canvod.store_metadata.log_book.LogBooks` and
``MyIcechunkStore.load_metadata_for_dedup`` on temporary stores (#421).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
import zarr
from _helpers import new_gnss_store
from canvod.store_metadata.log_book import LogBooks, read_log_book
from polars.testing import assert_frame_equal
from zarr.storage import WrapperStore

from canvod.store.store import _append_log_rows

GROUP = "canopy_01"
TABLE = f"{GROUP}/metadata/table"


def _rows(first: int, count: int, **extra: list[str]) -> pl.DataFrame:
    """``count`` made-up log-book rows of 15-minute files from file ``first``."""
    start = np.datetime64("2025-01-01T00:00", "ns") + np.arange(
        first, first + count
    ) * np.timedelta64(15, "m")
    return pl.DataFrame(
        {
            "rinex_hash": [f"hash_{k}" for k in range(first, first + count)],
            "fname": [f"file_{k}.rnx" for k in range(first, first + count)],
            "start": start,
            "end": start + np.timedelta64(895, "s"),
            **extra,
        }
    )


def _commit_rows(store: Any, df: pl.DataFrame) -> None:
    """Append ``df`` to the log book in a commit of its own."""
    session = store.repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    _append_log_rows(root.require_group(TABLE), df)
    session.commit("log-book rows")


class _ReadKeys(WrapperStore):
    """A store that records the key of every read, shared across its copies."""

    def __init__(self, store: Any, keys: list[str] | None = None) -> None:
        super().__init__(store)
        self.keys = [] if keys is None else keys

    def _with_store(self, store: Any) -> _ReadKeys:
        return type(self)(store, self.keys)

    async def get(self, key: str, *args: Any, **kwargs: Any) -> Any:
        self.keys.append(key)
        return await super().get(key, *args, **kwargs)


@dataclass
class _CountedSession:
    """A read-only session whose store records the keys read."""

    session: Any

    def __post_init__(self) -> None:
        self.store = _ReadKeys(self.session.store)
        self.branch = self.session.branch
        self.snapshot_id = self.session.snapshot_id
        self.has_uncommitted_changes = self.session.has_uncommitted_changes

    def chunks_read(self) -> list[str]:
        """Keys of log-book chunks read, not of metadata documents."""
        return [k for k in self.store.keys if k.startswith(TABLE) and "/c/" in k]


@pytest.fixture
def store(tmp_path: Path):
    """A GNSS store whose log book holds 3,000 rows, three chunks per column."""
    store = new_gnss_store(tmp_path / "gnss")
    _commit_rows(store, _rows(0, 3000))
    return store


def _at_tip(store: Any) -> _CountedSession:
    return _CountedSession(store.repo.readonly_session("main"))


def test_a_new_commit_reads_only_the_rows_it_added(store) -> None:
    books = LogBooks()
    books.rows(_at_tip(store), GROUP)
    _commit_rows(store, _rows(3000, 5))

    session = _at_tip(store)
    rows = books.rows(session, GROUP)

    assert rows is not None
    assert_frame_equal(
        rows, read_log_book(session.session.store, GROUP), check_column_order=False
    )
    read = session.chunks_read()
    assert read, "the new rows were not read"
    assert all(k.endswith("/c/2") for k in read), read


def test_rows_added_day_by_day_stay_one_chunk(store) -> None:
    """A frame grown by a chunk per commit filters slower every day stored."""
    books = LogBooks()
    for day in range(5):
        _commit_rows(store, _rows(3000 + 96 * day, 96))
        rows = books.rows(_at_tip(store), GROUP)

    assert rows is not None
    assert rows.height == 3000 + 5 * 96
    assert rows.n_chunks("all") == [1] * rows.width


def test_the_same_snapshot_reads_nothing(store) -> None:
    books = LogBooks()
    books.rows(_at_tip(store), GROUP)

    session = _at_tip(store)
    books.rows(session, GROUP)

    assert session.store.keys == []


@pytest.mark.parametrize(
    "change",
    ["rows", "a new column", "the table written anew"],
)
def test_rows_equal_a_whole_read_after_any_change(store, change) -> None:
    books = LogBooks()
    books.rows(_at_tip(store), GROUP)
    if change == "rows":
        _commit_rows(store, _rows(3000, 2000))
    elif change == "a new column":
        _commit_rows(store, _rows(3000, 5, epochs=["1"] * 5))
    else:
        session = store.repo.writable_session("main")
        rewritten = _rows(0, 3000).with_columns(
            pl.col("rinex_hash") + "_new", pl.arange(0, 3000).alias("index")
        )
        store.restore_metadata_table(GROUP, rewritten, session)
        session.commit("table written anew")

    tip = store.repo.readonly_session("main")
    rows = books.rows(tip, GROUP)

    assert rows is not None
    assert_frame_equal(rows, read_log_book(tip.store, GROUP), check_column_order=False)


def test_uncommitted_rows_are_not_kept(store) -> None:
    books = LogBooks()
    session = store.repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    _append_log_rows(root[TABLE], _rows(3000, 1))

    assert books.rows(session, GROUP).height == 3001
    session.discard_changes()
    assert books.rows(store.repo.readonly_session("main"), GROUP).height == 3000


def test_a_group_without_a_log_book_has_none(store) -> None:
    assert LogBooks().rows(store.repo.readonly_session("main"), "reference_01") is None


def test_another_runs_rows_are_seen(store, tmp_path) -> None:
    from canvod.store import open_gnss_store

    run = open_gnss_store(store.store_path)
    assert run.load_metadata_for_dedup(GROUP).height == 3000

    other = open_gnss_store(store.store_path)
    _commit_rows(other, _rows(3000, 3))

    rows = run.load_metadata_for_dedup(GROUP)
    assert rows["rinex_hash"].tail(3).to_list() == [
        "hash_3000",
        "hash_3001",
        "hash_3002",
    ]
