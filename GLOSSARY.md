# canVODpy

canVODpy computes vegetation optical depth from GNSS signals received
below a forest canopy and in the open, and keeps the data and results in
versioned stores. These are the words the project uses; use them in code,
docs, issues and messages.

## Science

**GNSS-T** (GNSS transmissometry):
Estimating how much vegetation weakens satellite navigation signals, by
comparing the same signal received below the canopy and in the open.
_Avoid_: GNSS-IR, GNSS reflectometry (different methods)

**VOD** (vegetation optical depth):
The attenuation of a microwave signal by vegetation along its path,
normalized to a vertical path; it tracks vegetation water content and
biomass.
_Avoid_: optical depth, tau (alone)

**Transmissivity**:
The fraction of a signal's power that passes through the canopy: the
canopy signal strength relative to the reference signal strength.
_Avoid_: transmittance

**SNR**:
The signal strength the receiver reports for a signal, in dB-Hz; the
observable VOD is computed from.
_Avoid_: C/N0, CN0, signal power

**Polar angle**:
The angle between the zenith and the direction to a satellite, seen from
the receiver (0 overhead, 90 degrees at the horizon).
_Avoid_: zenith angle, elevation (its complement)

**Azimuth**:
The direction to a satellite in the horizontal plane, clockwise from
north.

**Signal ID** (SID):
One signal of one satellite: satellite, frequency band and tracking code,
e.g. `G01|L1|C`.
_Avoid_: signal, channel, observable

**Epoch**:
The time of an observation, always GPS time.
_Avoid_: timestamp, time step

**Ephemeris**:
The orbit (and clock) of the satellites, from agency products or from
the receiver's broadcast navigation data; gives each epoch's polar angle
and azimuth.
_Avoid_: aux data, orbit file (for the data itself)

**Hemisphere grid**:
A division of the sky seen from the receiver into cells, used to
aggregate observations and VOD by direction.
_Avoid_: sky map, mesh

## Sites and receivers

**Site**:
A place with at least one canopy receiver and one reference receiver,
processed together into one GNSS store and one VOD store.
_Avoid_: station, location

**Canopy receiver**:
A receiver below the vegetation.
_Avoid_: forest receiver, below-canopy receiver

**Reference receiver**:
A receiver with an open view of the sky near the canopy receiver.
_Avoid_: sky receiver, open-sky receiver, clear-sky receiver

**VOD analysis**:
One pairing of a canopy receiver with a reference receiver for which VOD
is computed.
_Avoid_: pair, combination

**Receiver-day**:
One receiver's files of one GPS day; the unit a run processes.
_Avoid_: day file, batch

## Files

**canVOD file name**:
The file name convention that states a file's receiver identity, start
time, length, sampling and type, e.g.
`ROSA01TUW_R_20250010000_15M_05S_AA.rnx`.
_Avoid_: canonical name (in user-facing text), standard name

**Receiver identity**:
The first nine characters of a canVOD file name: site, receiver role,
receiver number and agency.
_Avoid_: station ID, marker name

**File type**:
The TYPE field at the end of a canVOD file name, naming the file's format
(e.g. `rnx`, `sbf`).
_Avoid_: extension

**Naming recipe**:
A description of how a receiver's own file names translate to canVOD file
names, for files not named by the convention.
_Avoid_: name mapping, pattern

**Reader format**:
The setting that tells a run which reader reads a receiver's files.
_Avoid_: file format (for the setting)

## Processing and storage

**Run**:
One processing of a site's receiver-days, started from the command line,
Python or Airflow; all three behave the same.
_Avoid_: job, pipeline execution

**Preprocessing**:
Optional changes to the observations before they are stored (temporal
aggregation, grid assignment), applied only when the settings ask for
them.
_Avoid_: filtering, cleaning

**Store**:
An Icechunk repository holding one site's GNSS data or VOD; a GNSS store
or a VOD store.
_Avoid_: repo, database

**GNSS store**:
A site's versioned store of the observations of all its receivers.
_Avoid_: RINEX store, observation store

**VOD store**:
A site's versioned store of the VOD of all its VOD analyses.

**Group**:
One receiver's data (in the GNSS store) or one VOD analysis's results
(in the VOD store).
_Avoid_: table, dataset (for the stored unit)

**Log book**:
The record a store keeps of what was written to each group: source files,
their hashes, and the preprocessing applied.
_Avoid_: metadata table, registry

**Day block**:
The part of a group that holds one receiver-day (or one day of a VOD
analysis): every possible epoch of that day at its cadence, with or
without data.
_Avoid_: day chunk, partition

**Cadence**:
The time between the epochs a day block holds: the sampling interval of
the day's files, or the aggregation interval when aggregation is set.
_Avoid_: resolution, frequency

**Snapshot**:
One committed state of a store, which can be read again later.
_Avoid_: version (for a store state), checkpoint

**Repository metadata** (Icechunk's term):
The description of a store that belongs to no snapshot and no branch:
who made it, what it holds, where, under which license. Some of its
fields never change; the others change only by amendment.
_Avoid_: global attributes, store identity

**Commit metadata** (Icechunk's term):
What one commit records about how it was made: software versions,
environment and settings of the run that wrote it.
_Avoid_: history, provenance (the log books hold provenance)

**Snapshot summary**:
The description of what one snapshot holds (time coverage, receivers,
counts), written in the same commit as the data it describes.
_Avoid_: statistics, store state

**Fixed field**:
A field of the repository metadata that never changes once the store
exists, such as its id or creation date.
_Avoid_: immutable field

**Amendable field**:
A field of the repository metadata that changes only by amendment, such
as the creator's email or the license.

**Amendment**:
A recorded change to an amendable field: old and new value, reason, who
and when.
_Avoid_: edit, update (for repository metadata)

**Metadata rule**:
A rule a standard sets for a metadata field, such as the license being an
SPDX identifier. New metadata that breaks one is refused; a store that
already breaks one still opens, with a warning, until an amendment fixes
the field, or, for a value computed from the data, the next commit.
_Avoid_: constraint, policy

**Catalog**:
The STAC description of all stores under one data root, kept beside
them: one item per store, grouped into GNSS observations and VOD.
_Avoid_: inventory, index

**Release**:
A named, fixed state of all stores under a data root: a tag in each
store plus a catalog that pins each store's snapshot.
_Avoid_: version (for a store state), export

**Plugin**:
An installed package that adds a reader or a VOD calculator to runs.
_Avoid_: extension (canvodpy-extensions are separate packages)
