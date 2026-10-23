"""GNSS data format readers.

This package provides readers for various GNSS data formats, all implementing
a common interface for seamless integration with processing pipelines.

Supported formats:
- RINEX v3.04 observations (``Rnxv3Obs``)
- RINEX v2.11 observations (``Rnxv2Obs``)
- Septentrio Binary Format, SBF (``SbfReader``)
- NMEA (``NmeaObs``)

Quick Start
-----------
```python
from canvod.readers import Rnxv3Obs

# Read RINEX v3 file
reader = Rnxv3Obs(fpath="station.24o")
dataset = reader.to_ds()
```

Or use the canvodpy factory, which picks the reader from the file's content
(RINEX v2, RINEX v3 or NMEA):
```python
from canvodpy import ReaderFactory

reader = ReaderFactory.create_from_file("station.24o")
dataset = reader.to_ds()
```
"""

from importlib.metadata import version as _version

from canvod.readers.base import (
    DEFAULT_REQUIRED_VARS,
    REQUIRED_ATTRS,
    REQUIRED_COORDS,
    REQUIRED_DIMS,
    VOD_REQUIRED_VARS,
    DatasetStructureValidator,
    GNSSDataReader,
    SignalID,
    validate_dataset,
    validate_vod_dataset,
)
from canvod.readers.builder import DatasetBuilder, sid_coords
from canvod.readers.matching import (
    DataDirMatcher,
    MatchedDirs,
    PairDataDirMatcher,
    PairMatchedDirs,
)
from canvod.readers.nmea.v4_00 import NmeaObs
from canvod.readers.rinex.v2_11 import Rnxv2Obs
from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.readers.sbf import SbfEpoch, SbfHeader, SbfReader, SbfSignalObs
from canvod.utils.tools import YYYYDOY

__version__ = _version("canvod-readers")

__all__ = [
    "DEFAULT_REQUIRED_VARS",
    "REQUIRED_ATTRS",
    "REQUIRED_COORDS",
    "REQUIRED_DIMS",
    "VOD_REQUIRED_VARS",
    "YYYYDOY",
    "DataDirMatcher",
    "DatasetBuilder",
    "DatasetStructureValidator",
    "GNSSDataReader",
    "MatchedDirs",
    "NmeaObs",
    "PairDataDirMatcher",
    "PairMatchedDirs",
    "Rnxv2Obs",
    "Rnxv3Obs",
    "SbfEpoch",
    "SbfHeader",
    "SbfReader",
    "SbfSignalObs",
    "SignalID",
    "sid_coords",
    "validate_dataset",
    "validate_vod_dataset",
]
