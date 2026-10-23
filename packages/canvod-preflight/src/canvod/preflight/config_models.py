"""Pydantic models for the naming configuration of the sites: section.

These models validate the ``naming:`` sections at site and receiver level.
The ``canvod-utils`` package stores these as opaque ``dict | None`` fields;
this package validates them when constructing a ``FilenameMapper``.

.. deprecated::
    Left over from development and removed with the next major version,
    together with the ``naming:`` settings. Naming recipes
    (``canvod-filemap``) replace them.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from canvod.utils.tools import deprecated

from .convention import AgencyId, ContentCode, Duration, SiteId


class DirectoryLayout(StrEnum):
    """How receiver data files are organized into subdirectories."""

    YYDDD_SUBDIRS = "yyddd_subdirs"  # 25001/, 25002/
    YYYYDDD_SUBDIRS = "yyyyddd_subdirs"  # 2025001/
    FLAT = "flat"  # all files in one directory


@deprecated(
    "SiteNamingConfig is left over from development and will be removed with the next major version. "
    "Use a naming recipe (the receiver setting 'recipe', see canvod-filemap) instead; canvodpy run finds the files in any folder layout."
)
class SiteNamingConfig(BaseModel):
    """Site-level naming defaults (``sites.<name>.naming`` in YAML)."""

    site_id: SiteId
    agency: AgencyId
    default_sampling: Duration = "05S"
    default_period: Duration = "01D"
    default_content: ContentCode = "AA"


@deprecated(
    "ReceiverNamingConfig is left over from development and will be removed with the next major version. "
    "Use a naming recipe (the receiver setting 'recipe', see canvod-filemap) instead; canvodpy run finds the files in any folder layout."
)
class ReceiverNamingConfig(BaseModel):
    """Receiver-level naming overrides (``sites.<name>.receivers.<rx>.naming``).

    The ``source_station`` field specifies the 4-character station code used
    in RINEX v2 / SBF filenames (e.g. ``ract``, ``rref``).  When set, only
    files whose station code matches are accepted during discovery and
    validation.  When ``None``, any station code is accepted.
    """

    receiver_number: int = Field(ge=1, le=99)
    source_pattern: str = "auto"
    source_station: str | None = Field(
        default=None,
        description="4-char station code in source filenames (e.g. 'ract')",
    )
    directory_layout: DirectoryLayout = DirectoryLayout.YYDDD_SUBDIRS
    agency: AgencyId | None = None
    sampling: Duration | None = None
    period: Duration | None = None
    content: ContentCode | None = None
