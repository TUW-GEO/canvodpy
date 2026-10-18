"""The data, the colors and the axes of the run dashboard's charts.

They live here, outside the marimo notebook (`performance.py`), so a
test can check them directly. No marimo here.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import date, datetime

import altair as alt

from canvodpy.run_history import StageTiming, StoreSize


def chart_palette(count: int = 1) -> list[str]:
    """The altair data colors for one series or for labels with an order,
    such as worker counts. One series is canvodpy's green (the docs
    theme, ``docs/assets/canvod-nordic.css``). Several run from dark
    blue over sky blue and amber to canvodpy's cream: the lightness
    rises along the order, which people with a red-green color vision
    deficiency can follow, and the hue changes too, so neighbors stay
    apart. The dashboard is always dark (the script header sets the
    marimo theme)."""
    anchors = [
        (0x4A, 0x6F, 0xA5),
        (0x6F, 0xB7, 0xDE),
        (0xE0, 0xB2, 0x68),
        (0xE1, 0xE6, 0xB9),
    ]
    if count == 1:
        return ["#ABC8A4"]
    colors = []
    for index in range(count):
        position = index / (count - 1) * (len(anchors) - 1)
        low = min(int(position), len(anchors) - 2)
        share = position - low
        rgb = [
            round(a + (b - a) * share)
            for a, b in zip(anchors[low], anchors[low + 1], strict=True)
        ]
        colors.append("#{:02X}{:02X}{:02X}".format(*rgb))
    return colors


def chart_categories(count: int) -> list[str]:
    """``count`` colors for labels without an order, such as CPU and
    memory: canvodpy's cream, then blue, amber and brick red. They
    differ in hue and in lightness (they stay apart in greyscale), and
    also with a red-green color vision deficiency. More labels than
    these four get the colors of :func:`chart_palette`."""
    colors = ["#E1E6B9", "#4C93C4", "#E0A84E", "#B5605A"]
    if count <= len(colors):
        return colors[:count]
    return chart_palette(count)


def time_bars(
    channel: str, field: str, title: str, rows: list[dict], scale_type: str
) -> tuple[list[dict], dict]:
    """The rows and the altair encoding of a bar chart's time axis.

    ``"linear"`` starts the axis at zero. ``"log"`` spreads short and
    long stages apart; a log axis has no zero, so the axis runs from
    the power of ten below the shortest time to the one above the
    longest, the bars start at its bottom, and rows without a positive
    time are left out.
    """
    channels = {"x": (alt.X, alt.X2Datum), "y": (alt.Y, alt.Y2Datum)}[channel]
    axis = alt.Axis(title=title)
    positive = [row for row in rows if (row.get(field) or 0) > 0]
    if scale_type != "log" or not positive:
        scale = alt.Scale(type="linear", zero=True)
        return rows, {channel: channels[0](f"{field}:Q", axis=axis, scale=scale)}
    times = [row[field] for row in positive]
    lower = 10 ** math.floor(math.log10(min(times)))
    upper = 10 ** math.ceil(math.log10(max(times)))
    scale = alt.Scale(type="log", domain=[lower, max(upper, 10 * lower)])
    return positive, {
        channel: channels[0](f"{field}:Q", axis=axis, scale=scale),
        f"{channel}2": channels[1](lower),
    }


def time_line(
    channel: str, field: str, title: str, rows: list[dict], scale_type: str
) -> tuple[list[dict], dict]:
    """The rows and the altair encoding of a line chart's time axis.

    Like :func:`time_bars` but without the baseline: a bar draws to a
    zero baseline (an ``x2``/``y2`` datum), a line has no such edge, so
    its encoding is the plain ``x`` or ``y`` channel. ``"log"`` keeps the
    positive rows and runs the axis between the powers of ten around the
    shortest and the longest time, as :func:`time_bars` does.
    """
    channel_types = {"x": alt.X, "y": alt.Y}
    axis = alt.Axis(title=title)
    positive = [row for row in rows if (row.get(field) or 0) > 0]
    if scale_type != "log" or not positive:
        scale = alt.Scale(type="linear", zero=True)
        return rows, {
            channel: channel_types[channel](f"{field}:Q", axis=axis, scale=scale)
        }
    times = [row[field] for row in positive]
    lower = 10 ** math.floor(math.log10(min(times)))
    upper = 10 ** math.ceil(math.log10(max(times)))
    scale = alt.Scale(type="log", domain=[lower, max(upper, 10 * lower)])
    return positive, {
        channel: channel_types[channel](f"{field}:Q", axis=axis, scale=scale)
    }


def stage_stats(timings: Iterable[StageTiming]) -> list[dict]:
    """The total and the per-day median time of each stage.

    The total is the stage's seconds added up. The median is over the
    stage's per-day seconds (the seconds of a day summed, whatever the
    receiver), or over its records when the stage names no day (such as
    ``day_block_growth``). A record of a unit of days names its days
    joined by commas (e.g. ``"2025168,2025169"``); its seconds are split
    evenly over those days, so a unit is one median, not one long point.
    The rows are sorted by total, high to low.
    """
    by_stage: dict[str, list[StageTiming]] = {}
    for timing in timings:
        by_stage.setdefault(timing.stage, []).append(timing)
    rows = []
    for stage, records in by_stage.items():
        total = sum(record.seconds or 0.0 for record in records)
        if any(record.day is not None for record in records):
            per_day: dict[str, float] = {}
            for record in records:
                if record.day is None:
                    continue
                for day, share in split_days(record.day, record.seconds or 0.0):
                    per_day[day] = per_day.get(day, 0.0) + share
            values = list(per_day.values())
        else:
            values = [record.seconds or 0.0 for record in records]
        rows.append(
            {
                "Stage": stage,
                "Total (s)": total,
                "Median (s)": statistics.median(values) if values else 0.0,
            }
        )
    rows.sort(key=lambda row: -float(row["Total (s)"]))
    return rows


def split_days(day: str | None, seconds: float) -> list[tuple[str, float]]:
    """Split a record's seconds over the data days it names.

    A record of a unit of days names its days joined by commas (e.g.
    ``"2025168,2025169"``). Its seconds are split evenly over those days, so
    a unit is not one long point on the time-per-day chart. Each day comes
    back as ``YYYYDOY`` (:func:`day_key`); a record without a day yields
    nothing.
    """
    if not day:
        return []
    days = [day_key(part) for part in day.split(",") if part]
    if not days:
        return []
    share = seconds / len(days)
    return [(part, share) for part in days]


def day_key(day: str) -> str:
    """A data day as ``YYYYDOY``, the key of every stage record.

    Runs before the fix recorded the VOD phase's days as ISO dates
    (``"2025-06-18"``); those become ``"2025169"``, so their seconds join
    the GNSS stages' seconds of the same day. A ``YYYYDOY`` key, or
    anything else, is returned as is.
    """
    if len(day) != len("2025-06-18"):
        return day
    try:
        stamp = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{stamp.year}{stamp.timetuple().tm_yday:03d}"


def day_date(key: str) -> str | None:
    """The ISO date (``"2025-06-18"``) of a ``YYYYDOY`` day, for a date axis;
    ``None`` when ``key`` is not ``YYYYDOY``."""
    try:
        return datetime.strptime(key, "%Y%j").date().isoformat()
    except ValueError:
        return None


def day_rows(timings: Iterable[StageTiming]) -> list[dict]:
    """The stage seconds of each data day, summed, ordered by day.

    A record of a unit of days is split evenly over the days it names
    (:func:`split_days`). Rows are ``Day`` (``YYYYDOY``), ``Date`` (ISO,
    for the date axis) and ``Seconds``.
    """
    totals: dict[str, float] = {}
    for timing in timings:
        for day, seconds in split_days(timing.day, timing.seconds or 0.0):
            totals[day] = totals.get(day, 0.0) + seconds
    return [
        {"Day": day, "Date": day_date(day), "Seconds": seconds}
        for day, seconds in sorted(totals.items())
    ]


def store_rows(store_sizes: Iterable[StoreSize]) -> list[dict]:
    """The on-disk store size per day, one row per store plus their total.

    Rows are ``(day, date, store, size in bytes)`` for every store
    recorded that day, then a ``Total`` row (all stores added up) per day,
    ordered by day. The day is ``YYYYDOY``, the date its ISO date for the
    date axis. The unit of the chart (MB or GB) is chosen from the values.
    """
    by_day: dict[str, dict[str, int]] = {}
    for size in store_sizes:
        by_day.setdefault(day_key(size.day), {})[size.store] = size.bytes
    rows = []
    for day in sorted(by_day):
        stores = by_day[day]
        when = day_date(day)
        for store in sorted(stores):
            rows.append(
                {
                    "Day": day,
                    "Date": when,
                    "Store": store,
                    "Size (bytes)": stores[store],
                }
            )
        rows.append(
            {
                "Day": day,
                "Date": when,
                "Store": "Total",
                "Size (bytes)": sum(stores.values()),
            }
        )
    return rows
