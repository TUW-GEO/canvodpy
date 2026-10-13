# `canvod.readers` API reference

RINEX observation file parsing with validation and GNSS signal specifications.

## Package

::: canvod.readers
    options:
      members:
        - GNSSDataReader
        - SignalID
        - DatasetBuilder
        - sid_coords
        - DatasetStructureValidator
        - validate_dataset
        - validate_vod_dataset
        - Rnxv3Obs
        - SbfReader
        - MatchedDirs
        - PairMatchedDirs

## RINEX v3.04

::: canvod.readers.rinex.v3_04

## Base reader

::: canvod.readers.base

## Dataset builder

::: canvod.readers.builder

## GNSS specifications

::: canvod.readers.gnss_specs
    options:
      members:
        - signals
        - obs_codes
        - bands
        - constellations
        - metadata
        - models

## Directory matching

::: canvod.readers.matching
