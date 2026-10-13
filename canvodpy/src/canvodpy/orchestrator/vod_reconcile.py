"""Find RINEX-ingested-but-VOD-missing dates for a VOD analysis pair.

A run can complete RINEX ingestion for a date
range cleanly, then fail before (or during) the corresponding VOD-store
write, leaving those dates permanently un-backfilled: the pipeline's
resume logic (``_last_processed_date()``, ``cli/run.py``) only looks at
the GNSS store, so an already-RINEX-complete date is never re-yielded
for VOD computation on a later run. This module finds that gap cheaply
-- two whole-table metadata reads (RINEX group + VOD group), not one
query per candidate date -- so it scales fine to a site's full history.

Per the owner's explicit direction: no automatic "skip and continue"
masking of a real failure. This module only reports/backfills a gap
left behind *after* a run already stopped; it does not change what
happens during a run.
"""

from __future__ import annotations

import datetime

import polars as pl

from canvod.store_metadata import store_exists
from canvod.utils.tools import YYYYDOY
from canvodpy.api import Site

# Defensive cap on a single metadata row's [start, end] span. Real rows
# never approach this (RINEX rows span ~1 day; VOD rows are bounded by
# compute_bulk()'s explicit caller-supplied range) -- this guards against
# a corrupt/malformed row (e.g. a bad epoch cast) silently expanding into
# a years-long loop. This function now runs on every `canvodpy run`
# startup via the read-only gap-check warning, not just the manual
# vod-reconcile tool, so an unbounded loop here would be a real problem.
_MAX_ROW_SPAN_DAYS = 366


def _dates_covered(df: pl.DataFrame) -> set[str]:
    """Expand a metadata table's ``start``/``end`` row intervals into the
    set of calendar dates (YYYYDOY strings) they cover.

    Handles both per-file rows (typically within a single date) and
    wider multi-day rows (e.g. a bulk VOD computation spanning a whole
    backfill range) uniformly -- every calendar day touched by any row's
    ``[start, end]`` interval counts as covered.

    Raises
    ------
    ValueError
        If a row's ``[start, end]`` span exceeds ``_MAX_ROW_SPAN_DAYS`` --
        treated as corrupt data rather than expanded.
    """
    dates: set[str] = set()
    for start, end in zip(df["start"], df["end"], strict=True):
        day = start.date()
        end_day = end.date()
        if (end_day - day).days > _MAX_ROW_SPAN_DAYS:
            raise ValueError(
                f"metadata row spans {(end_day - day).days} days "
                f"({day} to {end_day}), exceeding the {_MAX_ROW_SPAN_DAYS}-day "
                "sanity cap -- likely corrupt start/end data"
            )
        while day <= end_day:
            dates.add(YYYYDOY.from_date(day).to_str())
            day += datetime.timedelta(days=1)
    return dates


def _require_date(yyyydoy: str) -> datetime.date:
    date_obj = YYYYDOY.from_str(yyyydoy).date
    assert date_obj is not None, f"unparseable YYYYDOY string: {yyyydoy!r}"
    return date_obj


def _group_into_ranges(dates: list[str]) -> list[tuple[str, str]]:
    """Collapse a sorted list of YYYYDOY strings into contiguous ranges.

    ``VodComputer.compute_bulk()`` only takes a single ``start``/``end``
    range per call -- grouping gap dates into runs of consecutive
    calendar days lets a scattered gap set be backfilled with one
    ``compute_bulk()`` call per contiguous run instead of one per date.
    """
    if not dates:
        return []
    ranges: list[tuple[str, str]] = []
    range_start = dates[0]
    prev_date = _require_date(dates[0])
    for yyyydoy in dates[1:]:
        current_date = _require_date(yyyydoy)
        if current_date != prev_date + datetime.timedelta(days=1):
            ranges.append((range_start, YYYYDOY.from_date(prev_date).to_str()))
            range_start = yyyydoy
        prev_date = current_date
    ranges.append((range_start, YYYYDOY.from_date(prev_date).to_str()))
    return ranges


def find_vod_backfill_gaps(
    site: Site, analysis_name: str, calculator_name: str = "tau_omega"
) -> list[str]:
    """Dates with RINEX data ingested but no corresponding VOD result.

    Compares the GNSS store's ``{reference}_{canopy}`` group metadata
    table against the VOD store's ``{calculator}/{analysis}`` group
    metadata table for ``analysis_name`` -- two single, cheap whole-table
    reads via ``read_metadata_table()``, not a per-date query.

    Parameters
    ----------
    site : Site
        Site to check.
    analysis_name : str
        Configured VOD analysis name (``site.vod_analyses`` key).
    calculator_name : str
        Registered VOD calculator name results were (or would be)
        computed with.

    Returns
    -------
    list[str]
        Sorted YYYYDOY strings present in the GNSS store's analysis
        pair group but absent from the VOD store's result group. Empty
        if there's no gap.

    Raises
    ------
    ValueError
        If ``analysis_name`` is not configured for ``site``.
    """
    if analysis_name not in site.vod_analyses:
        available = list(site.vod_analyses)
        raise ValueError(
            f"VOD analysis '{analysis_name}' not configured. Available: {available}"
        )
    cfg = site.vod_analyses[analysis_name]
    rinex_group = cfg.reference_store_group
    vod_group = f"{calculator_name}/{analysis_name}"

    if not store_exists(site.gnss_store_path) or not site.gnss_store.group_exists(
        rinex_group
    ):
        return []
    with site.gnss_store.readonly_session() as session:
        rinex_df = site.gnss_store.read_metadata_table(session, rinex_group)
    rinex_dates = _dates_covered(rinex_df) if not rinex_df.is_empty() else set()

    vod_dates: set[str] = set()
    if store_exists(site.vod_store_path) and site.vod_store.group_exists(vod_group):
        with site.vod_store.readonly_session() as session:
            vod_df = site.vod_store.read_metadata_table(session, vod_group)
        vod_dates = _dates_covered(vod_df) if not vod_df.is_empty() else set()

    return sorted(rinex_dates - vod_dates)
