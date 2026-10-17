"""The colors and the time axes of the run dashboard's charts.

They live here, outside the marimo notebook (`performance.py`), so a
test can check them directly. No marimo here.
"""

from __future__ import annotations

import math

import altair as alt


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
