"""Each group's log book, read whole once and afterwards only its new rows.

A run asks for a group's log book several times a day: to plan a day and
to check overlaps at the tip before each commit. Reading the whole table
each time costs time that grows with the store (ADR 0021). The log book
is append-only with a continuous ``index`` (canvod-store's
``_append_log_rows``), so the rows another commit added are the rows past
the ones already known. GNSS and VOD log books alike.
"""

import threading
from dataclasses import dataclass
from typing import Any

import icechunk
import polars as pl
import zarr


def log_book_frame(columns: dict[str, Any]) -> pl.DataFrame:
    """Log-book columns as read from Zarr, as one DataFrame with typed times."""
    df = pl.DataFrame(columns)
    for name in ("start", "end"):
        if name in df.columns and df[name].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col(name).cast(pl.Datetime("ns")))
    if "written_at" in df.columns and df["written_at"].dtype == pl.Utf8:
        df = df.with_columns(pl.col("written_at").str.to_datetime("%+"))
    return df


def read_log_book(store: Any, group: str) -> pl.DataFrame:
    """The whole log book of ``group`` (``{group}/metadata/table``)."""
    table = zarr.open_group(store, mode="r", path=f"{group}/metadata/table")
    return log_book_frame({col: _column(table, col)[...] for col in table.array_keys()})


def _column(table: zarr.Group, name: str) -> zarr.Array:
    """Column ``name`` of a log-book table."""
    column = table[name]
    if not isinstance(column, zarr.Array):
        msg = f"log-book column {name!r} is a group, not an array"
        raise TypeError(msg)
    return column


@dataclass(frozen=True)
class _Known:
    """A log book as last read, and the snapshot it was read at."""

    rows: pl.DataFrame
    snapshot_id: str


class LogBooks:
    """The log books of one store's groups, kept between reads.

    :meth:`rows` reads a group's log book whole the first time. Later it
    reads nothing when the session is at the snapshot it last read, and
    otherwise only the rows past the ones it holds (rows another day or
    another run committed since). If the table no longer starts with the
    rows it holds (a column added, or the table written anew, as
    ``restore_metadata_table`` does), it reads the table whole again.

    Rows read from a session with uncommitted changes are returned but not
    kept: they may never be committed. Read-only sessions name no branch,
    so the rows are kept per group; reading another branch or an older
    snapshot only costs a whole read.
    """

    def __init__(self) -> None:
        self._known: dict[str, _Known] = {}
        self._lock = threading.Lock()

    def rows(self, session: icechunk.Session, group: str) -> pl.DataFrame | None:
        """``group``'s log book at ``session``; ``None`` if it has none."""
        snapshot = session.snapshot_id
        clean = not session.has_uncommitted_changes
        with self._lock:
            known = self._known.get(group)
            if known is not None and clean and known.snapshot_id == snapshot:
                return known.rows
            rows = self._read(session.store, group, known)
            if rows is None:
                self._known.pop(group, None)
            elif clean:
                self._known[group] = _Known(rows, snapshot)
            return rows

    @staticmethod
    def _read(store: Any, group: str, known: _Known | None) -> pl.DataFrame | None:
        """The log book, from ``known`` plus the rows past it where possible."""
        root = zarr.open_group(store, mode="r")
        path = f"{group}/metadata/table"
        if path not in root:
            return None
        table = zarr.open_group(store, mode="r", path=path)
        if known is None or not _starts_with(table, known.rows):
            return read_log_book(store, group)
        height = _column(table, "index").shape[0]
        if height == known.rows.height:
            return known.rows
        new = log_book_frame(
            {
                col: _column(table, col)[known.rows.height : height]
                for col in known.rows.columns
            }
        )
        return pl.concat([known.rows, new], how="vertical_relaxed")


def _starts_with(table: zarr.Group, rows: pl.DataFrame) -> bool:
    """Whether ``table`` holds ``rows`` first, judged by columns and last row."""
    if set(table.array_keys()) != set(rows.columns):
        return False
    height = rows.height
    if _column(table, "index").shape[0] < height:
        return False
    if height == 0:
        return True
    last = rows.height - 1
    stored = log_book_frame(
        {col: _column(table, col)[last : last + 1] for col in rows.columns}
    )
    return stored.equals(rows.slice(last, 1))
