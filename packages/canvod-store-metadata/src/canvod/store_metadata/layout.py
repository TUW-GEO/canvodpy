"""How a store group lays out its epoch axis (ADR 0016).

A group written as day blocks says so in its attributes; a group without
the attribute was written by appending files to the end of the axis.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Group attribute naming the layout of the group's epoch axis.
EPOCH_LAYOUT_ATTR = "epoch_layout"

#: Value of :data:`EPOCH_LAYOUT_ATTR` for a group made of day blocks.
DAY_BLOCKS = "day_blocks"


class LayoutError(Exception):
    """A write that does not fit the layout of a group's epoch axis.

    Deliberately not a ``ValueError``: a run stops on it instead of skipping
    the file, because every later file would be refused the same way.
    """


def is_day_block_group(attrs: Mapping[str, Any]) -> bool:
    """Whether a group with these attributes is made of day blocks."""
    return attrs.get(EPOCH_LAYOUT_ATTR) == DAY_BLOCKS
