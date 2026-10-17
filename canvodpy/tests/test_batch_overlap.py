"""Tests for the write-time overlap checks: among the files of one batch,
and against the files already stored (#351)."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import polars as pl
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.store import MyIcechunkStore
from canvod.store.store import StoredOverlapError


def _processor(
    stored: pl.DataFrame | None = None, strategy: str = "skip"
) -> RinexDataProcessor:
    """A processor whose GNSS store's log book holds ``stored``."""
    proc = object.__new__(RinexDataProcessor)
    store = SimpleNamespace(
        load_metadata_for_dedup=lambda _receiver: stored, _logger=mock.MagicMock()
    )
    store.batch_check_existing = partial(MyIcechunkStore.batch_check_existing, store)
    store.check_temporal_overlaps = partial(
        MyIcechunkStore.check_temporal_overlaps, store
    )
    proc.site = SimpleNamespace(gnss_store=store)
    proc._logger = mock.MagicMock()
    proc._gnss_store_strategy = strategy
    return proc


def _file(name: str, start: str, minutes: int) -> tuple[Path, xr.Dataset]:
    epochs = np.datetime64(start) + np.arange(0, minutes * 60, 5).astype(
        "timedelta64[s]"
    )
    return Path(name), xr.Dataset(coords={"epoch": epochs})


def _skipped(*files: tuple[Path, xr.Dataset]) -> set[str]:
    hashes = {fname: fname.name for fname, _ in files}
    return _processor()._check_existing_with_temporal_overlap("rx", list(files), hashes)


def test_adjacent_files_are_kept() -> None:
    assert not _skipped(
        _file("a", "2025-01-01T00:00", 15), _file("b", "2025-01-01T00:15", 15)
    )


def test_daily_file_next_to_sub_daily_files_is_skipped() -> None:
    files = [_file("day", "2025-01-01T00:00", 1440)] + [
        _file(f"q{i}", f"2025-01-01T00:{15 * i:02d}", 15) for i in range(4)
    ]
    assert _skipped(*files) == {"day"}


@pytest.mark.parametrize(
    ("second", "start"),
    [("same", "2025-01-01T00:00"), ("partial", "2025-01-01T00:10")],
)
def test_of_two_overlapping_files_one_is_kept(second: str, start: str) -> None:
    assert _skipped(
        _file("first", "2025-01-01T00:00", 15), _file(second, start, 15)
    ) == {second}


def _log_book(*files: tuple[str, str, int]) -> pl.DataFrame:
    """Log-book rows of files stored before: ``(name, start, minutes)``.

    The hash of a stored file is its name, as in :func:`_skipped`.
    """
    starts = [np.datetime64(start, "ns") for _, start, _ in files]
    ends = [
        start + np.timedelta64(minutes * 60 - 5, "s")
        for start, (_, _, minutes) in zip(starts, files, strict=True)
    ]
    return pl.DataFrame(
        {
            "fname": [name for name, _, _ in files],
            "canonical_name": [name for name, _, _ in files],
            "rinex_hash": [name for name, _, _ in files],
            "start": np.array(starts, dtype="datetime64[ns]"),
            "end": np.array(ends, dtype="datetime64[ns]"),
            "action": ["written"] * len(files),
        }
    )


def _check(
    stored: pl.DataFrame, *files: tuple[Path, xr.Dataset], strategy: str = "skip"
) -> set[str]:
    hashes = {fname: fname.name for fname, _ in files}
    return _processor(stored, strategy)._check_existing_with_temporal_overlap(
        "canopy_01", list(files), hashes
    )


class TestStoredOverlap:
    """A file whose epochs another file already filled stops the run (#351)."""

    def test_a_file_over_epochs_of_another_stored_file_stops_the_run(self) -> None:
        stored = _log_book(("ROSA_0000.rnx", "2025-01-01T00:00", 15))

        with pytest.raises(StoredOverlapError) as caught:
            _check(stored, _file("ROSA_0000_v2.rnx", "2025-01-01T00:10", 15))

        message = str(caught.value)
        assert "ROSA_0000_v2.rnx" in message
        assert "ROSA_0000.rnx" in message
        assert "canopy_01" in message
        assert "2025-01-01T00:10" in message
        assert "gnss_store_strategy" in message

    def test_a_changed_file_of_the_same_name_is_told_apart_by_its_hash(
        self,
    ) -> None:
        stored = _log_book(("FAN0_0000.rnx", "2025-01-01T00:00", 15)).with_columns(
            rinex_hash=pl.lit("a" * 64)
        )
        fname, ds = _file("FAN0_0000.rnx", "2025-01-01T00:00", 15)

        with pytest.raises(StoredOverlapError) as caught:
            _processor(stored)._check_existing_with_temporal_overlap(
                "canopy_01", [(fname, ds)], {fname: "b" * 64}
            )

        message = str(caught.value)
        assert f"FAN0_0000.rnx (hash {'b' * 12}," in message
        assert f"overlaps FAN0_0000.rnx (hash {'a' * 12}," in message

    def test_the_same_file_again_is_still_skipped(self) -> None:
        stored = _log_book(("ROSA_0000.rnx", "2025-01-01T00:00", 15))

        assert _check(stored, _file("ROSA_0000.rnx", "2025-01-01T00:00", 15)) == {
            "ROSA_0000.rnx"
        }

    def test_a_file_next_to_the_stored_ones_is_written(self) -> None:
        stored = _log_book(("ROSA_0000.rnx", "2025-01-01T00:00", 15))

        assert not _check(stored, _file("ROSA_0015.rnx", "2025-01-01T00:15", 15))

    @pytest.mark.parametrize("strategy", ["overwrite", "unsafe_append"])
    def test_a_strategy_that_writes_stored_files_again_replaces_them(
        self, strategy: str
    ) -> None:
        stored = _log_book(("ROSA_0000.rnx", "2025-01-01T00:00", 15))

        flagged = _check(
            stored,
            _file("ROSA_0000_v2.rnx", "2025-01-01T00:00", 15),
            strategy=strategy,
        )

        assert flagged == {"ROSA_0000_v2.rnx"}
