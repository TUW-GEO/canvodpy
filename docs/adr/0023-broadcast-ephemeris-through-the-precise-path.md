# The broadcast ephemeris of the canopy receiver, through the same interpolation as the precise ephemeris

*Proposed 2026-10-26.*

A run takes satellite angles from one ephemeris per store
(`ephemeris_source`, ADR 0019): the precise ephemeris (agency products,
SP3/CLK) or the broadcast ephemeris. Until now the broadcast ephemeris
worked only for SBF, whose SatVisibility blocks hold the angles the
receiver computed. RINEX receivers record the same navigation messages
in RINEX navigation files, which hold orbit parameters, not angles.
It is not settled that the precise ephemeris gives better VOD, and the
broadcast ephemeris is available in real time.

**`ephemeris_source` takes `precise` or `broadcast`.** `final` named a
product latency, not a source; it keeps working as a deprecated alias of
`precise` until v2.0.0, and a store that recorded `final` matches one
that records `precise`. With `broadcast`, the agency and the product
type do not apply and the content settings record them as empty.

**The broadcast ephemeris comes from the canopy receiver.** A satellite
the canopy does not receive needs no position. SBF and RINEX follow the
same rule: each receiver uses its own broadcast data, and in
shared-position mode the reference receiver uses the canopy's. A RINEX
receiver names its navigation files with `nav_directory`.

**Navigation records become satellite positions, then follow the precise
path.** For each satellite, the record whose reference time is nearest
gives the ECEF position and velocity on a 5-minute grid, where that
record is valid (the fit interval in the record for GPS, the validity
from each system's interface specification for the others). GPS,
Galileo, BeiDou and QZSS records are orbital elements, evaluated in
closed form; GLONASS and SBAS records are a position, velocity and
acceleration, integrated to the grid. The positions and velocities then
go through the existing Hermite interpolation and coordinate
transformation, so one implementation interpolates both ephemerides.
The broadcast clocks are not used.

**Missing data.** A day without navigation files stops the run with an
error that names what is missing. A satellite without a valid record at
some times gets no angles there, as when an SP3 file lacks a satellite.
Each such satellite is reported in the run's summary, in the run history
and in the day's log-book row. There is no fallback to the precise
ephemeris: a store holds one ephemeris.

**canvodpy reads RINEX 3.04/3.05 navigation files itself.** RINEX 2.11
navigation files follow later. The file name convention gains the type
`nav` and the sampling `00U`, which RINEX file names use for an
unspecified data frequency (RINEX 4.00, Table A1; RINEX navigation file
names may leave the field out, ours keep it), for example
`ROSA01TUW_R_20250010000_15M_00U_AA.nav`; other names need a naming
recipe.

## Considered options

- **`georinex` for reading and positions.** It read one receiver-day of
  the test data (96 navigation files) in 20.5 s, against about 3.4 s for
  the whole preparation of a day. Its position routine covers GPS and
  Galileo only and evaluates only at the record times.
- **The reference receiver's navigation data, or both receivers'
  pooled.** On the test data (2025-001), the canopy's own records cover
  what the canopy observes about as well as the reference's: better for
  BeiDou and GLONASS, slightly worse for GPS and Galileo. SBF already
  uses the canopy's.
- **Evaluating the navigation records directly at every observation
  epoch.** Accurate, but a second interpolation path next to the precise
  one.
- **Falling back to the precise ephemeris when navigation data is
  missing.** It mixes two ephemerides in one store.
- **Broadcast data on the provisional branch (#359).** Left out for now;
  it would leave the store with two ephemerides on two branches.

## Consequences

- RINEX users can process without agency products, and in real time.
- `final` in settings files gives a warning until v2.0.0.
- The angles of SBF and RINEX broadcast stores come from the same
  receiver, and can be compared.
