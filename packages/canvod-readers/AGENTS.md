# canvod-readers

Readers turn one receiver file into an `xarray.Dataset` on
`(epoch, sid)`. This package also owns the dataset contracts that every
other package and canvodpy-extensions check against.

## Where things live

| Path (under `src/canvod/readers/`) | What |
|---|---|
| `base.py` | `GNSSDataReader` ABC; `validate_dataset`, `validate_vod_dataset` and the contract constants: the truth for dims, coordinates, variables, attributes |
| `builder.py` | `DatasetBuilder`, `sid_coords`: how SIDs and their coordinates are built |
| `rinex/v3_04.py` | RINEX 3 (`Rnxv3Obs`) |
| `rinex/v2_11.py` | RINEX 2.11 (`Rnxv2Obs`) |
| `sbf/reader.py` | Septentrio SBF (`SbfReader`) |
| `nmea/v4_00.py` | NMEA (`NmeaObs`) |
| `gnss_specs/` | Constellations, bands, signals, satellite catalog |
| `matching/` | Deprecated directory matchers; discovery lives in `canvodpy.orchestrator.discovery` |

Background: `docs/packages/readers/building-a-reader.md`,
`docs/packages/readers/rinex-format.md`,
`docs/packages/readers/sbf-decoding.md`.

## Invariants

- Every reader's output passes `validate_dataset`. New code imports the
  contract from `base.py`; it never restates it.
- SIDs are built in `builder.py` only, so readers and stores agree.
- Every stored epoch is GPS time; `epoch.attrs["time_system"]` is `"GPS"`
  (`epoch_coord_attrs` refuses anything else). RINEX: the header's
  `TIME OF FIRST OBS` time system (mandatory) must be GPS, other scales are
  refused, not converted. SBF is GPS time (TOW/WNc, no leap seconds). NMEA
  is UTC, converted with the leap-second table of the date
  (`gnss_specs/leap_seconds.py`, extend it with each IERS Bulletin C).
  `DatasetBuilder(time_system="GPS")` is required.
- RINEX 3: the validated parser is the default. `parser="unvalidated_fast"`
  stays opt-in, warns on every use (`UnvalidatedParserWarning`) and must
  give the same dataset on valid files.
- SBF: one decoder for observations and auxiliary blocks, paired by time
  of week. Epochs stay in GPS time; never subtract leap seconds.
- Every reader sets the class attribute `file_type` (TYPE field of its
  files' canVOD names). `aggregate_glonass_fdma` is declared on
  `GNSSDataReader`; `False` is refused unless the reader sets
  `per_channel_glonass = True` (the RINEX readers).
- Readers in other packages reach `canvodpy run` as plugins (entry point
  group `canvodpy.readers`, `docs/guides/plugins.md`); keep that page in
  step with the `GNSSDataReader` contract.
- Readers don't read the settings file. Options arrive as arguments;
  `keep_data_vars=None` keeps every variable.

## Tests

```bash
just test-package canvod-readers
```

Real files come from the `test_data` submodule; tests that need them are
marked `integration` and skip without it.
