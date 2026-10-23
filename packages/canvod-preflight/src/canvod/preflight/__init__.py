"""canvod-preflight: the canVOD filename convention.

``CanVODFilename`` parses and builds canonical canVOD filenames, and
``find_overlaps`` finds files whose named time spans overlap. Both are used
by the file discovery of ``canvodpy run``.

.. deprecated::
    The mapping and validation API (``FilenameMapper``, ``VirtualFile``,
    ``DataDirectoryValidator``, ``ValidationReport``, ``SiteNamingConfig``,
    ``ReceiverNamingConfig``, ``DirectoryLayout``, the pattern registry and
    the ``canvod-preflight`` command) is left over from development
    and will be removed with the next major version. Use naming recipes
    (``canvod-filemap``) and ``canvodpy config validate`` instead.
"""

from importlib.metadata import version as _version

__version__ = _version("canvod-preflight")

# Config models — describe the site/receiver naming setup
from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig

# Convention types — needed when callers inspect matched files
from .convention import (
    AgencyId,
    CanVODFilename,
    ContentCode,
    Duration,
    FileType,
    ReceiverType,
    SiteId,
    find_overlaps,
)

# Mapping engine — physical filenames -> canonical names
from .mapping import FilenameMapper, VirtualFile

# Pattern registry — glob/regex matching for known filename styles
from .patterns import BUILTIN_PATTERNS, SourcePattern, match_pattern

# Validation API — primary public surface
from .validator import DataDirectoryValidator, ValidationReport

__all__ = [
    "BUILTIN_PATTERNS",
    "AgencyId",
    "CanVODFilename",
    "ContentCode",
    "DataDirectoryValidator",
    "DirectoryLayout",
    "Duration",
    "FileType",
    "FilenameMapper",
    "ReceiverNamingConfig",
    "ReceiverType",
    "SiteId",
    "SiteNamingConfig",
    "SourcePattern",
    "ValidationReport",
    "VirtualFile",
    "find_overlaps",
    "match_pattern",
]
