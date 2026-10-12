"""Static lookup tables for Septentrio Binary Format (SBF) decoding.

All tables are derived from official Septentrio documentation.
Each entry carries an explicit source citation.  Do NOT modify values
without updating the corresponding source reference.

Primary source
--------------
AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide (Septentrio).
Matches the firmware series of the production test data (v4.14.4).
Abbreviated below as **RefGuide-4.14.0**.

Supplementary source
--------------------
AsteRx SB3 ProBase Firmware v4.15.1 Reference Guide (Septentrio).
Field-level definitions are identical to v4.14.0 for all blocks used here.

Frequencies
-----------
Carrier frequencies are fetched from the ``BAND_PROPERTIES`` class
attributes in :mod:`canvod.readers.gnss_specs.constellations` (single
source of truth).  Accessing them as class variables requires no
instantiation and triggers no network or file I/O.

BeiDou B2I (signal 29) shares the same carrier frequency as B2b
(1207.14 MHz); it is mapped to ``BEIDOU.BAND_PROPERTIES["B2b"]``.
GLONASS FDMA signals (8-11) have ``freq=None``; use
:func:`~canvod.readers.sbf._scaling.glonass_freq_hz` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pint

from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)

# ---------------------------------------------------------------------------
# SVID ranges
# Source: RefGuide-4.14.0, Table 4.1.9, p. 255
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SvidRange:
    """One contiguous range of Septentrio internal SVID values."""

    lo: int
    hi: int
    system: str  # RINEX single-letter system code
    prn_offset: int  # PRN = SVID - prn_offset
    description: str


# Ordered table; first matching range wins.
# Source: RefGuide-4.14.0, Table 4.1.9, p. 255
_SVID_RANGES: tuple[_SvidRange, ...] = (
    _SvidRange(1, 37, "G", 0, "GPS G01-G37"),
    _SvidRange(38, 61, "R", 37, "GLONASS R01-R24 (slot number)"),
    _SvidRange(62, 62, "R", 62, "GLONASS R00; slot number unknown"),
    _SvidRange(63, 68, "R", 38, "GLONASS R25-R30"),
    _SvidRange(71, 106, "E", 70, "Galileo E01-E36"),
    _SvidRange(107, 119, "L", 0, "L-Band MSS (see LBandBeams block)"),
    _SvidRange(120, 140, "S", 0, "SBAS S120-S140 (PRN = SVID)"),
    _SvidRange(141, 180, "C", 140, "BeiDou C01-C40"),
    _SvidRange(181, 187, "J", 180, "QZSS J01-J07"),
    # NOTE: v4.15.1 extends QZSS to 181-190 (J01-J10).  Only 181-187 in v4.14.x.
    _SvidRange(191, 197, "I", 190, "NavIC/IRNSS I01-I07"),
    _SvidRange(198, 215, "S", 57, "SBAS S141-S158  (RINEX: Snn, nn = SVID - 57)"),
    _SvidRange(216, 222, "I", 208, "NavIC I08-I14"),
    _SvidRange(223, 245, "C", 182, "BeiDou C41-C63"),
)


def decode_svid(svid: int) -> tuple[str, int]:
    """Map a Septentrio internal SVID to ``(system, prn)``.

    Parameters
    ----------
    svid : int
        Septentrio internal satellite identifier (field type ``u1``).

    Returns
    -------
    system : str
        RINEX single-letter system code
        (``"G"``, ``"R"``, ``"E"``, ``"C"``, ``"J"``, ``"I"``, ``"S"``, ``"L"``).
    prn : int
        Satellite PRN number (or GLONASS slot number).
        ``0`` for GLONASS with unknown slot (SVID 62).

    Notes
    -----
    Source: RefGuide-4.14.0, Table 4.1.9, p. 255.
    Unknown SVIDs return ``("?", svid)``.
    """
    for r in _SVID_RANGES:
        if r.lo <= svid <= r.hi:
            return r.system, svid - r.prn_offset
    return "?", svid


# ---------------------------------------------------------------------------
# Frequency lookup: (system, sbf_band) → pint.Quantity
#
# Built from gnss_specs constellation BAND_PROPERTIES ClassVars — no
# instantiation, no network, no file I/O.
#
# BeiDou B2I maps to "B2b" in gnss_specs (same carrier: 1207.14 MHz).
# GLONASS G3 is CDMA (fixed freq); FDMA G1/G2 are intentionally absent
# (their freq is slot-dependent and looked up via glonass_freq_hz()).
# L-Band MSS ("LBd") has no fixed carrier and is intentionally absent.
#
# _X_BP aliases are typed as Any to work around pint's incomplete type stubs
# (BAND_PROPERTIES ClassVars resolve to Quantity[Unknown] in Pylance).
# Runtime values are pint.Quantity[float] in MHz.
# ---------------------------------------------------------------------------

_GPS_BP: Any = GPS.BAND_PROPERTIES
_QZSS_BP: Any = QZSS.BAND_PROPERTIES
_GLONASS_BP: Any = GLONASS.BAND_PROPERTIES
_BEIDOU_BP: Any = BEIDOU.BAND_PROPERTIES
_IRNSS_BP: Any = IRNSS.BAND_PROPERTIES
_GALILEO_BP: Any = GALILEO.BAND_PROPERTIES
_SBAS_BP: Any = SBAS.BAND_PROPERTIES

_BAND_FREQ: dict[tuple[str, str], Any] = {
    # GPS
    ("G", "L1"): _GPS_BP["L1"]["freq"],
    ("G", "L2"): _GPS_BP["L2"]["freq"],
    ("G", "L5"): _GPS_BP["L5"]["freq"],
    # QZSS
    ("J", "L1"): _QZSS_BP["L1"]["freq"],
    ("J", "L2"): _QZSS_BP["L2"]["freq"],
    ("J", "L5"): _QZSS_BP["L5"]["freq"],
    ("J", "L6"): _QZSS_BP["L6"]["freq"],
    # GLONASS — G3 CDMA only; FDMA (G1, G2) resolved via glonass_freq_hz()
    ("R", "G3"): _GLONASS_BP["G3"]["freq"],
    # BeiDou
    ("C", "B1C"): _BEIDOU_BP["B1C"]["freq"],
    ("C", "B2a"): _BEIDOU_BP["B2a"]["freq"],
    ("C", "B2b"): _BEIDOU_BP["B2b"]["freq"],
    ("C", "B1I"): _BEIDOU_BP["B1I"]["freq"],
    ("C", "B2I"): _BEIDOU_BP["B2b"]["freq"],  # B2I shares 1207.14 MHz with B2b
    ("C", "B3I"): _BEIDOU_BP["B3I"]["freq"],
    # NavIC / IRNSS
    ("I", "L5"): _IRNSS_BP["L5"]["freq"],
    # Galileo
    ("E", "E1"): _GALILEO_BP["E1"]["freq"],
    ("E", "E5a"): _GALILEO_BP["E5a"]["freq"],
    ("E", "E5b"): _GALILEO_BP["E5b"]["freq"],
    ("E", "E6"): _GALILEO_BP["E6"]["freq"],
    ("E", "E5"): _GALILEO_BP["E5"]["freq"],
    # SBAS
    ("S", "L1"): _SBAS_BP["L1"]["freq"],
    ("S", "L5"): _SBAS_BP["L5"]["freq"],
}


# ---------------------------------------------------------------------------
# Signal type table
# Source: RefGuide-4.14.0, Table 4.1.10, p. 256
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalDef:  # pylint: disable=too-many-instance-attributes
    """Definition of a tracked GNSS signal modulation.

    Attributes
    ----------
    number : int
        Signal type index (bits 0-4 of the SBF ``Type`` byte).
    signal_type : str
        Septentrio signal label, e.g. ``"L1CA"``, ``"E5a"``, ``"B1I"``.
    system : str
        RINEX system letter of the native constellation for this signal number.
    freq : pint.Quantity or None
        Carrier frequency fetched from
        :data:`~canvod.readers.gnss_specs.constellations` BAND_PROPERTIES.
        ``None`` for GLONASS FDMA signals (8-11) — use
        :func:`~canvod.readers.sbf._scaling.glonass_freq_hz` — and for
        L-Band MSS (signal 23).
    rinex_obs : str
        RINEX 3 observation code, e.g. ``"1C"``, ``"7Q"``, ``"2I"``.
    band : str
        Human-readable band label, e.g. ``"L1"``, ``"E5b"``, ``"B1I"``.
    code : str
        Tracking code letter used in the RINEX obs code, e.g. ``"C"``, ``"I"``.
    cn0_no_offset : bool
        ``True`` only for signal numbers 1 (GPS L1P) and 2 (GPS L2P).
        These use ``C/N0 = raw * 0.25`` (no +10 dB offset).
        All other signals use ``C/N0 = raw * 0.25 + 10``.

    Notes
    -----
    Source: RefGuide-4.14.0, Table 4.1.10, p. 256.
    CN0 formula: RefGuide-4.14.0, MeasEpochChannelType1.CN0, p. 261.
    Frequencies sourced from :mod:`canvod.readers.gnss_specs.constellations`.
    """

    number: int
    signal_type: str
    system: str
    freq: pint.Quantity | None  # type: ignore[type-arg]
    rinex_obs: str
    band: str
    code: str
    cn0_no_offset: bool


# fmt: off
# Raw signal definitions: (num, signal_type, system, band, rinex_obs, code, cn0_no_offset)
# Frequencies are looked up from _BAND_FREQ at build time.
# Source: RefGuide-4.14.0, Table 4.1.10, p. 256.
# Signals marked "Reserved" or "Tentative" are omitted unless observed in data.
_RAW: tuple[tuple[Any, ...], ...] = (
    # num  signal_type  sys   band    rinex  code   no_off
    # --- GPS -----------------------------------------------------------
    (0,  "L1CA", "G", "L1",  "1C",  "C",  False),
    (1,  "L1P",  "G", "L1",  "1W",  "W",  True ),  # CN0: no +10
    (2,  "L2P",  "G", "L2",  "2W",  "W",  True ),  # CN0: no +10
    (3,  "L2C",  "G", "L2",  "2L",  "L",  False),
    (4,  "L5",   "G", "L5",  "5Q",  "Q",  False),
    (5,  "L1C",  "G", "L1",  "1L",  "L",  False),
    # --- QZSS ----------------------------------------------------------
    (6,  "L1CA", "J", "L1",  "1C",  "C",  False),
    (7,  "L2C",  "J", "L2",  "2L",  "L",  False),
    # --- GLONASS (FDMA: freq=None — use glonass_freq_hz()) -------------
    (8,  "L1CA", "R", "G1",  "1C",  "C",  False),
    (9,  "L1P",  "R", "G1",  "1P",  "P",  False),
    (10, "L2P",  "R", "G2",  "2P",  "P",  False),
    (11, "L2CA", "R", "G2",  "2C",  "C",  False),
    (12, "L3",   "R", "G3",  "3Q",  "Q",  False),  # CDMA: fixed freq
    # --- BeiDou --------------------------------------------------------
    (13, "B1C",  "C", "B1C", "1P",  "P",  False),
    (14, "B2a",  "C", "B2a", "5P",  "P",  False),
    # --- NavIC / IRNSS -------------------------------------------------
    (15, "L5",   "I", "L5",  "5A",  "A",  False),
    # 16: Reserved
    # --- Galileo -------------------------------------------------------
    (17, "E1",   "E", "E1",  "1C",  "C",  False),
    # 18: Reserved
    (19, "E6",   "E", "E6",  "6C",  "C",  False),  # or 6B (CommonFlags bit 6)
    (20, "E5a",  "E", "E5a", "5Q",  "Q",  False),
    (21, "E5b",  "E", "E5b", "7Q",  "Q",  False),
    (22, "E5",   "E", "E5",  "8Q",  "Q",  False),  # AltBOC
    (23, "LBand","L", "LBd", "NA",  "?",  False),  # L-Band MSS: no fixed freq
    # --- SBAS ----------------------------------------------------------
    (24, "L1CA", "S", "L1",  "1C",  "C",  False),
    (25, "L5",   "S", "L5",  "5I",  "I",  False),
    # --- QZSS continued ------------------------------------------------
    (26, "L5",   "J", "L5",  "5Q",  "Q",  False),
    (27, "L6",   "J", "L6",  "6E",  "E",  False),
    # --- BeiDou continued (WARNING: 28=B1I, 29=B2I — not swapped) -----
    (28, "B1I",  "C", "B1I", "2I",  "I",  False),  # 1561.098 MHz
    (29, "B2I",  "C", "B2I", "7I",  "I",  False),  # 1207.14 MHz (same carrier as B2b)
    (30, "B3I",  "C", "B3I", "6I",  "I",  False),
    # 31: reserved as SigIdxLo==31 flag (extended signal number in ObsInfo)
    # --- QZSS continued ------------------------------------------------
    (32, "L1C",  "J", "L1",  "1L",  "L",  False),
    (33, "L1S",  "J", "L1",  "1Z",  "Z",  False),  # SLAS
    # --- BeiDou continued ----------------------------------------------
    (34, "B2b",  "C", "B2b", "7D",  "D",  False),
    # 35-37: Reserved
    # --- QZSS tentative (marked "Tentative" in RefGuide-4.14.0) -------
    (38, "L1CB", "J", "L1",  "1E",  "E",  False),
    (39, "L5S",  "J", "L5",  "5P",  "P",  False),
)
# fmt: on

_SIGNAL_DEFS: tuple[SignalDef, ...] = tuple(
    SignalDef(
        number=num,
        signal_type=sig_type,
        system=sys,
        freq=_BAND_FREQ.get((sys, band)),  # None for FDMA G1/G2 and L-Band MSS
        rinex_obs=rinex,
        band=band,
        code=code,
        cn0_no_offset=no_off,
    )
    for num, sig_type, sys, band, rinex, code, no_off in _RAW
)

#: Fast O(1) lookup: signal number -> SignalDef.
SIGNAL_TABLE: dict[int, SignalDef] = {s.number: s for s in _SIGNAL_DEFS}

#: GLONASS FDMA signal numbers (frequency depends on FreqNr, not fixed).
#: Source: RefGuide-4.14.0, Table 4.1.10, p. 256, frequency column footnote.
FDMA_SIGNAL_NUMS: frozenset[int] = frozenset({8, 9, 10, 11})
