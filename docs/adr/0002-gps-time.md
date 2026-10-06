# All stored epochs are GPS time

RINEX observation files, SBF and the orbit and clock products are GPS time
natively, receivers sample on whole GPS seconds and files are named by GPS
day. Storing UTC would move epochs 18 s off the sampling grid and across
day boundaries. Readers convert other scales on read (NMEA from UTC) and
record the scale; a RINEX file that declares another time scale is
refused, and so is an append to a store written without a recorded time
scale.

## Consequences

The leap second table ends at the last announced IERS Bulletin C and
raises after it; extend it with each new bulletin.
