"""RINEX v3.04 validation constants.

Observation codes, valid ranges, and system-specific constraints
based on RINEX Version 3.04 specification (November 23, 2018).

Tables extracted from:
- Table 4: GPS Observation Codes
- Table 5: GLONASS Observation Codes
- Table 6: Galileo Observation Codes
- Table 7: SBAS Observation Codes
- Table 8: QZSS Observation Codes
- Table 9: BDS Observation Codes
- Table 10: IRNSS Observation Codes
"""

from typing import Final

# Type aliases for band tables
BandCodes = set[str]
BandSpec = dict[str, float | str | BandCodes]
BandTable = dict[str, BandSpec]

# ========================================
# GNSS System Identifiers
# ========================================
GNSS_SYSTEMS: Final[set[str]] = {"G", "R", "E", "C", "J", "S", "I"}

SYSTEM_NAMES: Final[dict[str, str]] = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "S": "SBAS",
    "I": "IRNSS",
}

# ========================================
# GPS (Table 4)
# ========================================
GPS_BANDS: Final[BandTable] = {
    "1": {
        "name": "L1",
        "frequency": 1575.42,  # MHz
        "bandwidth": 30.69,  # MHz
        "codes": {"C", "S", "L", "X", "P", "W", "Y", "M", "N"},
    },
    "2": {
        "name": "L2",
        "frequency": 1227.60,
        "bandwidth": 30.69,
        "codes": {"C", "D", "S", "L", "X", "P", "W", "Y", "M", "N"},
    },
    "5": {
        "name": "L5",
        "frequency": 1176.45,
        "bandwidth": 24.0,
        "codes": {"I", "Q", "X"},
    },
}

# ========================================
# GLONASS (Table 5)
# ========================================
GLONASS_BANDS: Final[BandTable] = {
    "1": {
        "name": "G1",
        "frequency_base": 1602.0,  # MHz, channel k at base + k * spacing
        "channel_spacing": 0.5625,  # MHz (9/16), FDMA ICD 5.1, Table 3.1
        "bandwidth": 9.0,
        "codes": {"C", "P"},
    },
    "2": {
        "name": "G2",
        "frequency_base": 1246.0,  # MHz, channel k at base + k * spacing
        "channel_spacing": 0.4375,  # MHz (7/16), FDMA ICD 5.1, Table 3.1
        "bandwidth": 9.0,
        "codes": {"C", "P"},
    },
    "3": {
        "name": "G3",
        "frequency": 1202.025,
        "bandwidth": 20.0,
        "codes": {"I", "Q", "X"},
    },
    "4": {
        "name": "G1a",
        "frequency": 1600.995,
        "bandwidth": 7.875,
        "codes": {"A", "B", "X"},
    },
    "6": {
        "name": "G2a",
        "frequency": 1248.06,
        "bandwidth": 7.875,
        "codes": {"A", "B", "X"},
    },
}

# GLONASS frequency numbers
GLONASS_FREQ_NUMBERS: Final[list[int]] = list(range(-7, 13))  # -7 to +12

# ========================================
# Galileo (Table 6)
# ========================================
GALILEO_BANDS: Final[BandTable] = {
    "1": {
        "name": "E1",
        "frequency": 1575.42,
        "bandwidth": 24.552,
        "codes": {"A", "B", "C", "X", "Z"},
    },
    "5": {
        "name": "E5a",
        "frequency": 1176.45,
        "bandwidth": 20.46,
        "codes": {"I", "Q", "X"},
    },
    "7": {
        "name": "E5b",
        "frequency": 1207.14,
        "bandwidth": 20.46,
        "codes": {"I", "Q", "X"},
    },
    "8": {
        "name": "E5",
        "frequency": 1191.795,
        "bandwidth": 51.15,
        "codes": {"I", "Q", "X"},
    },
    "6": {
        "name": "E6",
        "frequency": 1278.75,
        "bandwidth": 40.92,
        "codes": {"A", "B", "C", "X", "Z"},
    },
}

# ========================================
# SBAS (Table 7)
# ========================================
SBAS_BANDS: Final[BandTable] = {
    "1": {
        "name": "L1",
        "frequency": 1575.42,
        "codes": {"C"},
    },
    "5": {
        "name": "L5",
        "frequency": 1176.45,
        "codes": {"I", "Q", "X"},
    },
}

# ========================================
# QZSS (Table 8)
# ========================================
QZSS_BANDS: Final[BandTable] = {
    "1": {
        "name": "L1",
        "frequency": 1575.42,
        "codes": {"C", "S", "L", "X", "Z"},
    },
    "2": {
        "name": "L2",
        "frequency": 1227.60,
        "codes": {"S", "L", "X"},
    },
    "5": {
        "name": "L5",
        "frequency": 1176.45,
        "codes": {"I", "Q", "X", "D", "P", "Z"},
    },
    "6": {
        "name": "L6",
        "frequency": 1278.75,
        "codes": {"S", "L", "X", "E", "Z"},
    },
}

# ========================================
# BeiDou (Table 9)
# ========================================
BEIDOU_BANDS: Final[BandTable] = {
    "2": {
        "name": "B1-2",
        "frequency": 1561.098,
        "codes": {"I", "Q", "X"},
    },
    "1": {
        "name": "B1",
        "frequency": 1575.42,
        "codes": {"D", "P", "X", "A", "N"},
    },
    "5": {
        "name": "B2a",
        "frequency": 1176.45,
        "codes": {"D", "P", "X"},
    },
    "7": {
        "name": "B2b",
        "frequency": 1207.140,
        "codes": {"I", "Q", "X", "D", "P", "Z"},
    },
    "8": {
        "name": "B2",
        "frequency": 1191.795,
        "codes": {"D", "P", "X"},
    },
    "6": {
        "name": "B3",
        "frequency": 1268.52,
        "codes": {"I", "Q", "X", "A"},
    },
}

# ========================================
# IRNSS (Table 10)
# ========================================
IRNSS_BANDS: Final[BandTable] = {
    "5": {
        "name": "L5",
        "frequency": 1176.45,
        "codes": {"A", "B", "C", "X"},
    },
    "9": {
        "name": "S",
        "frequency": 2492.028,
        "codes": {"A", "B", "C", "X"},
    },
}

# ========================================
# Combined System Observation Codes
# ========================================
VALID_OBS_CODES: Final[dict[str, BandTable]] = {
    "G": GPS_BANDS,
    "R": GLONASS_BANDS,
    "E": GALILEO_BANDS,
    "C": BEIDOU_BANDS,
    "J": QZSS_BANDS,
    "S": SBAS_BANDS,
    "I": IRNSS_BANDS,
}

# ========================================
# Observation Types
# ========================================
OBSERVATION_TYPES: Final[dict[str, str]] = {
    "C": "Pseudorange",
    "L": "Carrier phase",
    "D": "Doppler",
    "S": "Signal strength",
    "I": "Ionosphere delay",
    "X": "Receiver channel",
}

# ========================================
# Signal Strength Ranges (Table 12)
# ========================================
SIGNAL_STRENGTH_RANGES: Final[dict[int, tuple[int, int]]] = {
    1: (0, 12),  # < 12 dBHz
    2: (12, 17),
    3: (18, 23),
    4: (24, 29),
    5: (30, 35),  # Threshold for good tracking
    6: (36, 41),
    7: (42, 47),
    8: (48, 53),
    9: (54, 999),  # >= 54 dBHz
}

# ========================================
# Epoch Flags
# ========================================
EPOCH_FLAGS: Final[dict[int, str]] = {
    0: "OK",
    1: "Power failure between previous and current epoch",
    2: "Start moving antenna",
    3: "New site occupation",
    4: "Header info follows",
    5: "External event",
    6: "Cycle slip",
}

# ========================================
# Time Systems
# ========================================
TIME_SYSTEMS: Final[set[str]] = {"GPS", "GLO", "GAL", "QZS", "BDT", "IRN"}

TIME_SYSTEM_DEFAULTS: Final[dict[str, str]] = {
    "G": "GPS",
    "R": "GLO",
    "E": "GAL",
    "C": "BDT",
    "J": "QZS",
    "S": "GPS",  # SBAS uses GPS time
    "I": "IRN",
}

# ========================================
# Phase Reference Signals (Table A23)
# ========================================
PHASE_REFERENCE_SIGNALS: Final[dict[str, dict[str, str]]] = {
    "G": {
        "1": "C",  # L1: C/A is reference
        "2": "W",  # L2: Z-tracking is reference
        "5": "I",  # L5: I component is reference
    },
    "R": {
        "1": "C",  # G1: C/A is reference
        "2": "C",  # G2: C/A is reference
        "3": "I",  # G3: I component is reference
        "4": "A",  # G1a: A is reference
        "6": "A",  # G2a: A is reference
    },
    "E": {
        "1": "C",  # E1: C is reference
        "5": "I",  # E5a: I is reference
        "7": "I",  # E5b: I is reference
        "8": "I",  # E5: I is reference
        "6": "C",  # E6: C is reference
    },
    "C": {
        "2": "I",  # B1-2: I is reference
        "1": "P",  # B1: P is reference
        "5": "P",  # B2a: P is reference
        "7": "I",  # B2b: I is reference (BDS-2), P (BDS-3)
        "8": "P",  # B2: P is reference
        "6": "I",  # B3: I is reference
    },
    "J": {
        "1": "C",  # L1: C/A is reference (Block I)
        "2": "L",  # L2: L is reference
        "5": "Q",  # L5: Q is reference
        "6": "S",  # L6: S is reference
    },
    "S": {
        "1": "C",  # L1: C/A is reference
        "5": "I",  # L5: I is reference
    },
    "I": {
        "5": "A",  # L5: A is reference
        "9": "A",  # S: A is reference
    },
}

# ========================================
# Valid Marker Types
# ========================================
MARKER_TYPES: Final[set[str]] = {
    "GEODETIC",
    "NON_GEODETIC",
    "NON_PHYSICAL",
    "SPACEBORNE",
    "AIRBORNE",
    "WATER_CRAFT",
    "GROUND_CRAFT",
    "FIXED_BUOY",
    "FLOATING_BUOY",
    "FLOATING_ICE",
    "GLACIER",
    "BALLISTIC",
    "ANIMAL",
    "HUMAN",
}

# ========================================
# Observation Value Ranges
# ========================================
# Reasonable ranges for data validation
OBSERVATION_RANGES: Final[dict[str, tuple[float, float]]] = {
    "C": (15e6, 30e6),  # Pseudorange: 15M to 30M meters
    "L": (-1e9, 1e9),  # Phase: -1G to 1G cycles
    "D": (-50000, 50000),  # Doppler: -50k to 50k Hz
    "S": (0, 60),  # Signal strength: 0-60 dBHz
    "I": (-1e6, 1e6),  # Ionosphere delay: reasonable range
    "X": (1, 99),  # Channel number: 1-99
}

# ========================================
# RINEX File Types
# ========================================
FILE_TYPES: Final[dict[str, str]] = {
    "O": "Observation",
    "N": "Navigation (GPS)",
    "G": "Navigation (GLONASS)",
    "E": "Navigation (Galileo)",
    "C": "Navigation (BeiDou)",
    "J": "Navigation (QZSS)",
    "I": "Navigation (IRNSS)",
    "S": "Navigation (SBAS)",
    "M": "Meteorological",
}

# ========================================
# Required Header Records
# ========================================
REQUIRED_OBS_HEADER_RECORDS: Final[set[str]] = {
    "RINEX VERSION / TYPE",
    "PGM / RUN BY / DATE",
    "MARKER NAME",
    "OBSERVER / AGENCY",
    "REC # / TYPE / VERS",
    "ANT # / TYPE",
    "APPROX POSITION XYZ",
    "ANTENNA: DELTA H/E/N",
    "SYS / # / OBS TYPES",
    "TIME OF FIRST OBS",
    "END OF HEADER",
}

# Additional required for RINEX 3.01+
REQUIRED_301_HEADER_RECORDS: Final[set[str]] = {
    "SYS / PHASE SHIFT",  # Mandatory for phase alignment
}

# Additional required for GLONASS
REQUIRED_GLONASS_HEADER_RECORDS: Final[set[str]] = {
    "GLONASS SLOT / FRQ #",
    "GLONASS COD/PHS/BIS",
}

# ========================================
# GPS Week Number
# ========================================
GPS_WEEK_ZERO: Final[int] = 0  # Start: Jan 6, 1980
GPS_WEEK_ROLLOVER: Final[int] = 1024
BDT_WEEK_ZERO_GPS_WEEK: Final[int] = 1356  # BDT starts Jan 1, 2006

# ========================================
# Leap Seconds (as of 2017-01-01)
# ========================================
CURRENT_LEAP_SECONDS: Final[int] = 18  # GPS-UTC as of 2017

# ========================================
# Export all
# ========================================
__all__ = [
    "BDT_WEEK_ZERO_GPS_WEEK",
    "BEIDOU_BANDS",
    "CURRENT_LEAP_SECONDS",
    "EPOCH_FLAGS",
    "FILE_TYPES",
    "GALILEO_BANDS",
    "GLONASS_BANDS",
    "GLONASS_FREQ_NUMBERS",
    "GNSS_SYSTEMS",
    "GPS_BANDS",
    "GPS_WEEK_ROLLOVER",
    "GPS_WEEK_ZERO",
    "IRNSS_BANDS",
    "MARKER_TYPES",
    "OBSERVATION_RANGES",
    "OBSERVATION_TYPES",
    "PHASE_REFERENCE_SIGNALS",
    "QZSS_BANDS",
    "REQUIRED_301_HEADER_RECORDS",
    "REQUIRED_GLONASS_HEADER_RECORDS",
    "REQUIRED_OBS_HEADER_RECORDS",
    "SBAS_BANDS",
    "SIGNAL_STRENGTH_RANGES",
    "SYSTEM_NAMES",
    "TIME_SYSTEMS",
    "TIME_SYSTEM_DEFAULTS",
    "VALID_OBS_CODES",
]
