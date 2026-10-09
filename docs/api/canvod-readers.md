# canvod.readers API Reference

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

## Base Reader

::: canvod.readers.base

## Dataset Builder

::: canvod.readers.builder

## GNSS Specifications

::: canvod.readers.gnss_specs
    options:
      members:
        - signals
        - obs_codes
        - bands
        - constellations
        - metadata
        - models

## Directory Matching

::: canvod.readers.matching
