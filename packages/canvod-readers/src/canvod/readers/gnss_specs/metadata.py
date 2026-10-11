"""Metadata definitions for RINEX datasets.

Defines CF-compliant metadata for xarray.Dataset coordinates, data variables,
and global attributes. Used by all readers to ensure consistent NetCDF output
compatible with downstream VOD calculations and storage operations.

Module Contents
---------------
OBSERVABLES_METADATA : dict
    Metadata for GNSS observables (Pseudorange, Phase, Doppler, etc.)
CN0_METADATA : dict
    Metadata for Carrier-to-Noise density ratio (C/N0) measurements.
SNR_METADATA : dict
    Metadata for Signal-to-Noise ratio (SNR) measurements.
COORDS_METADATA : dict
    Metadata for dataset coordinates (epoch, sid, sv, etc.)
DTYPES : dict
    Data types for coordinates and variables.
DATAVARS_TO_BE_FILLED : dict
    Metadata for auxiliary variables (r, theta, phi, v, a).

Notes
-----
All metadata follows CF (Climate and Forecast) conventions for NetCDF files
to ensure interoperability with standard tools and libraries.

See Also
--------
canvod.readers.base.validate_dataset : Validates dataset structure

"""

from typing import Any, Final

import numpy as np

from canvod.readers.gnss_specs.constants import FREQ_UNIT

# -------------------
# Observable metadata
# -------------------
OBSERVABLES_METADATA: Final[dict[str, dict[str, Any]]] = {
    "Pseudorange": {
        "long_name": "GNSS Pseudorange",
        "coverage_content_type": "physicalMeasurement",
        "units": "meters",
        "valid_min": 0.0,
        "description": (
            "The pseudorange is the raw distance measurement between the GNSS "
            "satellite and receiver, including any timing errors due to "
            "satellite and receiver clocks."
        ),
        "comment": (
            "Pseudorange values represent the apparent distance from the "
            "satellite to the receiver and include biases from satellite and "
            "receiver clock errors."
        ),
        "_FillValue": np.nan,
    },
    "Doppler": {
        "long_name": "GNSS Doppler Shift",
        "coverage_content_type": "physicalMeasurement",
        "units": "Hz",
        "valid_min": -10_000.0,
        "description": (
            "The Doppler shift represents the rate of change in the phase of "
            "the GNSS signal due to the relative motion between the satellite "
            "and receiver."
        ),
        "comment": (
            "Doppler shift values are used to determine the relative velocity "
            "between the GNSS satellite and the receiver. Positive values "
            "indicate the satellite is moving toward the receiver, while "
            "negative values indicate it is moving away."
        ),
        "_FillValue": np.nan,
    },
    "Phase": {
        "long_name": "GNSS Carrier Phase",
        "coverage_content_type": "physicalMeasurement",
        "units": "cycles",
        "description": (
            "The carrier phase is the accumulated phase change of the GNSS "
            "signal's carrier wave from the satellite to the receiver, "
            "representing precise distance measurements."
        ),
        "comment": (
            "Carrier phase measurements are relative to an arbitrary reference "
            "cycle and may include an unknown integer ambiguity. They provide "
            "high-precision data for positioning applications when combined "
            "with pseudorange measurements."
        ),
        "_FillValue": np.nan,
    },
    "LLI": {
        "long_name": "Loss of Lock Indicator",
        "coverage_content_type": "qualityInformation",
        "units": "1",
        "valid_range": [-1, 7],
        "description": (
            "Loss of lock indicator of the signal's carrier phase, a bit field "
            "per RINEX 3.04 Table A3: bit 0 = lost lock, cycle slip possible; "
            "bit 1 = half-cycle ambiguity/slip possible; bit 2 = Galileo "
            "BOC-tracking of an MBOC-modulated signal. 0 = OK or not known, "
            "-1 = no indicator recorded. Table A3 defines no further bits, so "
            "7 is the largest defined value."
        ),
        "_FillValue": -1,
    },
    "SSI": {
        "long_name": "Signal Strength Indicator",
        "coverage_content_type": "qualityInformation",
        "units": "1",
        "valid_range": [-1, 9],
        "description": (
            "Signal strength indicator per RINEX 3.04 Table A3, projected "
            "into 1-9: 1 = minimum possible signal strength, 5 = average/good "
            "S/N ratio, 9 = maximum possible signal strength. 0 = not known, "
            "-1 = no indicator recorded."
        ),
        "_FillValue": -1,
    },
}

# -------------------
# SNR vs C/N0 metadata
# -------------------
CN0_METADATA: Final[dict[str, Any]] = {
    "long_name": "Carrier-to-Noise Density Ratio (C/N0)",
    "coverage_content_type": "physicalMeasurement",
    "units": "dB-Hz",
    "valid_min": 0.0,
    "description": (
        "Carrier-to-noise density ratio (C/N0): carrier power relative to the "
        "noise power density (per 1 Hz). RINEX 3.04 observation type S "
        "with the header record SIGNAL STRENGTH UNIT DBHZ (sect. 5.7)."
    ),
    "_FillValue": np.nan,
}

SNR_METADATA: Final[dict[str, Any]] = {
    "long_name": "Signal-to-Noise Ratio (SNR)",
    "coverage_content_type": "physicalMeasurement",
    "units": "dB",
    "valid_min": 0.0,
    "description": (
        "Raw signal strength as given by the receiver (RINEX 3.04 "
        "observation type S). RINEX 3.04 sect. 5.7 defines only the unit "
        "DBHZ; without a SIGNAL STRENGTH UNIT DBHZ header record the unit "
        "is not declared and dB is assumed."
    ),
    "_FillValue": np.nan,
}

# -------------------
# Coordinate metadata
# -------------------
COORDS_METADATA: Final[dict[str, dict[str, str]]] = {
    "epoch": {
        "standard_name": "time",
        "long_name": "GNSS Observation epoch",
        "short_name": "epoch",
        "description": (
            "The epoch indicates the precise time at which each GNSS "
            "observation was recorded."
        ),
    },
    "sv": {
        "long_name": "GNSS Space Vehicle Identifier",
        "description": (
            "The Space Vehicle (sv) identifier denotes the specific satellite "
            "from which the GNSS observation was received."
        ),
    },
    "sid": {
        "long_name": "Signal ID",
        "description": (
            "Unique signal identifier (sv|band|code). Used to map each "
            "observation unambiguously to its properties."
        ),
    },
    "band": {
        "description": "Signal band (L1, L2, E1, etc.)",
        "long_name": "Signal band",
    },
    "system": {
        "description": "GNSS system (G=GPS, E=Galileo, R=GLONASS, C=BeiDou)",
        "long_name": "GNSS System",
    },
    "code": {
        "description": "Observation code (C, P, Y, etc.)",
        "long_name": "Observation code",
    },
    "freq_center": {
        "description": "Center frequency of the signal band",
        "long_name": "Center Frequency",
        "units": f"{FREQ_UNIT:~}",
    },
    "freq_min": {
        "description": "Minimum frequency of the signal band",
        "long_name": "Minimum Frequency",
        "units": f"{FREQ_UNIT:~}",
    },
    "freq_max": {
        "description": "Maximum frequency of the signal band",
        "long_name": "Maximum Frequency",
        "units": f"{FREQ_UNIT:~}",
    },
}

# Time scale of the epoch coordinate, recorded in its "time_system"
# attribute. Every stored epoch is GPS time, so that all receivers and the
# orbits and clocks (SP3, CLK) share one time scale. RINEX and SBF are
# written in GPS time; the NMEA reader converts its UTC times to GPS time.
# Identifiers follow RINEX 3.04 Table A2 (TIME OF FIRST OBS).
EPOCH_TIME_SYSTEM: Final = "GPS"
EPOCH_TIME_SYSTEM_NAME: Final = "GPS time"


def require_gps_time(time_system: str, source: str | None = None) -> None:
    """Refuse epochs that are not in GPS time.

    Parameters
    ----------
    time_system : str
        Time scale of the epochs (RINEX 3.04 Table A2 identifier).
    source : str, optional
        The file the epochs come from, named in the error.

    Raises
    ------
    ValueError
        If ``time_system`` is not ``"GPS"``.

    """
    if time_system != EPOCH_TIME_SYSTEM:
        where = f"{source}: " if source else ""
        msg = (
            f"{where}epochs are in time system {time_system!r}, but canVODpy "
            "stores every epoch in GPS time ('GPS'), the time scale of the "
            "orbits and clocks, and does not convert from "
            f"{time_system!r}. Convert the epochs to GPS time first."
        )
        raise ValueError(msg)


def epoch_coord_attrs(time_system: str, source: str | None = None) -> dict[str, str]:
    """Return the epoch coordinate attributes, including its time scale.

    Parameters
    ----------
    time_system : str
        Time scale of the epochs: must be ``"GPS"``. Readers state it, so
        that epochs in another scale are refused instead of stored.
    source : str, optional
        The file the epochs come from, named in the error.

    Raises
    ------
    ValueError
        If ``time_system`` is not GPS time (:func:`require_gps_time`).

    """
    require_gps_time(time_system, source)
    return {
        **COORDS_METADATA["epoch"],
        "time_system": EPOCH_TIME_SYSTEM,
        "time_system_name": EPOCH_TIME_SYSTEM_NAME,
    }


# -------------------
# Encoding definitions
# -------------------
DTYPES: Final[dict[str, np.dtype]] = {
    "SNR": np.dtype("float32"),
    "Pseudorange": np.dtype("float64"),
    "Phase": np.dtype("float64"),
    "Doppler": np.dtype("float32"),
    "LLI": np.dtype("int8"),
    "SSI": np.dtype("int8"),
    "freq_center": np.dtype("float32"),
    "freq_min": np.dtype("float32"),
    "freq_max": np.dtype("float32"),
}

# -------------------
# Global attributes
# -------------------


def get_global_attrs() -> dict[str, str]:
    """Build global attributes from the active configuration.

    Returns
    -------
    dict[str, str]
        Global attributes dict suitable for xarray Dataset attrs.
        Falls back to ``{"Software": "canVODpy", "Institution": "Unknown"}``
        when no config is available (e.g. standalone ``canvod-readers``
        install without a ``canvod-settings.yaml``) — "Unknown" satisfies
        ``REQUIRED_ATTRS`` (``base.py``) while remaining a recognizable
        placeholder rather than a real institution name, so it can't be
        mistaken for genuine FAIR/DataCite metadata downstream.
    """
    from canvod.config import load_config

    try:
        cfg = load_config()
        meta = cfg.processing.metadata
    except Exception:
        return {"Software": "canVODpy", "Institution": "Unknown"}

    attrs: dict[str, str] = {
        "Author": meta.author,
        "Email": meta.email,
        "Institution": meta.institution,
    }
    if meta.department:
        attrs["Department"] = meta.department
    rg_parts = [p for p in [meta.research_group, meta.website] if p]
    if rg_parts:
        attrs["Research Group"] = ", ".join(rg_parts)
    attrs["Software"] = "canVODpy"
    return attrs


# -------------------
# Additional data variables
# -------------------
DATAVARS_TO_BE_FILLED: Final[dict[str, dict[str, Any]]] = {
    "r": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "radial distance",
            "units": "meters",
            "description": "Slant distance from receiver to satellite in ECEF spherical coordinates",
        },
    },
    "theta": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "polar angle",
            "units": "degrees",
            "description": "Angle from positive Z-axis (zenith)",
        },
    },
    "phi": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "azimuthal angle",
            "units": "degrees",
            "description": "Rotation angle from reference meridian in XY-plane",
        },
    },
    "v": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "satellite velocity",
            "units": "meters per second",
            "description": "Instantaneous satellite velocity relative to receiver",
        },
    },
    "a": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "satellite acceleration",
            "units": "meters per second squared",
            "description": "Instantaneous satellite acceleration relative to receiver",
        },
    },
}
