"""Pydantic data models for decoded SBF observations.

Physical-unit fields carry :class:`pint.Quantity` objects so downstream
code can perform unit-safe arithmetic and conversions.  Do-Not-Use sentinel
values are represented as ``None``.
"""

from __future__ import annotations

from datetime import datetime

import pint
from pydantic import BaseModel, ConfigDict


class SbfHeader(BaseModel):
    """Receiver metadata extracted from a ReceiverSetup block.

    Attributes
    ----------
    marker_name : str
        RINEX-style station marker name (NUL-stripped ASCII).
    marker_number : str
        Station marker number.
    observer : str
        Observer / operator name.
    agency : str
        Operating agency name.
    rx_serial : str
        Receiver serial number.
    rx_name : str
        Receiver model name (e.g. ``"GRB0053"``).
    rx_version : str
        Receiver firmware version string (e.g. ``"4.14.4"``).
    ant_serial : str
        Antenna serial number.
    ant_type : str
        Antenna type string.
    delta_h : pint.Quantity
        Antenna height above marker in meters.
    delta_e : pint.Quantity
        Antenna east offset in meters.
    delta_n : pint.Quantity
        Antenna north offset in meters.
    latitude_rad : float
        Approximate receiver latitude [rad].
    longitude_rad : float
        Approximate receiver longitude [rad].
    height_m : pint.Quantity
        Approximate receiver height above ellipsoid in meters.
    gnss_fw_version : str
        Full GNSS firmware version string.
    product_name : str
        Product model name.

    Notes
    -----
    Source: RefGuide-4.14.0, ReceiverSetup block.
    String fields decoded from NUL-padded ``c1[n]`` binary arrays.
    Offset fields (deltaH/E/N) and height use UREG meters.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    marker_name: str
    marker_number: str
    observer: str
    agency: str
    rx_serial: str
    rx_name: str
    rx_version: str
    ant_serial: str
    ant_type: str
    delta_h: pint.Quantity
    delta_e: pint.Quantity
    delta_n: pint.Quantity
    latitude_rad: float
    longitude_rad: float
    height_m: pint.Quantity
    gnss_fw_version: str
    product_name: str


class SbfSignalObs(BaseModel):
    """One decoded signal observation from a MeasEpoch sub-block.

    A Type1 (master) sub-block produces one ``SbfSignalObs`` with
    ``is_type2=False``; each associated Type2 (slave) sub-block produces
    a separate ``SbfSignalObs`` with ``is_type2=True``.

    Attributes
    ----------
    svid : int
        Septentrio internal satellite identifier (raw field, 1-245).
    system : str
        RINEX single-letter system code (``"G"``, ``"R"``, ``"E"``, etc.).
    prn : int
        Satellite PRN / slot number.
    signal_num : int
        SBF signal type number (0-39, after extended-table resolution).
    signal_type : str
        Septentrio signal label (e.g. ``"L1CA"``, ``"E5a"``).
    rx_channel : int
        Receiver tracking channel index.
    lock_time_s : int
        Duration of continuous carrier-phase lock in seconds (1 s/LSB,
        raw value). Type1: ``u2``, clipped at 65534 s, 65535 = Do-Not-Use.
        Type2: ``u1``, clipped at 254 s, 255 = Do-Not-Use.
    cn0 : pint.Quantity or None
        C/N0 in ``dBHz``, with the MeasExtra CN0HighRes value of the same
        epoch added where logged. ``None`` if Do-Not-Use (raw == 255).
    pseudorange : pint.Quantity or None
        Pseudorange in meters. ``None`` if Do-Not-Use.
    doppler : pint.Quantity or None
        Doppler shift in Hz (positive = approaching). ``None`` if Do-Not-Use.
    phase_cycles : float or None
        Carrier phase in cycles (dimensionless). ``None`` if Do-Not-Use
        or carrier frequency unknown.
    obs_info : int
        Raw ObsInfo byte (smoothing / multipath / half-cycle flags).
    is_type2 : bool
        ``False`` for a Type1 master observation; ``True`` for Type2 slave.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpoch block, pp. 259-263.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    svid: int
    system: str
    prn: int
    signal_num: int
    signal_type: str
    rx_channel: int
    lock_time_s: int
    cn0: pint.Quantity | None
    pseudorange: pint.Quantity | None
    doppler: pint.Quantity | None
    phase_cycles: float | None
    obs_info: int
    is_type2: bool


class SbfEpoch(BaseModel):
    """One MeasEpoch block decoded into physical observations.

    Attributes
    ----------
    tow_ms : int
        GPS Time of Week in milliseconds.
    wn : int
        GPS Week Number (continuous, no rollover).
    timestamp : datetime
        GPS time derived from TOW + WN (no leap seconds).
    common_flags : int
        Raw CommonFlags byte. Bit 0: multipath mitigation enabled;
        bit 1: at least one code measurement smoothed; bit 3: clock
        steering active (RefGuide-4.14.0, MeasEpoch, p.260).
    cum_clk_jumps : int
        Cumulative receiver clock jumps modulo 256 since power-on.
    observations : tuple of SbfSignalObs
        All decoded signal observations (Type1 and associated Type2).

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpoch block header, p.260.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tow_ms: int
    wn: int
    timestamp: datetime
    common_flags: int
    cum_clk_jumps: int
    observations: tuple[SbfSignalObs, ...]
