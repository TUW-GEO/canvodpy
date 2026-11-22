"""GNSS specifications and core characteristics.

This module contains fundamental GNSS definitions including:
- Constants: Unit registry, physical constants, RINEX parameters
- Exceptions: GNSS-specific error types
- Metadata: CF-compliant metadata for coordinates and observables
- Models: Pydantic validation models for RINEX data structures
- Signals: Signal ID mapping and band properties
- GLONASS FDMA: carrier frequency per channel, channel per satellite and date
- Obs codes: RINEX observation code <-> signal ID mapping
- Utils: File hashing, version extraction, data type checks

These components are used across all GNSS reader implementations.
"""

from canvod.readers.gnss_specs.glonass_fdma import (
    glonass_carrier_frequency_hz,
    glonass_channel,
    glonass_fdma_frequency_hz,
)
from canvod.readers.gnss_specs.obs_codes import obs_code_for_sid, sid_for_obs_code
from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog

__all__ = [
    "SatelliteCatalog",
    "glonass_carrier_frequency_hz",
    "glonass_channel",
    "glonass_fdma_frequency_hz",
    "obs_code_for_sid",
    "sid_for_obs_code",
]
