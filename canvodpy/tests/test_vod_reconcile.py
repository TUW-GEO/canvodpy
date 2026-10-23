"""Tests for canvodpy.orchestrator.vod_reconcile (dev/todo_later.md §43).

_dates_covered/_group_into_ranges are exercised directly (pure functions,
no store needed). find_vod_backfill_gaps is exercised against a mocked
Site/store pair, following the same MagicMock convention as
test_vod_computer.py -- no real Icechunk store required.
"""

from __future__ import annotations

import datetime
import unittest.mock

import polars as pl
import pytest
from canvodpy.orchestrator.vod_reconcile import (
    _dates_covered,
    _group_into_ranges,
    find_vod_backfill_gaps,
)


def _meta_df(rows: list[tuple[str, str]]) -> pl.DataFrame:
    """Build a fake metadata table with datetime start/end columns."""
    return pl.DataFrame(
        {
            "start": [datetime.datetime.fromisoformat(s) for s, _e in rows],
            "end": [datetime.datetime.fromisoformat(e) for _s, e in rows],
        }
    )


def _make_site(vod_analyses: dict | None = None):
    site = unittest.mock.MagicMock()
    site.name = "TestSite"
    site.vod_analyses = vod_analyses or {}
    return site


def _make_analysis_cfg(canopy: str = "canopy_01", reference: str = "reference_01"):
    cfg = unittest.mock.MagicMock()
    cfg.canopy_receiver = canopy
    cfg.reference_receiver = reference
    cfg.reference_store_group = f"{reference}_{canopy}"
    return cfg


class TestDatesCovered:
    def test_single_day_rows(self):
        df = _meta_df(
            [
                ("2025-01-01T00:00:00", "2025-01-01T00:15:00"),
                ("2025-01-02T00:00:00", "2025-01-02T00:15:00"),
            ]
        )
        assert _dates_covered(df) == {"2025001", "2025002"}

    def test_multi_day_row_spans_every_day_inclusive(self):
        df = _meta_df([("2025-01-01T00:00:00", "2025-01-03T23:59:59")])
        assert _dates_covered(df) == {"2025001", "2025002", "2025003"}

    def test_empty_df(self):
        df = _meta_df([])
        assert _dates_covered(df) == set()

    def test_duplicate_dates_dedupe(self):
        df = _meta_df(
            [
                ("2025-01-01T00:00:00", "2025-01-01T00:15:00"),
                ("2025-01-01T00:15:00", "2025-01-01T00:30:00"),
            ]
        )
        assert _dates_covered(df) == {"2025001"}

    def test_absurd_span_raises_instead_of_looping(self):
        # a corrupt/malformed end value (e.g. bad epoch cast) must not
        # silently expand into a years-long loop
        df = _meta_df([("2025-01-01T00:00:00", "2099-01-01T00:00:00")])
        with pytest.raises(ValueError, match="corrupt"):
            _dates_covered(df)


class TestGroupIntoRanges:
    def test_empty(self):
        assert _group_into_ranges([]) == []

    def test_single_date(self):
        assert _group_into_ranges(["2025010"]) == [("2025010", "2025010")]

    def test_contiguous_run(self):
        dates = ["2025010", "2025011", "2025012"]
        assert _group_into_ranges(dates) == [("2025010", "2025012")]

    def test_gap_splits_into_two_ranges(self):
        dates = ["2025010", "2025011", "2025015", "2025016"]
        assert _group_into_ranges(dates) == [
            ("2025010", "2025011"),
            ("2025015", "2025016"),
        ]

    def test_year_boundary_is_contiguous(self):
        # 2025 is not a leap year -- day 365 is Dec 31; day 1 of 2026 is
        # the very next calendar day. Naive int/string increment would
        # wrongly treat "2025365" -> "2026001" as a gap.
        dates = ["2025364", "2025365", "2026001", "2026002"]
        assert _group_into_ranges(dates) == [("2025364", "2026002")]

    def test_all_scattered_singletons(self):
        dates = ["2025001", "2025003", "2025005"]
        assert _group_into_ranges(dates) == [
            ("2025001", "2025001"),
            ("2025003", "2025003"),
            ("2025005", "2025005"),
        ]


class TestFindVodBackfillGaps:
    @pytest.fixture(autouse=True)
    def stores_exist(self, monkeypatch):
        """Both mocked stores exist; a first run without them is tested in
        test_metadata_first.py."""
        monkeypatch.setattr(
            "canvodpy.orchestrator.vod_reconcile.store_exists", lambda _: True
        )

    def test_unknown_analysis_raises(self):
        site = _make_site(vod_analyses={})
        with pytest.raises(ValueError, match="not configured"):
            find_vod_backfill_gaps(site, "missing_analysis")

    def test_rinex_group_missing_returns_no_gaps(self):
        site = _make_site(vod_analyses={"a": _make_analysis_cfg()})
        site.gnss_store.group_exists.return_value = False
        assert find_vod_backfill_gaps(site, "a") == []
        site.vod_store.group_exists.assert_not_called()

    def test_vod_group_missing_all_rinex_dates_are_gaps(self):
        site = _make_site(vod_analyses={"a": _make_analysis_cfg()})
        site.gnss_store.group_exists.return_value = True
        site.gnss_store.readonly_session.return_value.__enter__.return_value = (
            unittest.mock.MagicMock()
        )
        site.gnss_store.read_metadata_table.return_value = _meta_df(
            [
                ("2025-01-01T00:00:00", "2025-01-01T00:15:00"),
                ("2025-01-02T00:00:00", "2025-01-02T00:15:00"),
            ]
        )
        site.vod_store.group_exists.return_value = False

        gaps = find_vod_backfill_gaps(site, "a", "tau_omega")
        assert gaps == ["2025001", "2025002"]

    def test_partial_overlap_returns_only_missing_dates(self):
        site = _make_site(vod_analyses={"a": _make_analysis_cfg()})
        site.gnss_store.group_exists.return_value = True
        site.gnss_store.readonly_session.return_value.__enter__.return_value = (
            unittest.mock.MagicMock()
        )
        site.gnss_store.read_metadata_table.return_value = _meta_df(
            [
                ("2025-01-01T00:00:00", "2025-01-01T00:15:00"),
                ("2025-01-02T00:00:00", "2025-01-02T00:15:00"),
                ("2025-01-03T00:00:00", "2025-01-03T00:15:00"),
            ]
        )
        site.vod_store.group_exists.return_value = True
        site.vod_store.readonly_session.return_value.__enter__.return_value = (
            unittest.mock.MagicMock()
        )
        site.vod_store.read_metadata_table.return_value = _meta_df(
            [("2025-01-01T00:00:00", "2025-01-02T23:59:59")]
        )

        gaps = find_vod_backfill_gaps(site, "a", "tau_omega")
        assert gaps == ["2025003"]

    def test_full_coverage_returns_no_gaps(self):
        site = _make_site(vod_analyses={"a": _make_analysis_cfg()})
        site.gnss_store.group_exists.return_value = True
        site.gnss_store.readonly_session.return_value.__enter__.return_value = (
            unittest.mock.MagicMock()
        )
        site.gnss_store.read_metadata_table.return_value = _meta_df(
            [("2025-01-01T00:00:00", "2025-01-02T00:15:00")]
        )
        site.vod_store.group_exists.return_value = True
        site.vod_store.readonly_session.return_value.__enter__.return_value = (
            unittest.mock.MagicMock()
        )
        site.vod_store.read_metadata_table.return_value = _meta_df(
            [("2025-01-01T00:00:00", "2025-01-02T23:59:59")]
        )

        assert find_vod_backfill_gaps(site, "a", "tau_omega") == []

    def test_uses_correct_group_names(self):
        site = _make_site(
            vod_analyses={"a": _make_analysis_cfg(canopy="c1", reference="r1")}
        )
        site.gnss_store.group_exists.return_value = False

        find_vod_backfill_gaps(site, "a", "my_calc")

        site.gnss_store.group_exists.assert_called_once_with("r1_c1")
