"""GNSS specifications and core characteristics.

This module contains fundamental GNSS definitions including:
- Constants: Unit registry, physical constants, RINEX parameters
- Exceptions: GNSS-specific error types
- Metadata: CF-compliant metadata for coordinates and observables
- Models: Pydantic validation models for RINEX data structures
- Signals: Signal ID mapping and band properties
- Obs codes: RINEX observation code <-> signal ID mapping
- Utils: File hashing, version extraction, data type checks

These components are used across all GNSS reader implementations.
"""

from canvod.readers.gnss_specs.obs_codes import obs_code_for_sid, sid_for_obs_code
from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog

__all__ = ["SatelliteCatalog", "obs_code_for_sid", "sid_for_obs_code"]
