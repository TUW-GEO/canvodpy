---
name: add-constellation
description: Add or extend a GNSS constellation (system prefix, bands, codes, frequencies, PRN range) in canvod-readers. Use when a receiver reports a system or signal canvodpy does not know.
---

# Add a constellation

All constellations live in one module,
`packages/canvod-readers/src/canvod/readers/gnss_specs/constellations.py`:
a `ConstellationBase` class and one subclass per system (GPS, GALILEO,
GLONASS, BEIDOU, SBAS, IRNSS, QZSS). Use the closest one as the template;
GLONASS for frequency-division systems (one frequency channel per
satellite).

## Steps

1. Subclass `ConstellationBase` in `packages/canvod-readers/src/canvod/readers/gnss_specs/constellations.py`: `SYSTEM_PREFIX`
   (the RINEX system letter), `BANDS`, `BAND_CODES`, `BAND_PROPERTIES`,
   the valid PRNs. Take the numbers from the interface control document
   and cite it in a comment: title, version, section or table, and the
   download link. Don't add the document to the repository: it would ship
   with the package, and most are not ours to redistribute.
2. Bands and signals: `packages/canvod-readers/src/canvod/readers/gnss_specs/bands.py`, `packages/canvod-readers/src/canvod/readers/gnss_specs/signals.py`,
   `packages/canvod-readers/src/canvod/readers/gnss_specs/obs_codes.py` (RINEX observation codes to SIDs).
3. Satellite catalog: systems in the IGS SINEX metadata are found by
   `SYSTEM_PREFIX` (`packages/canvod-readers/src/canvod/readers/gnss_specs/satellite_catalog.py`).
4. Each reader maps its own codes: check RINEX (`packages/canvod-readers/src/canvod/readers/rinex/`), SBF
   (`packages/canvod-readers/src/canvod/readers/sbf/_registry.py`) and NMEA (`packages/canvod-readers/src/canvod/readers/nmea/`).

SIDs are part of every store: a change to how an existing system's SIDs
are built makes new data incompatible with stored data. Ask the user
before changing existing SIDs.

## Tests

PRN range, band frequencies, SIDs from a real file of the new system:
`just test-package canvod-readers`.
