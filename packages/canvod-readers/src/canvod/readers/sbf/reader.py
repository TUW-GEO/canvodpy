"""SBF file reader.

Wraps the ``sbf-parser`` library and decodes Septentrio Binary Format files
following the AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide
(RefGuide-4.14.0). One decoder serves every output of :class:`SbfReader`:

- Blocks are grouped by their receiver time stamp (TOW, WNc): all blocks of
  a group hold data of the same epoch (RefGuide-4.14.0, Section 4.1.3,
  p.253), whatever their order in the file. The receiver writes the
  MeasExtra, SatVisibility, PVT, DOP and status blocks of an epoch after its
  MeasEpoch block.
- GLONASS FDMA carrier frequencies come from the frequency number in the
  ObsInfo field of the MeasEpoch Type1 sub-block (p.262).
- Observations of SVID 62, a GLONASS satellite whose slot number is not
  known (p.255), are dropped: they have no RINEX satellite code, and several
  such satellites would share one identifier.
- The raw fields of all observations are scaled at once with the functions
  in :mod:`canvod.readers.sbf._scaling`.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, cast

import numpy as np
import structlog
import xarray as xr
from numpy.typing import NDArray
from pydantic import ConfigDict

from canvod.readers.base import (
    GNSSDataReader,
    validate_dataset,
)
from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
    epoch_coord_attrs,
)
from canvod.readers.sbf._registry import FDMA_SIGNAL_NUMS, SIGNAL_TABLE, decode_svid
from canvod.readers.sbf._scaling import (
    cn0_dbhz,
    decode_offsets_msb,
    decode_signal_num,
    doppler2_hz,
    doppler_hz,
    glonass_freq_hz,
    glonass_freq_nr,
    phase_cycles,
    pr2_m,
    pseudorange_m,
)
from canvod.readers.sbf.models import SbfEpoch, SbfHeader, SbfSignalObs
from canvod.utils.tools import hashing

try:
    import sbf_parser
except ImportError as _err:
    raise ImportError(
        "sbf-parser is required for SbfReader. Install it with: uv add sbf-parser"
    ) from _err

log = structlog.get_logger(__name__)

# C/N0 as decoded from SBF (Septentrio), on top of the generic C/N0 entry.
_SBF_CN0_METADATA: dict[str, Any] = {
    **CN0_METADATA,
    "description": (
        "Carrier-to-noise density ratio (C/N0): carrier power relative to the "
        "noise power density (per 1 Hz), as reported in SBF MeasEpoch."
    ),
    "resolution": "0.25 dB-Hz (MeasEpoch); 0.03125 dB-Hz with MeasExtra CN0HighRes",
    "comment": (
        "Sourced from MeasEpoch.MeasEpochChannelType1.CN0 (u1, scale 0.25 dB-Hz/LSB, "
        "Do-Not-Use 255). "
        "GPS L1P (sig 1, RINEX 1W) and GPS L2P (sig 2, RINEX 2W): "
        "C/N0 = raw * 0.25. All other signals: C/N0 = raw * 0.25 + 10. "
        "Where the MeasExtra block of the same epoch is logged, its CN0HighRes "
        "value (MeasExtraChannelSub.Misc bits 0-2, 0.03125 dB-Hz/LSB) is added, "
        "which extends the resolution to 0.03125 dB-Hz."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), MeasEpochChannelType1 sub-block, "
        "field CN0, p.261; signal type table Section 4.1.10, p.256; "
        "MeasExtra block (Block 4000), MeasExtraChannelSub, field Misc, p.265."
    ),
}

# ---------------------------------------------------------------------------
# Receiver time stamp
# TOW and WNc follow the GPS convention: weeks since 1980-01-06, no leap
# seconds (RefGuide-4.14.0, Section 2.3, p.53). Epochs are stored in GPS
# time, the time scale of RINEX files and of the orbit and clock products.
# ---------------------------------------------------------------------------

_GPS_EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
_SECONDS_PER_GPS_WEEK: int = 604_800

# ---------------------------------------------------------------------------
# Block grouping and identifiers
# ---------------------------------------------------------------------------

#: Blocks decoded per epoch. All carry a receiver time stamp
#: (RefGuide-4.14.0, Section 4.1.3, p.253).
_EPOCH_BLOCKS: frozenset[str] = frozenset(
    {
        "ReceiverTime",
        "MeasEpoch",
        "MeasExtra",
        "PVTGeodetic",
        "DOP",
        "ReceiverStatus",
        "SatVisibility",
        "QualityInd",
        "RFStatus",
        "ChannelStatus",
    }
)

_TOW_DNU: int = 4_294_967_295  # Section 4.1.3, p.253
_WNC_DNU: int = 65_535
_SVID_DNU: int = 0  # Section 4.1.9, p.255
_SVID_GLONASS_UNKNOWN_SLOT: int = 62  # Section 4.1.9, p.255: RINEX code NA

#: Carrier frequency in Hz of every signal with a fixed frequency
#: (all except GLONASS FDMA and L-Band MSS), from the signal table.
_FIXED_FREQ_HZ: dict[int, float] = {
    num: float(sig.freq.to(UREG.Hz).magnitude)
    for num, sig in SIGNAL_TABLE.items()
    if sig.freq is not None
}


def _iter_epoch_groups(fpath: Path) -> Iterator[dict[str, dict[str, Any]]]:
    """Yield the blocks of each epoch that has a MeasEpoch block.

    Blocks are grouped by their receiver time stamp (WNc, TOW), which never
    decreases once the receiver time is aligned with GNSS time
    (RefGuide-4.14.0, Section 4.1.3, p.253). Blocks without a valid time
    stamp, and epochs without a MeasEpoch block (e.g. a PVT block at a
    higher rate than the measurements), are skipped.

    Parameters
    ----------
    fpath : Path
        SBF file.

    Yields
    ------
    dict of {str: dict}
        Block name → raw block dict from ``sbf_parser``.
    """
    group: dict[str, dict[str, Any]] = {}
    key: tuple[int, int] | None = None
    for name, data in sbf_parser.SbfParser().read(str(fpath)):
        if name not in _EPOCH_BLOCKS:
            continue
        tow = int(data["TOW"])
        wn = int(data["WNc"])
        if tow == _TOW_DNU or wn == _WNC_DNU:
            continue
        if (wn, tow) != key:
            if "MeasEpoch" in group:
                yield group
            group = {}
            key = (wn, tow)
        group[name] = data
    if "MeasEpoch" in group:
        yield group


def _tow_wn_to_gps(tow_ms: int, wn: int) -> datetime:
    """Convert the receiver time stamp (TOW + WNc) to a GPS time datetime.

    Parameters
    ----------
    tow_ms : int
        GPS Time of Week in milliseconds.
    wn : int
        GPS Week Number (continuous, post-rollover correction applied by
        the receiver).

    Returns
    -------
    datetime
        GPS time. It carries ``tzinfo=UTC`` only to be timezone-aware, as
        the RINEX readers' times do; no leap seconds are subtracted.

    Notes
    -----
    Source: RefGuide-4.14.0, Section 2.3, p.53.
    """
    gps_seconds = wn * _SECONDS_PER_GPS_WEEK + tow_ms / 1000.0
    return _GPS_EPOCH + timedelta(seconds=gps_seconds)


# ---------------------------------------------------------------------------
# String helpers for ReceiverSetup binary character arrays
# ---------------------------------------------------------------------------


def _decode_bytes(raw: bytes) -> str:
    """Decode a NUL-padded SBF character array to a clean Python string."""
    return raw.decode("ascii", errors="replace").rstrip("\x00").strip()


def _snr_dbhz_to_ssi(snr_dbhz: np.ndarray) -> np.ndarray:
    """Derive RINEX-convention SSI (1-9) from continuous CN0 (dB-Hz).

    SBF's raw MeasEpoch blocks carry only continuous CN0, not RINEX's
    single-digit Signal Strength Indicator -- this is the standard
    RINEX-writing-receiver conversion for CN0 given in dB-Hz (RINEX 3.04
    §5.7): ``sn_rnx = MIN(MAX(INT(sn_raw/6), 1), 9)``. NaN (no
    observation) stays at the -1 "no data" sentinel.
    """
    ssi = np.full(snr_dbhz.shape, -1, dtype=np.int8)
    valid = np.isfinite(snr_dbhz)
    ssi[valid] = np.clip(np.floor(snr_dbhz[valid] / 6.0), 1, 9).astype(np.int8)
    return ssi


# ---------------------------------------------------------------------------
# Bandwidth helper for the sid frequency bounds
# ---------------------------------------------------------------------------

_CONSTELLATION_MAP: dict[str, Any] = {
    "G": GPS,
    "R": GLONASS,
    "E": GALILEO,
    "C": BEIDOU,
    "J": QZSS,
    "I": IRNSS,
    "S": SBAS,
}


def _get_bandwidth_mhz(system: str, band: str) -> float:
    """Return signal bandwidth in MHz, or NaN if unknown.

    Parameters
    ----------
    system : str
        RINEX single-letter system code.
    band : str
        Band label (e.g. "L1", "G1", "E5a").

    Returns
    -------
    float
        Bandwidth in MHz, or NaN if the band is not found.
    """
    if system == "R" and band in ("G1", "G2"):
        # FDMA G1/G2: use aggregated bandwidth table (ClassVar on GLONASS)
        bw = GLONASS.AGGR_G1_G2_BAND_PROPERTIES[band]["bandwidth"]
        return float(bw.to(UREG.MHz).magnitude)
    const = _CONSTELLATION_MAP.get(system)
    if const is None:
        return float("nan")
    try:
        bw = const.BAND_PROPERTIES[band]["bandwidth"]
        return float(bw.to(UREG.MHz).magnitude)
    except KeyError, AttributeError:
        return float("nan")


# ---------------------------------------------------------------------------
# Metadata dataset variable / coordinate attributes
# (CF-convention style: long_name, units, source, comment, references)
# ---------------------------------------------------------------------------

_BROADCAST_THETA_ATTRS: dict[str, str] = {
    "long_name": "Satellite polar angle reported by the receiver",
    "coverage_content_type": "auxiliaryInformation",
    "short_name": "θ_B",
    "units": "rad",
    "source": "SBF SatVisibility block (Block 4012), reported by receiver firmware",
    "comment": (
        "Polar angle from vertical: 0 = overhead, π/2 = horizon. "
        "Derived from SatVisibility.SatInfo.Elevation (i2, scale 0.01 deg/LSB, "
        "Do-Not-Use -32768), converted to radians via theta = (90 - elevation_deg) * π/180. "
        "Computed by the receiver firmware from the satellite's broadcast "
        "ephemeris or almanac, as given per value by broadcast_angle_source; "
        "NOT independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Elevation, p.400."
    ),
}
_BROADCAST_PHI_ATTRS: dict[str, str] = {
    "long_name": "Satellite azimuth reported by the receiver (geographic convention)",
    "coverage_content_type": "auxiliaryInformation",
    "short_name": "φ_B",
    "units": "rad",
    "source": "SBF SatVisibility block (Block 4012), reported by receiver firmware",
    "comment": (
        "Geographic azimuth: 0 = North, π/2 = East (clockwise). "
        "Derived from SatVisibility.SatInfo.Azimuth (u2, scale 0.01 deg/LSB, "
        "Do-Not-Use 65535), converted to radians via phi = azimuth_deg * π/180. "
        "Computed by the receiver firmware from the satellite's broadcast "
        "ephemeris or almanac, as given per value by broadcast_angle_source; "
        "NOT independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Azimuth, p.400."
    ),
}

_RISE_SET_ATTRS: dict[str, object] = {
    "long_name": "Satellite rise/set indicator",
    "coverage_content_type": "auxiliaryInformation",
    "flag_values": [0, 1],
    "flag_meanings": "setting rising",
    "source": "SBF SatVisibility block, reported by receiver firmware",
    "comment": (
        "Rise/set indicator from the SBF SatVisibility block: "
        "0 = satellite is setting (elevation decreasing), "
        "1 = satellite is rising (elevation increasing), "
        "255 (raw) indicates unknown elevation rate. "
        "Fill value -1 (int8) used for missing observations."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field RiseSet, p.400. "
        "Raw field: u1, scale 1; 0=setting, 1=rising, 255=unknown (→ stored as -1)."
    ),
}

_BROADCAST_ANGLE_SOURCE_ATTRS: dict[str, object] = {
    "long_name": "Orbit data behind broadcast_theta and broadcast_phi",
    "coverage_content_type": "auxiliaryInformation",
    "flag_values": [1, 2],
    "flag_meanings": "almanac ephemeris",
    "source": "SBF SatVisibility block, reported by receiver firmware",
    "comment": (
        "Whether the receiver computed the azimuth/elevation of this "
        "satellite from its almanac (1) or its broadcast ephemeris (2). "
        "255 (raw) indicates unknown. Fill value -1 (int8) used for unknown "
        "and missing values. Broadcast-mode geometry uses only values "
        "computed from the ephemeris (2)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field "
        "SatelliteInfo, p.400. Raw field: u1; 1=almanac, 2=ephemeris, "
        "255=unknown (→ stored as -1)."
    ),
}

_MP_CORRECTION_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange multipath correction",
    "coverage_content_type": "auxiliaryInformation",
    "units": "m",
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Multipath mitigation correction applied to the pseudorange by the receiver. "
        "Add this value to the pseudorange to recover the raw unmitigated pseudorange. "
        "Raw field: i2, scale 0.001 m/LSB (resolution 1 mm). No Do-Not-Use value."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field MPCorrection, p.265."
    ),
}

_CODE_VAR_ATTRS: dict[str, object] = {
    "long_name": "Code tracking noise variance",
    "coverage_content_type": "qualityInformation",
    "units": "m^2",
    "valid_max": 65534e-4,
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Estimated code tracking noise variance. "
        "Raw field: u2, scale 0.0001 m²/LSB (stored here after applying scale). "
        "Values saturate at 65534 counts (= 6.5534 m²); raw Do-Not-Use 65535 → NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CodeVar, p.265."
    ),
}

_CARRIER_VAR_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase tracking noise variance",
    "coverage_content_type": "qualityInformation",
    "units": "mcycles^2",
    "valid_max": 65534.0,
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Estimated carrier phase tracking noise variance. "
        "Raw field: u2, scale 1 mcycle²/LSB. "
        "Values saturate at 65534 mcycles²; raw Do-Not-Use 65535 → NaN. "
        "Multiply by the MeasExtra.DopplerVarFactor to obtain the Doppler "
        "measurement variance."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarrierVar, p.265."
    ),
}

_CN0_HIGHRES_CORRECTION_ATTRS: dict[str, object] = {
    "long_name": "C/N0 high-resolution correction from MeasExtra",
    "coverage_content_type": "auxiliaryInformation",
    "units": "dB-Hz",
    "valid_min": 0.0,
    "valid_max": 7 * 0.03125,  # CN0HighRes max value 7 → 0.21875 dB-Hz
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "High-resolution C/N0 extension from MeasExtra.MeasExtraChannelSub.Misc "
        "bits 0-2 (CN0HighRes, u3, range 0-7). "
        "Add to the SNR variable (from MeasEpoch, 0.25 dB-Hz resolution) to obtain "
        "C/N0 at 0.03125 dB-Hz (1/32 dB-Hz) resolution: "
        "  C/N0_highres = SNR + cn0_highres_correction. "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field Misc bits 0-2 (CN0HighRes), p.265."
    ),
}

_SMOOTHING_CORR_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange Hatch-filter smoothing correction",
    "coverage_content_type": "auxiliaryInformation",
    "units": "m",
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Smoothing correction applied to the pseudorange by the Hatch filter. "
        "Add to the stored pseudorange to recover the raw unsmoothed measurement. "
        "Raw field: i2, scale 0.001 m/LSB. "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field SmoothingCorr, p.265."
    ),
}

_LOCK_TIME_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase lock time",
    "coverage_content_type": "qualityInformation",
    "units": "s",
    "valid_min": 0.0,
    "valid_max": 65534.0,
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Duration of continuous carrier phase tracking for this signal. "
        "Reset to 0 on reacquisition or cycle slip. "
        "Raw field: u2, scale 1 s/LSB, clipped to 65534 s; Do-Not-Use 65535 → NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field LockTime, p.265."
    ),
}

_CUM_LOSS_CONT_ATTRS: dict[str, object] = {
    "long_name": "Cumulative loss-of-continuity counter",
    "coverage_content_type": "qualityInformation",
    "units": "1",
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Modulo-256 counter that increments each time continuous carrier phase "
        "tracking is interrupted (cycle slip or reacquisition after loss of lock). "
        "A change between consecutive epochs indicates a cycle slip. "
        "Raw field: u1, no Do-Not-Use value."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CumLossCont, p.265."
    ),
}

_CAR_MP_CORR_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase multipath correction",
    "coverage_content_type": "auxiliaryInformation",
    "units": "cycles",
    "source": "SBF MeasExtra block (Block 4000), reported by receiver firmware",
    "comment": (
        "Multipath correction for the carrier phase measurement. "
        "Add to the stored carrier phase to recover the raw unmitigated phase. "
        "Raw field: i1, scale 1/512 cycles/LSB (1.953125 mcycles/LSB). "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarMPCorr, p.265."
    ),
}

_SNR_RAW_ATTRS: dict[str, object] = {
    "long_name": "C/N0 before CN0HighRes correction (0.25 dB-Hz resolution)",
    "coverage_content_type": "physicalMeasurement",
    "units": "dB-Hz",
    "valid_min": 0.0,
    "source": "SBF MeasEpoch block (Block 4027), before CN0HighRes correction",
    "comment": (
        "Carrier-to-noise density at the native MeasEpoch resolution of 0.25 dB-Hz, "
        "before the high-resolution extension from MeasExtra is applied. "
        "SNR is the corrected version (0.03125 dB-Hz when MeasExtra is available). "
        "NaN where no observation was present."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), MeasEpochChannelType1 sub-block, "
        "field CN0, p.261."
    ),
}

_PSEUDORANGE_UNSMOOTHED_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange before Hatch-filter carrier smoothing",
    "coverage_content_type": "physicalMeasurement",
    "units": "m",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Pseudorange with the Hatch-filter smoothing correction removed: "
        "PR_unsmoothed = Pseudorange + smoothing_corr_m. "
        "Exposes the raw code measurement before the firmware's carrier-smoothing "
        "filter is applied. NaN where MeasExtra was not logged or no measurement "
        "available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field SmoothingCorr, p.265."
    ),
}

_PSEUDORANGE_RAW_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange before Hatch-filter smoothing and multipath mitigation",
    "coverage_content_type": "physicalMeasurement",
    "units": "m",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Pseudorange with both firmware corrections removed: "
        "PR_raw = Pseudorange + smoothing_corr_m + mp_correction_m. "
        "Exposes the code measurement before any firmware post-processing. "
        "NaN where MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "fields SmoothingCorr and MPCorrection, p.265."
    ),
}

_PHASE_RAW_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase before carrier multipath correction",
    "coverage_content_type": "physicalMeasurement",
    "units": "cycles",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Carrier phase with the firmware multipath correction removed: "
        "Phase_raw = Phase + car_mp_corr_cycles. "
        "NaN where MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarMPCorr, p.265."
    ),
}

_PDOP_ATTRS: dict[str, object] = {
    "long_name": "Position Dilution of Precision",
    "coverage_content_type": "qualityInformation",
    "units": "1",
    "source": "SBF DOP block (Block 4001), reported by receiver firmware",
    "comment": (
        "PDOP = √(Qxx + Qyy + Qzz), where Q is the position covariance matrix "
        "in a local Cartesian frame. Smaller values indicate better satellite geometry. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field PDOP, p.348."
    ),
}

_HDOP_ATTRS: dict[str, object] = {
    "long_name": "Horizontal Dilution of Precision",
    "coverage_content_type": "qualityInformation",
    "units": "1",
    "source": "SBF DOP block (Block 4001), reported by receiver firmware",
    "comment": (
        "HDOP = √(Qλλ + Qϕϕ), where Qλλ and Qϕϕ are the longitude and latitude "
        "components of the position covariance matrix. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field HDOP, p.348."
    ),
}

_VDOP_ATTRS: dict[str, object] = {
    "long_name": "Vertical Dilution of Precision",
    "coverage_content_type": "qualityInformation",
    "units": "1",
    "source": "SBF DOP block (Block 4001), reported by receiver firmware",
    "comment": (
        "VDOP = √(Qhh), where Qhh is the height component of the position "
        "covariance matrix. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field VDOP, p.348."
    ),
}

_N_SV_ATTRS: dict[str, object] = {
    "long_name": "Number of satellites used in PVT computation",
    "coverage_content_type": "auxiliaryInformation",
    "units": "1",
    "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    "comment": (
        "Total number of satellites used in the Position-Velocity-Time (PVT) "
        "computation. Raw field: u1, Do-Not-Use 255 (→ stored as -1). "
        "Fill value -1 (int16) indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field NrSV, p.338."
    ),
}

_H_ACCURACY_ATTRS: dict[str, object] = {
    "long_name": "Horizontal position accuracy (2DRMS, 95%)",
    "coverage_content_type": "qualityInformation",
    "units": "m",
    "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    "comment": (
        "Twice the root-mean-square of the horizontal distance error (2DRMS). "
        "The horizontal distance between the true and computed positions is expected "
        "to be below this value with ≥95% probability. "
        "Raw field: u2, scale 0.01 m/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field HAccuracy, p.339."
    ),
}

_V_ACCURACY_ATTRS: dict[str, object] = {
    "long_name": "Vertical position accuracy (2-sigma, 95%)",
    "coverage_content_type": "qualityInformation",
    "units": "m",
    "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    "comment": (
        "Two-sigma vertical accuracy. "
        "The vertical distance between the true and computed positions is expected "
        "to be below this value with ≥95% probability. "
        "Raw field: u2, scale 0.01 m/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field VAccuracy, p.339."
    ),
}

_PVT_MODE_ATTRS: dict[str, object] = {
    "long_name": "PVT solution mode",
    "coverage_content_type": "auxiliaryInformation",
    "units": "1",
    "flag_values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 10],
    "flag_meanings": (
        "no_pvt stand_alone differential fixed_location "
        "rtk_fixed_ambiguities rtk_float_ambiguities sbas_aided "
        "moving_base_rtk_fixed_ambiguities moving_base_rtk_float_ambiguities ppp"
    ),
    "source": "SBF PVTGeodetic block (Block 4007), reported by receiver firmware",
    "comment": (
        "Bits 0-3 of PVTGeodetic.Mode (u1). "
        "0 = No PVT; 1 = Stand-Alone; 2 = Differential (DGNSS); "
        "3 = Fixed location; 4 = RTK fixed ambiguities; "
        "5 = RTK float ambiguities; 6 = SBAS-aided; "
        "7 = moving-base RTK fixed ambiguities; "
        "8 = moving-base RTK float ambiguities; 10 = PPP. "
        "Fill value -1 (int8) indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field Mode, p.337."
    ),
}

_MEAN_CORR_AGE_ATTRS: dict[str, object] = {
    "long_name": "Mean age of differential corrections",
    "coverage_content_type": "auxiliaryInformation",
    "units": "s",
    "source": "SBF PVTGeodetic block, reported by receiver firmware",
    "comment": (
        "Mean age of the differential corrections used in a DGNSS or RTK solution. "
        "Only meaningful when PVT mode is Differential (2), RTK fixed (4), or "
        "RTK float (5). NaN indicates not available (raw DoNotUse value 65535)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field MeanCorrAge, p.338. "
        "Raw field: u2, scale 0.01 s/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
}

_CPU_LOAD_ATTRS: dict[str, object] = {
    "long_name": "Receiver CPU load",
    "coverage_content_type": "auxiliaryInformation",
    "units": "percent",
    "valid_min": 0,
    "valid_max": 100,
    "source": "SBF ReceiverStatus block, reported by receiver firmware",
    "comment": (
        "Percentage load on the receiver's main processor (0-100%). "
        "Sustained values above 80% risk data loss in the receiver. "
        "Fill value -1 (int8) indicates not available (raw DoNotUse value 255)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field CPULoad, p.396. "
        "Raw field: u1, scale 1 %/LSB, Do-Not-Use 255 (→ stored as -1). "
        "Sustained load > 80% risks data loss."
    ),
}

_TEMPERATURE_ATTRS: dict[str, object] = {
    "long_name": "Receiver internal temperature",
    "coverage_content_type": "auxiliaryInformation",
    "units": "degC",
    "source": "SBF ReceiverStatus block, reported by receiver firmware",
    "comment": (
        "Internal temperature of the receiver. "
        "The raw SBF field (u1) has 1 °C resolution and an offset of 100; "
        "stored value = raw_field − 100 (e.g. raw 120 → 20 °C). "
        "Do-Not-Use value 0 is stored as NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field Temperature, p.398. "
        "Raw field: u1, subtract 100 to obtain °C (e.g. raw 120 = 20°C). "
        "Do-Not-Use 0 (→ NaN)."
    ),
}

_RX_ERROR_ATTRS: dict[str, object] = {
    "long_name": "Receiver error status bit field",
    "coverage_content_type": "qualityInformation",
    "units": "1",
    # CF bitmask convention: test each flag with (value & mask) != 0
    # Bit positions: 3=8, 4=16, 5=32, 6=64, 8=256, 9=512, 10=1024, 11=2048
    "flag_masks": [8, 16, 32, 64, 256, 512, 1024, 2048],
    "flag_meanings": (
        "software watchdog antenna congestion missedevent cpuoverload "
        "invalidconfig outofgeofence"
    ),
    "source": "SBF ReceiverStatus block, reported by receiver firmware",
    "comment": (
        "Bit field indicating whether the receiver previously detected an error. "
        "Non-zero value means at least one error has been detected. "
        "Multiple flags may be set simultaneously; test each with "
        "(rx_error & flag_mask) != 0. "
        "E.g. value 8 = bit 3 = software error; "
        "value 48 = bits 4+5 = watchdog + antenna."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field RxError, p.398."
    ),
}


_SMOOTHING_FLAG_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange smoothing flag",
    "coverage_content_type": "qualityInformation",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "missing not_smoothed smoothed",
    "source": "SBF MeasEpoch block (Block 4027), ObsInfo bit 0",
    "comment": (
        "1 = pseudorange is carrier-smoothed (smoothing filter applied by "
        "the receiver), 0 = not smoothed, -1 = no observation. "
        "Extracted from the ObsInfo byte (bit 0) of each MeasEpoch "
        "Type1/Type2 sub-block."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), field ObsInfo bit 0, pp. 260-263."
    ),
    "_FillValue": -1,
}
_HALF_CYCLE_ATTRS: dict[str, object] = {
    "long_name": "Carrier-phase half-cycle ambiguity flag",
    "coverage_content_type": "qualityInformation",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "missing resolved half_cycle_ambiguous",
    "source": "SBF MeasEpoch block (Block 4027), ObsInfo bit 2",
    "comment": (
        "1 = the carrier phase of this observation may contain an "
        "unresolved 0.5-cycle ambiguity, 0 = ambiguity resolved, "
        "-1 = no observation. Extracted from the ObsInfo byte (bit 2) "
        "of each MeasEpoch Type1/Type2 sub-block."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), field ObsInfo bit 2, pp. 260-263."
    ),
    "_FillValue": -1,
}

# ---------------------------------------------------------------------------
# QualityInd (Block 4082) indicator attributes
# ---------------------------------------------------------------------------

_QUAL_COMMENT_TAIL = (
    "Score on a 0 (poor) to 10 (excellent) scale; -1 = unknown / not "
    "reported (raw value 15 or indicator absent). Decoded from QualityInd "
    "indicator words: bits 0-7 = indicator type, bits 8-11 = value."
)
_QUAL_REFERENCE = (
    "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
    "QualityInd block (Block 4082), field Indicators."
)
_QUAL_OVERALL_ATTRS: dict[str, object] = {
    "long_name": "Overall receiver quality indicator",
    "coverage_content_type": "qualityInformation",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 0",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_GNSS_MAIN_ATTRS: dict[str, object] = {
    "long_name": "GNSS signal quality, main antenna",
    "coverage_content_type": "qualityInformation",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 1",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_RF_MAIN_ATTRS: dict[str, object] = {
    "long_name": "RF power level quality, main antenna",
    "coverage_content_type": "qualityInformation",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 11",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_CPU_ATTRS: dict[str, object] = {
    "long_name": "CPU headroom quality indicator",
    "coverage_content_type": "qualityInformation",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 21",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_SCINT_ATTRS: dict[str, object] = {
    "long_name": "Ionospheric scintillation score",
    "coverage_content_type": "qualityInformation",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 29",
    "comment": (_QUAL_COMMENT_TAIL + " Indicator type 29 requires firmware >= 4.15.1."),
    "references": _QUAL_REFERENCE,
}

# ---------------------------------------------------------------------------
# RFStatus (Block 4092) flag attributes
# ---------------------------------------------------------------------------

_SPOOFING_FLAG_ATTRS: dict[str, object] = {
    "long_name": "GNSS spoofing detection flag",
    "coverage_content_type": "qualityInformation",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "not_available no_spoofing spoofing_detected",
    "source": "SBF RFStatus block (Block 4092), Flags bit 0",
    "comment": (
        "1 = the receiver detected suspected spoofing of GNSS signals at "
        "this epoch, 0 = no spoofing detected, -1 = no RFStatus block "
        "available for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "RFStatus block (Block 4092), field Flags bit 0."
    ),
}
_NMA_FAIL_ATTRS: dict[str, object] = {
    "long_name": "Navigation message authentication failure flag",
    "coverage_content_type": "qualityInformation",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "not_available authentication_ok authentication_failed",
    "source": "SBF RFStatus block (Block 4092), Flags bit 1",
    "comment": (
        "1 = navigation message authentication (e.g. Galileo OSNMA) failed "
        "at this epoch, 0 = no authentication failure, -1 = no RFStatus "
        "block available for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "RFStatus block (Block 4092), field Flags bit 1."
    ),
}

# ---------------------------------------------------------------------------
# ChannelStatus (Block 4013) tracking / PVT status attributes
# ---------------------------------------------------------------------------

_TRACKING_STATUS_RAW_ATTRS: dict[str, object] = {
    "long_name": "Raw per-satellite tracking status bitfield (main antenna)",
    "coverage_content_type": "qualityInformation",
    "source": "SBF ChannelStatus block (Block 4013), ChannelStateInfo.TrackingStatus",
    "comment": (
        "Raw u2 bitfield with 2 bits per signal type: 0 = Idle, 1 = Search, "
        "2 = Sync, 3 = Tracking. Bit positions are constellation-specific "
        "(e.g. GPS: bits 0-1 = L1CA, 2-3 = P1Y, 4-5 = P2Y, 6-7 = L2C, "
        "8-9 = L5, 10-11 = L1C). The same per-satellite value is broadcast "
        "to all SIDs of that satellite; decode the bit pair for the SID's "
        "signal type to obtain per-signal status. Main antenna only. "
        "0 also means no ChannelStatus information for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "ChannelStatus block (Block 4013), ChannelStateInfo sub-block, "
        "field TrackingStatus."
    ),
}
_PVT_STATUS_RAW_ATTRS: dict[str, object] = {
    "long_name": "Raw per-satellite PVT usage status bitfield (main antenna)",
    "coverage_content_type": "qualityInformation",
    "source": "SBF ChannelStatus block (Block 4013), ChannelStateInfo.PVTStatus",
    "comment": (
        "Raw u2 bitfield with 2 bits per signal type: 0 = Not used in PVT, "
        "1 = Waiting for ephemeris, 2 = Used in PVT, 3 = Rejected. Bit "
        "positions are constellation-specific and match TrackingStatus. "
        "The same per-satellite value is broadcast to all SIDs of that "
        "satellite. Main antenna only. "
        "0 also means no ChannelStatus information for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "ChannelStatus block (Block 4013), ChannelStateInfo sub-block, "
        "field PVTStatus."
    ),
}


def _decode_quality_indicators(qualind: dict[str, Any]) -> dict[int, int]:
    """Decode QualityInd (Block 4082) indicator words to ``{type: value}``.

    ``sbf_parser`` returns the ``Indicators`` u2[N] array as raw
    little-endian bytes; decode each 16-bit word as
    bits 0-7 = indicator type, bits 8-11 = value (0-10; 15 = unknown).

    Parameters
    ----------
    qualind : dict
        Raw QualityInd block dict from ``sbf_parser``.

    Returns
    -------
    dict of {int: int}
        Mapping indicator type → value, with 15 (unknown) mapped to -1.
    """
    raw = qualind.get("Indicators", b"")
    if isinstance(raw, (bytes, bytearray)):
        words = [
            int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw) - 1, 2)
        ]
    else:  # already a sequence of ints
        words = [int(w) for w in raw]
    out: dict[int, int] = {}
    for word in words:
        ind_type = word & 0xFF
        value = (word >> 8) & 0x0F
        out[ind_type] = -1 if value == 15 else value
    return out


def _extract_tracking_info(
    chanstatus: dict[str, Any],
) -> list[tuple[str, int, int]]:
    """Extract per-satellite tracking info from a ChannelStatus block.

    Only Main-antenna (Antenna == 0) ChannelStateInfo sub-blocks are
    considered — the primary receiver channel.

    Parameters
    ----------
    chanstatus : dict
        Raw ChannelStatus (Block 4013) dict from ``sbf_parser``.

    Returns
    -------
    list of (sv, tracking_status, pvt_status)
        One entry per satellite with a Main-antenna channel state, where
        ``sv`` is e.g. ``"G01"`` and the two status values are the raw u2
        bitfields (2 bits per signal type).
    """
    out: list[tuple[str, int, int]] = []
    sats = chanstatus.get("SatInfo") or chanstatus.get("ChannelSatInfo") or []
    for sat in sats:
        try:
            svid = int(sat["SVID"])
            if svid == 0:  # Do-Not-Use
                continue
            sys_code, prn = decode_svid(svid)
            sv = f"{sys_code}{prn:02d}"
            for state in sat.get("StateInfo") or []:
                if int(state.get("Antenna", 0)) == 0:  # Main antenna
                    out.append(
                        (
                            sv,
                            int(state["TrackingStatus"]),
                            int(state["PVTStatus"]),
                        )
                    )
                    break
        except KeyError, TypeError, ValueError:
            continue
    return out


def _sid_props(svid: int, sig_num: int, freq_nr: int) -> dict[str, Any] | None:
    """Compute the sid string and its properties for one signal of a satellite.

    Parameters
    ----------
    svid : int
        Septentrio SVID.
    sig_num : int
        SBF signal number.
    freq_nr : int
        GLONASS frequency number with offset 8, or -1 if unknown.

    Returns
    -------
    dict or None
        sid, sv, system, band, code and frequency bounds in MHz, or ``None``
        if the signal is not in the signal table.
    """
    sig_def = SIGNAL_TABLE.get(sig_num)
    if sig_def is None:
        return None
    system, prn = decode_svid(svid)
    sv = f"{system}{prn:02d}"
    band = sig_def.band

    if sig_num in FDMA_SIGNAL_NUMS:
        if freq_nr > 0:
            freq_center_mhz = float(glonass_freq_hz(sig_num, freq_nr)) / 1e6
        else:
            freq_qty = GLONASS.AGGR_G1_G2_BAND_PROPERTIES[band]["freq"]
            freq_center_mhz = float(freq_qty.to(UREG.MHz).magnitude)
    elif sig_def.freq is not None:
        freq_center_mhz = float(sig_def.freq.to(UREG.MHz).magnitude)
    else:
        freq_center_mhz = float("nan")

    bw_mhz = _get_bandwidth_mhz(system, band)
    if np.isnan(freq_center_mhz) or np.isnan(bw_mhz):
        freq_min_mhz = freq_max_mhz = float("nan")
    else:
        freq_min_mhz = freq_center_mhz - bw_mhz / 2.0
        freq_max_mhz = freq_center_mhz + bw_mhz / 2.0

    return {
        "sid": f"{sv}|{band}|{sig_def.code}",
        "sv": sv,
        "system": system,
        "band": band,
        "code": sig_def.code,
        "freq_center": freq_center_mhz,
        "freq_min": freq_min_mhz,
        "freq_max": freq_max_mhz,
    }


# ---------------------------------------------------------------------------
# The decoder: every signal observation of a sequence of epochs, one row each
# ---------------------------------------------------------------------------

# Raw integer fields collected per observation. Type1 sub-blocks fill the
# code/Doppler fields, Type2 sub-blocks the offset fields; the other set
# stays 0 and is never used for that row.
_RAW_FIELDS: tuple[str, ...] = (
    "epoch",
    "parent",
    "is_type2",
    "svid",
    "rx_channel",
    "type",
    "obs_info",
    "cn0",
    "lock_time",
    "misc",
    "code_lsb",
    "doppler",
    "offsets_msb",
    "code_offset_lsb",
    "doppler_offset_lsb",
    "carrier_msb",
    "carrier_lsb",
)

# MeasExtraChannelSub fields (RefGuide-4.14.0, MeasExtra, pp.264-265).
# sbf_parser names the multipath correction field "MPCorrection " (trailing
# space).
_EXTRA_FIELDS: tuple[str, ...] = (
    "epoch",
    "rx_channel",
    "type",
    "misc",
    "mp_correction",
    "smoothing_corr",
    "code_var",
    "carrier_var",
    "lock_time",
    "cum_loss_cont",
    "car_mp_corr",
)


@dataclass(frozen=True)
class _Observations:
    """Decoded signal observations, one row per signal and epoch.

    All arrays have one entry per row. Physical values are plain floats in
    the unit named by the field; NaN where Do-Not-Use or not available.
    MeasExtra values are NaN where the epoch has no MeasExtra entry for the
    signal.
    """

    epoch: NDArray[np.int64]
    svid: NDArray[np.int64]
    sig_num: NDArray[np.int64]
    freq_nr: NDArray[np.int64]
    rx_channel: NDArray[np.int64]
    is_type2: NDArray[np.bool_]
    obs_info: NDArray[np.int64]
    lock_time_s: NDArray[np.int64]
    cn0_dbhz: NDArray[np.float64]
    pseudorange_m: NDArray[np.float64]
    doppler_hz: NDArray[np.float64]
    phase_cycles: NDArray[np.float64]
    # MeasExtra (RefGuide-4.14.0, pp.264-265)
    cn0_highres_dbhz: NDArray[np.float64]
    mp_correction_m: NDArray[np.float64]
    smoothing_corr_m: NDArray[np.float64]
    code_var_m2: NDArray[np.float64]
    carrier_var_mcycle2: NDArray[np.float64]
    extra_lock_time_s: NDArray[np.float64]
    cum_loss_cont: NDArray[np.float64]
    car_mp_corr_cycles: NDArray[np.float64]

    @property
    def snr_dbhz(self) -> NDArray[np.float64]:
        """C/N0 with the MeasExtra CN0HighRes value added where logged."""
        return np.where(
            np.isnan(self.cn0_highres_dbhz),
            self.cn0_dbhz,
            self.cn0_dbhz + self.cn0_highres_dbhz,
        )


def _decode_observations(groups: list[dict[str, dict[str, Any]]]) -> _Observations:
    """Decode the MeasEpoch and MeasExtra blocks of a sequence of epochs.

    Parameters
    ----------
    groups : list of dict
        Epoch groups from :func:`_iter_epoch_groups`; the row field
        ``epoch`` is the index into this list.

    Returns
    -------
    _Observations
        One row per Type1 and Type2 sub-block, except SVID Do-Not-Use and
        SVID 62 (unknown GLONASS slot).

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpoch (Block 4027) pp.259-263, MeasExtra
    (Block 4000) pp.264-265. Type2 sub-blocks belong to the satellite of
    their Type1 sub-block and carry no receiver channel or GLONASS frequency
    number; they take both from it.
    """
    raw: dict[str, list[int]] = {k: [] for k in _RAW_FIELDS}
    extra: dict[str, list[float]] = {k: [] for k in _EXTRA_FIELDS}

    for e, group in enumerate(groups):
        for t1 in group["MeasEpoch"].get("Type_1", []):
            svid = int(t1["SVID"])
            if svid in (_SVID_DNU, _SVID_GLONASS_UNKNOWN_SLOT):
                continue
            parent = len(raw["epoch"])
            rx_channel = int(t1["RxChannel"])
            for k, v in (
                ("epoch", e),
                ("parent", parent),
                ("is_type2", 0),
                ("svid", svid),
                ("rx_channel", rx_channel),
                ("type", int(t1["Type"])),
                ("obs_info", int(t1["ObsInfo"])),
                ("cn0", int(t1["CN0"])),
                ("lock_time", int(t1["LockTime"])),
                ("misc", int(t1["Misc"])),
                ("code_lsb", int(t1["CodeLSB"])),
                ("doppler", int(t1["Doppler"])),
                ("offsets_msb", 0),
                ("code_offset_lsb", 0),
                ("doppler_offset_lsb", 0),
                ("carrier_msb", int(t1["CarrierMSB"])),
                ("carrier_lsb", int(t1["CarrierLSB"])),
            ):
                raw[k].append(v)
            for t2 in t1.get("Type_2", []):
                for k, v in (
                    ("epoch", e),
                    ("parent", parent),
                    ("is_type2", 1),
                    ("svid", svid),
                    ("rx_channel", rx_channel),
                    ("type", int(t2["Type"])),
                    ("obs_info", int(t2["ObsInfo"])),
                    ("cn0", int(t2["CN0"])),
                    ("lock_time", int(t2["LockTime"])),
                    ("misc", 0),
                    ("code_lsb", 0),
                    ("doppler", 0),
                    ("offsets_msb", int(t2["OffsetMSB"])),
                    ("code_offset_lsb", int(t2["CodeOffsetLSB"])),
                    ("doppler_offset_lsb", int(t2["DopplerOffsetLSB"])),
                    ("carrier_msb", int(t2["CarrierMSB"])),
                    ("carrier_lsb", int(t2["CarrierLSB"])),
                ):
                    raw[k].append(v)

        for ch in (group.get("MeasExtra") or {}).get("MeasExtraChannel", []):
            for k, v in (
                ("epoch", e),
                ("rx_channel", int(ch["RxChannel"])),
                ("type", int(ch["Type"])),
                ("misc", int(ch["Misc"])),
                ("mp_correction", int(ch["MPCorrection "])),
                ("smoothing_corr", int(ch["SmoothingCorr"])),
                ("code_var", int(ch["CodeVar"])),
                ("carrier_var", int(ch["CarrierVar"])),
                ("lock_time", int(ch["LockTime"])),
                ("cum_loss_cont", int(ch["CumLossCont"])),
                ("car_mp_corr", int(ch["CarMPCorr"])),
            ):
                extra[k].append(v)

    a = {k: np.asarray(v, dtype=np.int64) for k, v in raw.items()}
    n = len(a["epoch"])
    parent = a["parent"]
    is_type2 = a["is_type2"].astype(bool)

    sig_num = decode_signal_num(a["type"], a["obs_info"])
    freq_nr = glonass_freq_nr(a["type"], a["obs_info"])[parent]

    # Carrier frequency per row; FreqNr Do-Not-Use is 0 (p.255).
    freq_hz = np.full(n, np.nan)
    fdma = np.isin(sig_num, list(FDMA_SIGNAL_NUMS)) & (freq_nr > 0)
    if fdma.any():
        freq_hz[fdma] = glonass_freq_hz(sig_num[fdma], freq_nr[fdma])
    for num in np.unique(sig_num[~fdma]):
        if int(num) in _FIXED_FREQ_HZ:
            freq_hz[sig_num == num] = _FIXED_FREQ_HZ[int(num)]

    with np.errstate(invalid="ignore"):
        pr1_m = pseudorange_m(a["misc"], a["code_lsb"])
        d1_hz = doppler_hz(a["doppler"])
        code_offset_msb, doppler_offset_msb = decode_offsets_msb(a["offsets_msb"])
        pr_m = np.where(
            is_type2,
            pr2_m(pr1_m[parent], code_offset_msb, a["code_offset_lsb"]),
            pr1_m,
        )
        d_hz = np.where(
            is_type2,
            doppler2_hz(
                d1_hz[parent],
                doppler_offset_msb,
                a["doppler_offset_lsb"],
                freq_hz,
                freq_hz[parent],
            ),
            d1_hz,
        )
        ph_cycles = phase_cycles(pr_m, a["carrier_msb"], a["carrier_lsb"], freq_hz)
    cn0 = cn0_dbhz(a["cn0"], sig_num)

    # MeasExtra: match each entry to the observation of the same epoch,
    # receiver channel and signal. The extended signal number is in Misc
    # bits 3-7 (p.265).
    x = {k: np.asarray(v, dtype=np.int64) for k, v in extra.items()}
    row_of = {
        key: i
        for i, key in enumerate(
            zip(a["epoch"].tolist(), a["rx_channel"].tolist(), sig_num.tolist())
        )
    }
    x_sig = decode_signal_num(x["type"], x["misc"])
    x_rows = np.asarray(
        [
            row_of.get(key, -1)
            for key in zip(
                x["epoch"].tolist(), x["rx_channel"].tolist(), x_sig.tolist()
            )
        ],
        dtype=np.int64,
    )
    hit = x_rows >= 0
    rows = x_rows[hit]

    def _extra(values: NDArray[Any]) -> NDArray[np.float64]:
        out = np.full(n, np.nan)
        out[rows] = values[hit]
        return out

    code_var = np.where(x["code_var"] == 65535, np.nan, x["code_var"] * 1e-4)
    carrier_var = np.where(x["carrier_var"] == 65535, np.nan, x["carrier_var"] * 1.0)
    lock_time = np.where(x["lock_time"] == 65535, np.nan, x["lock_time"] * 1.0)

    return _Observations(
        epoch=a["epoch"],
        svid=a["svid"],
        sig_num=sig_num,
        freq_nr=freq_nr,
        rx_channel=a["rx_channel"],
        is_type2=is_type2,
        obs_info=a["obs_info"],
        lock_time_s=a["lock_time"],
        cn0_dbhz=cn0,
        pseudorange_m=pr_m,
        doppler_hz=d_hz,
        phase_cycles=ph_cycles,
        cn0_highres_dbhz=_extra((x["misc"] & 0x07) * 0.03125),
        mp_correction_m=_extra(x["mp_correction"] * 1e-3),
        smoothing_corr_m=_extra(x["smoothing_corr"] * 1e-3),
        code_var_m2=_extra(code_var),
        carrier_var_mcycle2=_extra(carrier_var),
        extra_lock_time_s=_extra(lock_time),
        cum_loss_cont=_extra(x["cum_loss_cont"] * 1.0),
        car_mp_corr_cycles=_extra(x["car_mp_corr"] / 512.0),
    )


def _optional(value: float, unit: Any) -> Any:
    """``value`` with ``unit`` attached, or ``None`` if NaN."""
    return None if math.isnan(value) else value * unit


class SbfReader(GNSSDataReader):
    """Read and decode a Septentrio Binary Format (SBF) observation file.

    Parameters
    ----------
    fpath : Path
        Path to the ``*.sbf`` (or ``*.SBF``, or receiver-named) binary file.
    aggregate_glonass_fdma : bool, default True
        Must be ``True``: GLONASS FDMA signals are always given as
        aggregated G1/G2 bands; ``False`` is refused.

    Examples
    --------
    >>> reader = SbfReader(fpath=Path("rref213a00.25_"))
    >>> print(reader.header.rx_version)
    4.14.4
    >>> for epoch in reader.iter_epochs():
    ...     for obs in epoch.observations:
    ...         print(obs.system, obs.prn, obs.cn0)

    Notes
    -----
    - All physical-unit conversions follow RefGuide-4.14.0.
    - :meth:`iter_epochs`, :meth:`to_ds` and :meth:`to_ds_and_auxiliary`
      share one decoder (:func:`_decode_observations`) and give the same
      values.
    - :meth:`iter_epochs` returns :class:`pint.Quantity` objects using the
      shared :data:`~canvod.readers.gnss_specs.constants.UREG`; the datasets
      hold plain floats.
    - The file is scanned once per :meth:`iter_epochs` call; use
      :attr:`num_epochs` for a pre-computed count (scans once on first access).
    - Inherits ``fpath``, its validator, and ``arbitrary_types_allowed``
      from :class:`GNSSDataReader`.
    """

    model_config = ConfigDict(extra="ignore")

    file_type: ClassVar[str] = "sbf"

    @property
    def source_format(self) -> str:
        return "sbf"

    # ------------------------------------------------------------------
    # GNSSDataReader abstract property implementations
    # ------------------------------------------------------------------

    @cached_property
    def file_hash(self) -> str:
        """SHA-256 hex digest of the file (first 16 characters).

        Returns
        -------
        str
            16-character hexadecimal prefix of the SHA-256 hash.
        """
        return hashing.file_hash(self.fpath)

    @cached_property
    def start_time(self) -> datetime:
        """Return the timestamp of the first decoded epoch.

        Returns
        -------
        datetime
            First observation epoch, in GPS time.

        Raises
        ------
        LookupError
            If the file contains no decodable epochs.
        """
        for epoch in self.iter_epochs():
            return epoch.timestamp
        raise LookupError(f"No epochs in {self.fpath}")

    @cached_property
    def end_time(self) -> datetime:
        """Return the timestamp of the last decoded epoch.

        Returns
        -------
        datetime
            Last observation epoch, in GPS time.

        Raises
        ------
        LookupError
            If the file contains no decodable epochs.
        """
        last: datetime | None = None
        for epoch in self.iter_epochs():
            last = epoch.timestamp
        if last is None:
            raise LookupError(f"No epochs in {self.fpath}")
        return last

    @cached_property
    def systems(self) -> list[str]:
        """Return sorted list of GNSS system codes present in the file.

        Returns
        -------
        list of str
            Sorted list of RINEX system letters (e.g. ``["E", "G", "R"]``).
        """
        return sorted(
            {obs.system for ep in self.iter_epochs() for obs in ep.observations}
        )

    @cached_property
    def num_satellites(self) -> int:
        """Return the number of unique satellites observed in the file.

        Returns
        -------
        int
            Count of unique ``system + PRN`` pairs across all epochs.
        """
        return len(
            {
                f"{obs.system}{obs.prn:02d}"
                for ep in self.iter_epochs()
                for obs in ep.observations
            }
        )

    @cached_property
    def num_epochs(self) -> int:
        """Count the observation epochs (MeasEpoch blocks) in the file.

        Returns
        -------
        int
            Number of epochs :meth:`iter_epochs` yields.

        Notes
        -----
        Scans the entire file once; result is cached.
        """
        count = sum(1 for _ in _iter_epoch_groups(self.fpath))
        log.debug("sbf_epoch_count", fpath=str(self.fpath), num_epochs=count)
        return count

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    @cached_property
    def header(self) -> SbfHeader:
        """Parse the first ReceiverSetup block in the file.

        Returns
        -------
        SbfHeader
            Receiver metadata.

        Raises
        ------
        LookupError
            If no ReceiverSetup block is found.
        """
        parser = sbf_parser.SbfParser()
        for name, data in parser.read(str(self.fpath)):
            if name == "ReceiverSetup":
                return SbfHeader(
                    marker_name=_decode_bytes(data["MarkerName"]),
                    marker_number=_decode_bytes(data["MarkerNumber"]),
                    observer=_decode_bytes(data["Observer"]),
                    agency=_decode_bytes(data["Agency"]),
                    rx_serial=_decode_bytes(data["RxSerialNumber"]),
                    rx_name=_decode_bytes(data["RxName"]),
                    rx_version=_decode_bytes(data["RxVersion"]),
                    ant_serial=_decode_bytes(data["AntSerialNbr"]),
                    ant_type=_decode_bytes(data["AntType"]),
                    delta_h=float(data["deltaH"]) * UREG.meter,
                    delta_e=float(data["deltaE"]) * UREG.meter,
                    delta_n=float(data["deltaN"]) * UREG.meter,
                    latitude_rad=float(data["Latitude"]),
                    longitude_rad=float(data["Longitude"]),
                    height_m=float(data["Height"]) * UREG.meter,
                    gnss_fw_version=_decode_bytes(data["GNSSFWVersion"]),
                    product_name=_decode_bytes(data["ProductName"]),
                )
        raise LookupError(f"No ReceiverSetup block found in {self.fpath}")

    # ------------------------------------------------------------------
    # Epoch iterator
    # ------------------------------------------------------------------

    def iter_epochs(self) -> Iterator[SbfEpoch]:
        """Iterate over the observation epochs of the file.

        Yields
        ------
        SbfEpoch
            One decoded observation epoch, with its signal observations in
            physical units as :class:`pint.Quantity`.

        Notes
        -----
        - The file is scanned from start to finish on each call.
        - ``cn0`` includes the MeasExtra CN0HighRes value of the same epoch
          where it is logged, as the ``SNR`` variable of :meth:`to_ds`.
        - Signals not in the signal table are skipped.
        """
        for group in _iter_epoch_groups(self.fpath):
            meas = group["MeasEpoch"]
            tow_ms = int(meas["TOW"])
            wn = int(meas["WNc"])
            obs = _decode_observations([group])
            snr = obs.snr_dbhz
            observations: list[SbfSignalObs] = []
            for i in range(len(obs.epoch)):
                sig_num = int(obs.sig_num[i])
                sig_def = SIGNAL_TABLE.get(sig_num)
                if sig_def is None:
                    log.debug(
                        "sbf_unknown_signal", svid=int(obs.svid[i]), sig_num=sig_num
                    )
                    continue
                svid = int(obs.svid[i])
                system, prn = decode_svid(svid)
                observations.append(
                    SbfSignalObs(
                        svid=svid,
                        system=system,
                        prn=prn,
                        signal_num=sig_num,
                        signal_type=sig_def.signal_type,
                        rx_channel=int(obs.rx_channel[i]),
                        lock_time_s=int(obs.lock_time_s[i]),
                        cn0=_optional(float(snr[i]), UREG.dBHz),
                        pseudorange=_optional(float(obs.pseudorange_m[i]), UREG.meter),
                        doppler=_optional(float(obs.doppler_hz[i]), UREG.Hz),
                        phase_cycles=(
                            None
                            if math.isnan(obs.phase_cycles[i])
                            else float(obs.phase_cycles[i])
                        ),
                        obs_info=int(obs.obs_info[i]),
                        is_type2=bool(obs.is_type2[i]),
                    )
                )
            yield SbfEpoch(
                tow_ms=tow_ms,
                wn=wn,
                timestamp=_tow_wn_to_gps(tow_ms, wn),
                common_flags=int(meas["CommonFlags"]),
                cum_clk_jumps=int(meas["CumClkJumps"]),
                observations=tuple(observations),
            )

    # ------------------------------------------------------------------
    # Datasets
    # ------------------------------------------------------------------

    def to_ds(  # ty: ignore[invalid-method-override] -- intentional SBF-specific kwargs, not a substitutability bug: callers going through the base GNSSDataReader.to_ds contract never pass pad_global_sid/strip_fillval by name
        self,
        keep_data_vars: list[str] | None = None,
        pad_global_sid: bool = True,
        strip_fillval: bool = True,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert SBF observations to an ``(epoch, sid)`` xarray Dataset.

        Produces the same structure as :class:`~canvod.readers.rinex.v3_04.Rnxv3Obs`
        and passes :func:`~canvod.readers.base.validate_dataset`. The values
        are those of the observation dataset of :meth:`to_ds_and_auxiliary`.

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to retain. If ``None``, all are kept: ``SNR``,
            ``Pseudorange``, ``Phase``, ``Doppler``, ``SSI``, ``Smoothing``,
            ``HalfCycle``. ``LLI`` is not produced: SBF has no
            loss-of-lock indicator.
        pad_global_sid : bool, default True
            If ``True``, pads the dataset to the global SID space via
            :func:`canvod.readers.preprocessing.pad_to_global_sid`.
        strip_fillval : bool, default True
            If ``True``, removes fill values via
            :func:`canvod.readers.preprocessing.strip_fillvalue`.
        **kwargs
            ``keep_sids`` is forwarded to ``pad_to_global_sid``; others are
            ignored.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions ``(epoch, sid)`` that passes
            :func:`~canvod.readers.base.validate_dataset`.
        """
        obs_ds, _ = self._build(
            keep_data_vars=keep_data_vars,
            pad_global_sid=pad_global_sid,
            strip_fillval=strip_fillval,
            store_raw_observables=False,
            with_metadata=False,
            keep_sids=cast(list[str] | None, kwargs.get("keep_sids")),
        )
        return obs_ds

    def to_ds_and_auxiliary(  # ty: ignore[invalid-method-override] -- intentional SBF-specific kwargs, not a substitutability bug: see to_ds() above
        self,
        keep_data_vars: list[str] | None = None,
        pad_global_sid: bool = True,
        strip_fillval: bool = True,
        store_raw_observables: bool = True,
        **kwargs: object,
    ) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
        """Decode the observations and the SBF metadata in one file scan.

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to retain in the obs dataset.
        pad_global_sid : bool, default True
            Pad obs dataset to the global SID space.
        strip_fillval : bool, default True
            Strip fill values from the obs dataset.
        store_raw_observables : bool, default True
            Add pre-correction "raw" observable variables to the obs dataset:
            ``SNR_raw``, ``Pseudorange_unsmoothed``, ``Pseudorange_raw``,
            ``Phase_raw``. Set to ``False`` to reduce dataset size when these
            are not needed.
        **kwargs
            ``keep_sids`` is forwarded to ``pad_to_global_sid``; others are
            ignored.

        Returns
        -------
        tuple[xr.Dataset, dict[str, xr.Dataset]]
            ``(obs_ds, {"sbf_obs": meta_ds})``. ``meta_ds`` has the sids of
            ``obs_ds``; it holds the broadcast satellite geometry
            (SatVisibility), the MeasExtra fields, and the receiver, PVT and
            quality data of each epoch.
        """
        obs_ds, meta_ds = self._build(
            keep_data_vars=keep_data_vars,
            pad_global_sid=pad_global_sid,
            strip_fillval=strip_fillval,
            store_raw_observables=store_raw_observables,
            with_metadata=True,
            keep_sids=cast(list[str] | None, kwargs.get("keep_sids")),
        )
        assert meta_ds is not None
        return obs_ds, {"sbf_obs": meta_ds}

    def _build(  # pylint: disable=too-many-arguments,too-many-locals,too-many-statements
        self,
        *,
        keep_data_vars: list[str] | None,
        pad_global_sid: bool,
        strip_fillval: bool,
        store_raw_observables: bool,
        with_metadata: bool,
        keep_sids: list[str] | None,
    ) -> tuple[xr.Dataset, xr.Dataset | None]:
        """Build the observation dataset and, if requested, the metadata one.

        Both come from one file scan and one call of
        :func:`_decode_observations`.
        """
        groups: list[dict[str, dict[str, Any]]] = []
        timestamps: list[np.datetime64] = []
        for group in _iter_epoch_groups(self.fpath):
            meas = group["MeasEpoch"]
            ts = _tow_wn_to_gps(int(meas["TOW"]), int(meas["WNc"]))
            timestamps.append(np.datetime64(ts.replace(tzinfo=None), "ns"))
            groups.append(group)

        obs = _decode_observations(groups)

        # ---- sid axis: one sid per (svid, signal, GLONASS FreqNr) ---------
        keys = np.stack([obs.svid, obs.sig_num, obs.freq_nr], axis=1)
        if len(keys):
            uniq_keys, key_idx = np.unique(keys, axis=0, return_inverse=True)
            key_idx = key_idx.reshape(-1)
        else:
            uniq_keys = np.empty((0, 3), dtype=np.int64)
            key_idx = np.empty(0, dtype=np.int64)
        key_props = [_sid_props(int(s), int(g), int(f)) for s, g, f in uniq_keys]
        sid_props: dict[str, dict[str, Any]] = {
            p["sid"]: p for p in key_props if p is not None
        }
        sorted_sids = sorted(sid_props)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        key_to_col = np.asarray(
            [-1 if p is None else sid_to_idx[p["sid"]] for p in key_props],
            dtype=np.int64,
        )
        col = key_to_col[key_idx] if len(key_idx) else key_idx
        known = col >= 0
        rows_e = obs.epoch[known]
        rows_s = col[known]

        n_epochs = len(timestamps)
        n_sids = len(sorted_sids)
        shape = (n_epochs, n_sids)

        def _grid(values: NDArray[Any], dtype: Any, fill: Any) -> NDArray[Any]:
            out = np.full(shape, fill, dtype=dtype)
            out[rows_e, rows_s] = values[known]
            return out

        snr_arr = _grid(obs.snr_dbhz, DTYPES["SNR"], np.nan)
        pr_arr = _grid(obs.pseudorange_m, DTYPES["Pseudorange"], np.nan)
        ph_arr = _grid(obs.phase_cycles, DTYPES["Phase"], np.nan)
        dop_arr = _grid(obs.doppler_hz, DTYPES["Doppler"], np.nan)
        # ObsInfo flags: -1 = no observation, 0 = flag clear, 1 = flag set.
        # Bit 0 = smoothing, bit 2 = half-cycle ambiguity (p.262).
        smoothing_arr = _grid(obs.obs_info & 0x01, np.int8, -1)
        half_cycle_arr = _grid((obs.obs_info >> 2) & 0x01, np.int8, -1)
        # SBF has no native RINEX-style SSI field: derive it from C/N0.
        ssi_arr = _snr_dbhz_to_ssi(snr_arr).astype(DTYPES["SSI"])

        coords_obs: dict[str, Any] = {
            "epoch": ("epoch", timestamps, epoch_coord_attrs("GPS")),
            "sid": xr.DataArray(
                np.array(sorted_sids, dtype=object),
                dims=["sid"],
                attrs=COORDS_METADATA["sid"],
            ),
        }
        for name in ("sv", "system", "band", "code"):
            coords_obs[name] = (
                "sid",
                np.array([sid_props[s][name] for s in sorted_sids], dtype=object),
                COORDS_METADATA[name],
            )
        for name in ("freq_center", "freq_min", "freq_max"):
            coords_obs[name] = (
                "sid",
                np.asarray(
                    [sid_props[s][name] for s in sorted_sids], dtype=DTYPES[name]
                ),
                COORDS_METADATA[name],
            )

        attrs = cast(dict[str, Any], self._build_attrs())
        try:
            import pymap3d as pm

            hdr = self.header
            x, y, z = pm.geodetic2ecef(
                math.degrees(hdr.latitude_rad),
                math.degrees(hdr.longitude_rad),
                float(hdr.height_m.to(UREG.meter).magnitude),
            )
            attrs["APPROX POSITION X"] = float(x)
            attrs["APPROX POSITION Y"] = float(y)
            attrs["APPROX POSITION Z"] = float(z)
        except LookupError, AttributeError:
            pass

        obs_vars: dict[str, Any] = {
            "SNR": (["epoch", "sid"], snr_arr, _SBF_CN0_METADATA),
            "Pseudorange": (
                ["epoch", "sid"],
                pr_arr,
                OBSERVABLES_METADATA["Pseudorange"],
            ),
            "Phase": (["epoch", "sid"], ph_arr, OBSERVABLES_METADATA["Phase"]),
            "Doppler": (["epoch", "sid"], dop_arr, OBSERVABLES_METADATA["Doppler"]),
            "SSI": (["epoch", "sid"], ssi_arr, OBSERVABLES_METADATA["SSI"]),
            "Smoothing": (["epoch", "sid"], smoothing_arr, _SMOOTHING_FLAG_ATTRS),
            "HalfCycle": (["epoch", "sid"], half_cycle_arr, _HALF_CYCLE_ATTRS),
        }
        if store_raw_observables:
            # Pre-correction observables; NaN where MeasExtra was not logged.
            with np.errstate(invalid="ignore"):
                pr_unsmoothed = obs.pseudorange_m + obs.smoothing_corr_m
                pr_raw = pr_unsmoothed + obs.mp_correction_m
                ph_raw = obs.phase_cycles + obs.car_mp_corr_cycles
            obs_vars["SNR_raw"] = (
                ["epoch", "sid"],
                _grid(obs.cn0_dbhz, DTYPES["SNR"], np.nan),
                _SNR_RAW_ATTRS,
            )
            obs_vars["Pseudorange_unsmoothed"] = (
                ["epoch", "sid"],
                _grid(pr_unsmoothed, np.float64, np.nan),
                _PSEUDORANGE_UNSMOOTHED_ATTRS,
            )
            obs_vars["Pseudorange_raw"] = (
                ["epoch", "sid"],
                _grid(pr_raw, np.float64, np.nan),
                _PSEUDORANGE_RAW_ATTRS,
            )
            obs_vars["Phase_raw"] = (
                ["epoch", "sid"],
                _grid(ph_raw, np.float64, np.nan),
                _PHASE_RAW_ATTRS,
            )

        obs_ds = xr.Dataset(data_vars=obs_vars, coords=coords_obs, attrs=attrs)

        meta_ds: xr.Dataset | None = None
        if with_metadata:
            meta_ds = self._build_metadata(
                groups, timestamps, obs, sid_props, sorted_sids, _grid
            )

        if pad_global_sid:
            from canvod.readers.preprocessing import pad_to_global_sid

            obs_ds = pad_to_global_sid(obs_ds, keep_sids=keep_sids)

        if strip_fillval:
            from canvod.readers.preprocessing import strip_fillvalue

            obs_ds = strip_fillvalue(obs_ds)

        if meta_ds is not None:
            # Same sids as obs_ds; padded sids get the fill values.
            meta_ds = meta_ds.reindex(sid=obs_ds.sid, fill_value=np.nan)
            for name in ("rise_set", "broadcast_angle_source"):
                if meta_ds[name].dtype != np.int8:
                    meta_ds[name] = meta_ds[name].fillna(-1).astype(np.int8)
            for name in ("tracking_status_raw", "pvt_status_raw"):
                if meta_ds[name].dtype != np.uint16:
                    meta_ds[name] = meta_ds[name].fillna(0).astype(np.uint16)

        validate_dataset(obs_ds, required_vars=keep_data_vars)

        if keep_data_vars is not None:
            obs_ds = obs_ds.drop_vars(
                [v for v in obs_ds.data_vars if v not in keep_data_vars]
            )

        return obs_ds, meta_ds

    def _build_metadata(  # pylint: disable=too-many-arguments,too-many-locals,too-many-statements,too-many-branches
        self,
        groups: list[dict[str, dict[str, Any]]],
        timestamps: list[np.datetime64],
        obs: _Observations,
        sid_props: dict[str, dict[str, Any]],
        sorted_sids: list[str],
        grid: Any,
    ) -> xr.Dataset:
        """Build the SBF metadata dataset on the sid axis of the observations.

        Parameters
        ----------
        groups : list of dict
            Epoch groups from :func:`_iter_epoch_groups`.
        timestamps : list of numpy.datetime64
            Epoch time of each group.
        obs : _Observations
            Decoded observations of ``groups``.
        sid_props : dict
            Properties of each sid.
        sorted_sids : list of str
            The sid axis.
        grid : callable
            Puts a per-observation array onto the ``(epoch, sid)`` grid.
        """
        n_epochs = len(groups)
        n_sids = len(sorted_sids)
        cols_of_sv: dict[str, list[int]] = {}
        for i, sid in enumerate(sorted_sids):
            cols_of_sv.setdefault(sid_props[sid]["sv"], []).append(i)

        theta_deg = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        phi_deg = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        rise_set_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)
        angle_source_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)
        # ChannelStatus raw bitfields, broadcast per sv (0 = idle / no info)
        tracking_status_arr = np.zeros((n_epochs, n_sids), dtype=np.uint16)
        pvt_status_arr = np.zeros((n_epochs, n_sids), dtype=np.uint16)

        pdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        hdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        vdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        n_sv_arr = np.full(n_epochs, -1, dtype=np.int16)
        h_acc_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        v_acc_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        pvt_mode_arr = np.full(n_epochs, -1, dtype=np.int8)
        mean_corr_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        cpu_load_arr = np.full(n_epochs, -1, dtype=np.int8)
        temp_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        rx_error_arr = np.full(n_epochs, 0, dtype=np.int32)
        # QualityInd scores (0-10; -1 = unknown / block absent)
        qual_overall_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_gnss_main_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_rf_main_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_cpu_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_scint_arr = np.full(n_epochs, -1, dtype=np.int8)
        # RFStatus flags (0/1; -1 = block absent)
        spoofing_arr = np.full(n_epochs, -1, dtype=np.int8)
        nma_fail_arr = np.full(n_epochs, -1, dtype=np.int8)

        for t, group in enumerate(groups):
            dop = group.get("DOP")
            if dop is not None:
                # PDOP/HDOP/VDOP: u2, 0.01/LSB, Do-Not-Use 0 (RefGuide-4.14.0, DOP)
                for arr, field in (
                    (pdop_arr, "PDOP"),
                    (hdop_arr, "HDOP"),
                    (vdop_arr, "VDOP"),
                ):
                    raw = int(dop[field])
                    if raw != 0:
                        arr[t] = raw * 0.01

            pvt = group.get("PVTGeodetic")
            if pvt is not None:
                # RefGuide-4.14.0, PVTGeodetic: NrSV u1 Do-Not-Use 255;
                # H/VAccuracy u2 0.01 m Do-Not-Use 65535; Mode bits 0-3;
                # MeanCorrAge u2 0.01 s Do-Not-Use 65535.
                raw_nrsv = int(pvt["NrSV"])
                n_sv_arr[t] = -1 if raw_nrsv == 255 else raw_nrsv
                for arr, field in ((h_acc_arr, "HAccuracy"), (v_acc_arr, "VAccuracy")):
                    raw = int(pvt[field])
                    if raw != 65535:
                        arr[t] = raw * 0.01
                pvt_mode_arr[t] = int(pvt["Mode"]) & 0x0F
                raw_mca = int(pvt["MeanCorrAge"])
                if raw_mca != 65535:
                    mean_corr_arr[t] = raw_mca * 0.01

            status = group.get("ReceiverStatus")
            if status is not None:
                # RefGuide-4.14.0, ReceiverStatus: CPULoad Do-Not-Use 255;
                # Temperature u1, offset 100, Do-Not-Use 0.
                raw_cpu = int(status["CPULoad"])
                cpu_load_arr[t] = -1 if raw_cpu == 255 else raw_cpu
                raw_temp = int(status["Temperature"])
                if raw_temp != 0:
                    temp_arr[t] = float(raw_temp - 100)
                rx_error_arr[t] = int(status["RxError"])

            satvis = group.get("SatVisibility")
            if satvis is not None:
                # RefGuide-4.14.0, SatVisibility p.400: Azimuth u2 0.01 deg,
                # Do-Not-Use 65535; Elevation i2 0.01 deg, Do-Not-Use -32768;
                # RiseSet 255 = unknown; SatelliteInfo 1 = almanac,
                # 2 = ephemeris, 255 = unknown.
                for sat in satvis.get("SatInfo", []):
                    svid = int(sat["SVID"])
                    if svid in (_SVID_DNU, _SVID_GLONASS_UNKNOWN_SLOT):
                        continue
                    system, prn = decode_svid(svid)
                    cols = cols_of_sv.get(f"{system}{prn:02d}")
                    if not cols:
                        continue
                    elev = int(sat["Elevation"])
                    azim = int(sat["Azimuth"])
                    rs = int(sat["RiseSet"])
                    theta_deg[t, cols] = (
                        np.nan if elev == -32768 else 90.0 - elev * 0.01
                    )
                    phi_deg[t, cols] = np.nan if azim == 65535 else azim * 0.01
                    rise_set_arr[t, cols] = -1 if rs == 255 else rs
                    src = int(sat["SatelliteInfo"])
                    angle_source_arr[t, cols] = -1 if src == 255 else src

            qualind = group.get("QualityInd")
            if qualind is not None:
                q_vals = _decode_quality_indicators(qualind)
                qual_overall_arr[t] = q_vals.get(0, -1)
                qual_gnss_main_arr[t] = q_vals.get(1, -1)
                qual_rf_main_arr[t] = q_vals.get(11, -1)
                qual_cpu_arr[t] = q_vals.get(21, -1)
                qual_scint_arr[t] = q_vals.get(29, -1)

            rfstatus = group.get("RFStatus")
            if rfstatus is not None:
                # RFStatus Flags: bit 0 spoofing, bit 1 NMA failure
                rf_flags = int(rfstatus["Flags"])
                spoofing_arr[t] = rf_flags & 0x01
                nma_fail_arr[t] = (rf_flags >> 1) & 0x01

            chanstatus = group.get("ChannelStatus")
            if chanstatus is not None:
                for sv, trk_raw, pvt_raw in _extract_tracking_info(chanstatus):
                    cols = cols_of_sv.get(sv)
                    if cols:
                        tracking_status_arr[t, cols] = trk_raw
                        pvt_status_arr[t, cols] = pvt_raw

        coords_meta: dict[str, Any] = {
            "epoch": ("epoch", timestamps, epoch_coord_attrs("GPS")),
            "sid": xr.DataArray(
                sorted_sids, dims=["sid"], attrs=COORDS_METADATA["sid"]
            ),
        }
        for name in ("sv", "system", "band", "code"):
            coords_meta[name] = (
                "sid",
                [sid_props[s][name] for s in sorted_sids],
                COORDS_METADATA[name],
            )
        for name in ("freq_center", "freq_min", "freq_max"):
            coords_meta[name] = (
                "sid",
                np.asarray([sid_props[s][name] for s in sorted_sids], dtype=np.float32),
                COORDS_METADATA[name],
            )
        coords_meta.update(
            {
                "pdop": ("epoch", pdop_arr, _PDOP_ATTRS),
                "hdop": ("epoch", hdop_arr, _HDOP_ATTRS),
                "vdop": ("epoch", vdop_arr, _VDOP_ATTRS),
                "n_sv": ("epoch", n_sv_arr, _N_SV_ATTRS),
                "h_accuracy_m": ("epoch", h_acc_arr, _H_ACCURACY_ATTRS),
                "v_accuracy_m": ("epoch", v_acc_arr, _V_ACCURACY_ATTRS),
                "pvt_mode": ("epoch", pvt_mode_arr, _PVT_MODE_ATTRS),
                "mean_corr_age_s": ("epoch", mean_corr_arr, _MEAN_CORR_AGE_ATTRS),
                "cpu_load": ("epoch", cpu_load_arr, _CPU_LOAD_ATTRS),
                "temperature_c": ("epoch", temp_arr, _TEMPERATURE_ATTRS),
                "rx_error": ("epoch", rx_error_arr, _RX_ERROR_ATTRS),
                "qual_overall": ("epoch", qual_overall_arr, _QUAL_OVERALL_ATTRS),
                "qual_gnss_main": ("epoch", qual_gnss_main_arr, _QUAL_GNSS_MAIN_ATTRS),
                "qual_rf_main": ("epoch", qual_rf_main_arr, _QUAL_RF_MAIN_ATTRS),
                "qual_cpu": ("epoch", qual_cpu_arr, _QUAL_CPU_ATTRS),
                "qual_scintillation": ("epoch", qual_scint_arr, _QUAL_SCINT_ATTRS),
                "spoofing_flag": ("epoch", spoofing_arr, _SPOOFING_FLAG_ATTRS),
                "nma_fail_flag": ("epoch", nma_fail_arr, _NMA_FAIL_ATTRS),
            }
        )

        def _f32(values: NDArray[np.float64]) -> NDArray[np.float32]:
            return grid(values, np.float32, np.nan)

        dims = ["epoch", "sid"]
        return xr.Dataset(
            data_vars={
                "broadcast_theta": (
                    dims,
                    np.deg2rad(theta_deg),
                    _BROADCAST_THETA_ATTRS,
                ),
                "broadcast_phi": (dims, np.deg2rad(phi_deg), _BROADCAST_PHI_ATTRS),
                "rise_set": (dims, rise_set_arr, _RISE_SET_ATTRS),
                "broadcast_angle_source": (
                    dims,
                    angle_source_arr,
                    _BROADCAST_ANGLE_SOURCE_ATTRS,
                ),
                "mp_correction_m": (
                    dims,
                    _f32(obs.mp_correction_m),
                    _MP_CORRECTION_ATTRS,
                ),
                "smoothing_corr_m": (
                    dims,
                    _f32(obs.smoothing_corr_m),
                    _SMOOTHING_CORR_ATTRS,
                ),
                "code_var": (dims, _f32(obs.code_var_m2), _CODE_VAR_ATTRS),
                "carrier_var": (
                    dims,
                    _f32(obs.carrier_var_mcycle2),
                    _CARRIER_VAR_ATTRS,
                ),
                "lock_time_s": (dims, _f32(obs.extra_lock_time_s), _LOCK_TIME_ATTRS),
                "cum_loss_cont": (dims, _f32(obs.cum_loss_cont), _CUM_LOSS_CONT_ATTRS),
                "car_mp_corr_cycles": (
                    dims,
                    _f32(obs.car_mp_corr_cycles),
                    _CAR_MP_CORR_ATTRS,
                ),
                "cn0_highres_correction": (
                    dims,
                    _f32(obs.cn0_highres_dbhz),
                    _CN0_HIGHRES_CORRECTION_ATTRS,
                ),
                "tracking_status_raw": (
                    dims,
                    tracking_status_arr,
                    _TRACKING_STATUS_RAW_ATTRS,
                ),
                "pvt_status_raw": (dims, pvt_status_arr, _PVT_STATUS_RAW_ATTRS),
            },
            coords=coords_meta,
            attrs=self._build_attrs(),
        )

    def __repr__(self) -> str:
        """Return a short string representation."""
        return f"SbfReader(file='{self.fpath.name}', epochs={self.num_epochs})"
