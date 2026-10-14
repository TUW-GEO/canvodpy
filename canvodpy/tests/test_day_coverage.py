"""Epochs a receiver's day holds, by its log book (``should_skip_day``)."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest
from canvodpy.orchestrator.processor import logged_day_epochs

_NAME = "FANT01TUW_R_2025001{hhmm}_15M_{sampling}_AA.rnx"


def _rows(*rows: dict) -> pl.DataFrame:
    return pl.DataFrame(
        list(rows),
        schema={
            "canonical_name": pl.Utf8,
            "start": pl.Datetime("ns"),
            "end": pl.Datetime("ns"),
            "epochs": pl.Int64,
            "action": pl.Utf8,
            "written_at": pl.Utf8,
        },
    )


def _row(hhmm: str, sampling: str, epochs: int, **kw) -> dict:
    start = datetime(2025, 1, 1, int(hhmm[:2]), int(hhmm[2:]))
    return {
        "canonical_name": _NAME.format(hhmm=hhmm, sampling=sampling),
        "start": start,
        "end": kw.get("end", start),
        "epochs": epochs,
        "action": kw.get("action", "write"),
        "written_at": kw.get("written_at", "2026-01-01T00:00:00+00:00"),
    }


def test_expects_a_day_at_the_files_sampling_not_30_s() -> None:
    logged, expected = logged_day_epochs(_rows(_row("0000", "05S", 180)))
    assert (logged, expected) == (180, 17280)


def test_counts_a_file_written_twice_once() -> None:
    rows = _rows(
        _row("0000", "05S", 170, written_at="2026-01-01T00:00:00+00:00"),
        _row("0000", "05S", 180, written_at="2026-01-02T00:00:00+00:00"),
    )
    assert logged_day_epochs(rows) == (180, 17280)


def test_skipped_files_add_nothing() -> None:
    rows = _rows(_row("0000", "05S", 180), _row("0015", "05S", 180, action="skip"))
    assert logged_day_epochs(rows) == (180, 17280)


def test_rows_without_an_epoch_count_use_the_time_range() -> None:
    start = datetime(2025, 1, 1, 0, 0)
    end = datetime(2025, 1, 1, 0, 14, 55)
    rows = _rows(_row("0000", "05S", -1, end=end))
    assert rows["start"][0] == start
    assert logged_day_epochs(rows) == (180, 17280)


def test_a_name_without_sampling_is_refused() -> None:
    row = _row("0000", "05S", 180)
    row["canonical_name"] = ""
    with pytest.raises(ValueError, match="sampling"):
        logged_day_epochs(_rows(row))
