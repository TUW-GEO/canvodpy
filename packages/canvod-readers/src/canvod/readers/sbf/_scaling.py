"""Physical-unit scaling functions for SBF measurement fields.

All formulas are taken verbatim from the official reference guide. Every
function accepts plain integers or numpy integer arrays of raw field values,
so the reader can scale all observations of a file in one call. Results are
plain float arrays in the unit named by the function (``_m``, ``_hz``,
``_dbhz``, ``_mhz``, cycles); Do-Not-Use (DNU) values become NaN. Plain floats
instead of ``pint.Quantity``, because SBF files hold millions of values.

Physical constants are imported from
:mod:`canvod.readers.gnss_specs.constants` to avoid duplication
(``SPEEDOFLIGHT``, ``UREG``).

Primary source
--------------
AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide (Septentrio).
Abbreviated below as **RefGuide-4.14.0**.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from canvod.readers.gnss_specs.constants import SPEEDOFLIGHT, UREG
from canvod.readers.sbf._registry import FDMA_SIGNAL_NUMS

# Speed of light [m/s], derived from the shared SPEEDOFLIGHT constant.
_C_M_S: float = float(SPEEDOFLIGHT.to(UREG.meter / UREG.second).magnitude)


def _ints(raw: ArrayLike) -> NDArray[np.int64]:
    """Raw SBF field values as an int64 array (scalars become 0-d arrays)."""
    return np.asarray(raw, dtype=np.int64)


# ---------------------------------------------------------------------------
# Signal number extraction from Type + ObsInfo bytes (extended signal table)
# Source: RefGuide-4.14.0, MeasEpochChannelType1.Type, p.261; ObsInfo p.262
#   bits 0-4 of Type = SigIdxLo
#   If SigIdxLo == 31: actual signal num = (ObsInfo bits 3-7) + 32
#   Signal type number table: Section 4.1.10, p.256
# ---------------------------------------------------------------------------


def decode_signal_num(type_byte: ArrayLike, obs_info: ArrayLike) -> NDArray[np.int64]:
    """Extract the extended signal type number from a Type/ObsInfo byte pair.

    Parameters
    ----------
    type_byte : int or array of int
        Raw ``u1`` Type field from a Type1 or Type2 sub-block (or from a
        MeasExtraChannelSub sub-block).
    obs_info : int or array of int
        Raw ``u1`` byte that carries the extended signal number: ObsInfo
        in MeasEpoch, Misc in MeasExtra.

    Returns
    -------
    numpy.ndarray of int
        Signal type number in the range 0-39.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1.Type, p.261.
    Bits 5-7 of Type encode the antenna descriptor; they are ignored here.
    """
    sig_idx_lo = _ints(type_byte) & 0x1F  # bits 0-4
    extended = ((_ints(obs_info) >> 3) & 0x1F) + 32
    return np.where(sig_idx_lo == 31, extended, sig_idx_lo)


# ---------------------------------------------------------------------------
# GLONASS frequency number from the Type1 ObsInfo byte
# Source: RefGuide-4.14.0, MeasEpochChannelType1.ObsInfo, p.262
#   If SigIdxLo is 8, 9, 10 or 11, ObsInfo bits 3-7 contain the GLONASS
#   frequency number with an offset of 8.
# ---------------------------------------------------------------------------


def glonass_freq_nr(type_byte: ArrayLike, obs_info: ArrayLike) -> NDArray[np.int64]:
    """GLONASS frequency number (offset 8) from a Type1 sub-block, or -1.

    Parameters
    ----------
    type_byte : int or array of int
        Raw ``u1`` Type field of a MeasEpochChannelType1 sub-block.
    obs_info : int or array of int
        Raw ``u1`` ObsInfo field of the same sub-block.

    Returns
    -------
    numpy.ndarray of int
        ``FreqNr`` (1 = frequency number -7) where the sub-block carries a
        GLONASS FDMA signal, ``-1`` otherwise.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1.ObsInfo, p.262.
    Type2 sub-blocks carry no frequency number; they belong to the same
    satellite as their Type1 sub-block and use its value.
    """
    sig_idx_lo = _ints(type_byte) & 0x1F
    is_fdma = np.isin(sig_idx_lo, list(FDMA_SIGNAL_NUMS))
    return np.where(is_fdma, (_ints(obs_info) >> 3) & 0x1F, -1)


# ---------------------------------------------------------------------------
# CN0 scaling
# Source: RefGuide-4.14.0, MeasEpochChannelType1.CN0, p.261
#   Field: u1, scale 0.25 dB-Hz/LSB, Do-Not-Use 255
#   C/N0 [dB-Hz] = raw * 0.25       if the signal number is 1 or 2
#   C/N0 [dB-Hz] = raw * 0.25 + 10  otherwise
#   Signal numbers 1 (GPS L1P) and 2 (GPS L2P) use the codeless tracking scheme
#   needed for the GPS P-code (RefGuide-4.14.0 Sect. 3.2.4 setCN0Mask, p.97).
# ---------------------------------------------------------------------------


def cn0_dbhz(raw: ArrayLike, sig_num: ArrayLike) -> NDArray[np.float64]:
    """Scale raw CN0 bytes to C/N0 in dB-Hz.

    Parameters
    ----------
    raw : int or array of int
        Raw ``u1`` CN0 field from a Type1 or Type2 sub-block.
    sig_num : int or array of int
        Signal type number (from :func:`decode_signal_num`).

    Returns
    -------
    numpy.ndarray of float
        C/N0 in dB-Hz; NaN where Do-Not-Use (raw == 255).

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1.CN0, p.261.
    Resolution is 0.25 dB-Hz; MeasExtra.Misc CN0HighRes (p.265) extends it
    to 0.03125 dB-Hz.
    """
    raw = _ints(raw)
    offset = np.where(np.isin(_ints(sig_num), (1, 2)), 0.0, 10.0)
    return np.where(raw == 255, np.nan, raw * 0.25 + offset)


# ---------------------------------------------------------------------------
# Type1 pseudorange
# Source: RefGuide-4.14.0, MeasEpochChannelType1, p.261
#   Misc field (u1): bits 0-3 = CodeMSB; CodeLSB field (u4)
#   PR [m]  = (CodeMSB * 4_294_967_296 + CodeLSB) * 0.001
# Do-Not-Use: CodeMSB == 0 AND CodeLSB == 0
# ---------------------------------------------------------------------------


def pseudorange_m(misc: ArrayLike, code_lsb: ArrayLike) -> NDArray[np.float64]:
    """Scale Type1 code fields to pseudorange.

    Parameters
    ----------
    misc : int or array of int
        Raw ``u1`` Misc byte; bits 0-3 carry CodeMSB.
    code_lsb : int or array of int
        Raw ``u4`` CodeLSB field.

    Returns
    -------
    numpy.ndarray of float
        Pseudorange in meters; NaN where Do-Not-Use.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1, p.261.
    """
    code_msb = _ints(misc) & 0x0F
    code_lsb = _ints(code_lsb)
    dnu = (code_msb == 0) & (code_lsb == 0)
    return np.where(dnu, np.nan, (code_msb * 4_294_967_296 + code_lsb) * 1e-3)


# ---------------------------------------------------------------------------
# Type1 Doppler
# Source: RefGuide-4.14.0, MeasEpochChannelType1.Doppler, p.261
#   Field: i4, scale 0.0001 Hz/LSB
# Do-Not-Use: raw == -2_147_483_648  (i4 minimum)
# ---------------------------------------------------------------------------

_DOPPLER_DNU: int = -(1 << 31)  # -2_147_483_648


def doppler_hz(raw: ArrayLike) -> NDArray[np.float64]:
    """Scale Type1 Doppler raw ``i4`` values to Hz.

    Parameters
    ----------
    raw : int or array of int
        Raw ``i4`` Doppler field.

    Returns
    -------
    numpy.ndarray of float
        Doppler shift in Hz (positive = approaching); NaN where Do-Not-Use.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1.Doppler, p.261.
    """
    raw = _ints(raw)
    return np.where(raw == _DOPPLER_DNU, np.nan, raw * 1e-4)


# ---------------------------------------------------------------------------
# Carrier phase (Type1 and Type2)
# Source: RefGuide-4.14.0, MeasEpochChannelType1 p.261, Type2 p.263
#   λ          = c / f
#   L [cycles] = PR [m] / λ  +  (CarrierMSB * 65536 + CarrierLSB) * 0.001
# Do-Not-Use: CarrierMSB == -128 AND CarrierLSB == 0
# ---------------------------------------------------------------------------


def phase_cycles(
    pr_m: ArrayLike,
    carrier_msb: ArrayLike,
    carrier_lsb: ArrayLike,
    freq_hz: ArrayLike,
) -> NDArray[np.float64]:
    """Scale carrier fields to carrier phase in cycles.

    Parameters
    ----------
    pr_m : float or array of float
        Pseudorange in meters of the same sub-block (Type1:
        :func:`pseudorange_m`, Type2: :func:`pr2_m`).
    carrier_msb : int or array of int
        Raw ``i1`` CarrierMSB field.
    carrier_lsb : int or array of int
        Raw ``u2`` CarrierLSB field.
    freq_hz : float or array of float
        Carrier frequency of the signal in Hz.

    Returns
    -------
    numpy.ndarray of float
        Carrier phase in cycles; NaN where Do-Not-Use, or
        where the pseudorange or the frequency is NaN.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType1, p.261.
    Uses :data:`~canvod.readers.gnss_specs.constants.SPEEDOFLIGHT`.
    """
    carrier_msb = _ints(carrier_msb)
    carrier_lsb = _ints(carrier_lsb)
    dnu = (carrier_msb == -128) & (carrier_lsb == 0)
    wavelength_m = _C_M_S / np.asarray(freq_hz, dtype=np.float64)
    cycles = (
        np.asarray(pr_m, dtype=np.float64) / wavelength_m
        + (carrier_msb * 65_536 + carrier_lsb) * 1e-3
    )
    return np.where(dnu, np.nan, cycles)


# ---------------------------------------------------------------------------
# OffsetMSB decoding for Type2 sub-blocks
# Source: RefGuide-4.14.0, MeasEpochChannelType2.OffsetsMSB, p.262
#   bits 0-2: CodeOffsetMSB    (3-bit two's-complement, range -4 to +3)
#   bits 3-7: DopplerOffsetMSB (5-bit two's-complement, range -16 to +15)
# ---------------------------------------------------------------------------


def _signed_n_bit(value: ArrayLike, bits: int) -> NDArray[np.int64]:
    """Reinterpret unsigned integers as signed n-bit two's-complement."""
    value = _ints(value)
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def decode_offsets_msb(
    offset_msb: ArrayLike,
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Decode the Type2 OffsetMSB byte into (CodeOffsetMSB, DopplerOffsetMSB).

    Parameters
    ----------
    offset_msb : int or array of int
        Raw ``u1`` OffsetMSB byte.

    Returns
    -------
    code_offset_msb : numpy.ndarray of int
        3-bit signed value in range [-4, +3].
    doppler_offset_msb : numpy.ndarray of int
        5-bit signed value in range [-16, +15].

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType2.OffsetsMSB, p.262.
    """
    offset_msb = _ints(offset_msb)
    code_raw = offset_msb & 0x07  # bits 0-2
    doppler_raw = (offset_msb >> 3) & 0x1F  # bits 3-7
    return _signed_n_bit(code_raw, 3), _signed_n_bit(doppler_raw, 5)


# ---------------------------------------------------------------------------
# Type2 pseudorange
# Source: RefGuide-4.14.0, MeasEpochChannelType2, p.263
#   PR_type2 [m] = PR_type1 [m]  +  (CodeOffsetMSB * 65536 + CodeOffsetLSB) * 0.001
# Do-Not-Use: CodeOffsetMSB == -4 AND CodeOffsetLSB == 0
# ---------------------------------------------------------------------------


def pr2_m(
    pr1_m: ArrayLike,
    code_offset_msb: ArrayLike,
    code_offset_lsb: ArrayLike,
) -> NDArray[np.float64]:
    """Compute Type2 pseudorange from the Type1 pseudorange and offset fields.

    Parameters
    ----------
    pr1_m : float or array of float
        Type1 pseudorange in meters (from :func:`pseudorange_m`).
    code_offset_msb : int or array of int
        3-bit signed CodeOffsetMSB (from :func:`decode_offsets_msb`).
    code_offset_lsb : int or array of int
        Raw ``u2`` CodeOffsetLSB field.

    Returns
    -------
    numpy.ndarray of float
        Type2 pseudorange in meters; NaN where Do-Not-Use or where the
        Type1 pseudorange is NaN.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType2, p.263.
    """
    code_offset_msb = _ints(code_offset_msb)
    code_offset_lsb = _ints(code_offset_lsb)
    dnu = (code_offset_msb == -4) & (code_offset_lsb == 0)
    offset_m = np.where(
        dnu, np.nan, (code_offset_msb * 65_536 + code_offset_lsb) * 1e-3
    )
    return np.asarray(pr1_m, dtype=np.float64) + offset_m


# ---------------------------------------------------------------------------
# Type2 Doppler
# Source: RefGuide-4.14.0, MeasEpochChannelType2, p.263
#   D_type2 [Hz] = D_type1 * (freq_type2 / freq_type1)
#                + (DopplerOffsetMSB * 65536 + DopplerOffsetLSB) * 1e-4
# Do-Not-Use: DopplerOffsetMSB == -16 AND DopplerOffsetLSB == 0
# ---------------------------------------------------------------------------


def doppler2_hz(
    d1_hz: ArrayLike,
    doppler_offset_msb: ArrayLike,
    doppler_offset_lsb: ArrayLike,
    freq_type2_hz: ArrayLike,
    freq_type1_hz: ArrayLike,
) -> NDArray[np.float64]:
    """Compute Type2 Doppler from the Type1 Doppler and differential offset.

    Parameters
    ----------
    d1_hz : float or array of float
        Type1 Doppler in Hz (from :func:`doppler_hz`).
    doppler_offset_msb : int or array of int
        5-bit signed DopplerOffsetMSB (from :func:`decode_offsets_msb`).
    doppler_offset_lsb : int or array of int
        Raw ``u2`` DopplerOffsetLSB field.
    freq_type2_hz : float or array of float
        Carrier frequency of the Type2 signal in Hz.
    freq_type1_hz : float or array of float
        Carrier frequency of the Type1 (master) signal in Hz.

    Returns
    -------
    numpy.ndarray of float
        Type2 Doppler in Hz; NaN where Do-Not-Use or where an input is NaN.

    Notes
    -----
    Source: RefGuide-4.14.0, MeasEpochChannelType2, p.263.
    """
    doppler_offset_msb = _ints(doppler_offset_msb)
    doppler_offset_lsb = _ints(doppler_offset_lsb)
    dnu = (doppler_offset_msb == -16) & (doppler_offset_lsb == 0)
    alpha = np.asarray(freq_type2_hz, dtype=np.float64) / np.asarray(
        freq_type1_hz, dtype=np.float64
    )
    offset_hz = np.where(
        dnu, np.nan, (doppler_offset_msb * 65_536 + doppler_offset_lsb) * 1e-4
    )
    return np.asarray(d1_hz, dtype=np.float64) * alpha + offset_hz


# ---------------------------------------------------------------------------
# GLONASS FDMA carrier frequencies
# Source: RefGuide-4.14.0, Signal type table Section 4.1.10, p.256
#   G1 [MHz] = 1602.000 + (FreqNr - 8) * 9/16   (signals 8, 9)
#   G2 [MHz] = 1246.000 + (FreqNr - 8) * 7/16   (signals 10, 11)
#   FreqNr as defined in Section 4.1.9, p.255 (offset 8)
# ---------------------------------------------------------------------------

_G1_BASE_HZ: float = 1602.000e6
_G1_STEP_HZ: float = 9 / 16 * 1e6  # per frequency number
_G2_BASE_HZ: float = 1246.000e6
_G2_STEP_HZ: float = 7 / 16 * 1e6  # per frequency number
_FREQ_NR_OFFSET: int = 8  # frequency number = FreqNr - 8


def glonass_freq_hz(signal_num: ArrayLike, freq_nr: ArrayLike) -> NDArray[np.float64]:
    """Return the GLONASS FDMA carrier frequency of each observation.

    Parameters
    ----------
    signal_num : int or array of int
        SBF signal type number; must be 8 (L1CA), 9 (L1P), 10 (L2P)
        or 11 (L2CA).
    freq_nr : int or array of int
        ``FreqNr`` (from :func:`glonass_freq_nr`), frequency number with an
        offset of 8.

    Returns
    -------
    numpy.ndarray of float
        Carrier frequency in Hz.

    Raises
    ------
    ValueError
        If any ``signal_num`` is not a GLONASS FDMA signal (8-11).

    Notes
    -----
    Source: RefGuide-4.14.0, Section 4.1.10, p.256.
    GLONASS L3 CDMA (signal 12) has a fixed frequency (1202.025 MHz) stored
    directly in :data:`~canvod.readers.sbf._registry.SIGNAL_TABLE`.
    """
    signal_num = _ints(signal_num)
    if not np.isin(signal_num, list(FDMA_SIGNAL_NUMS)).all():
        raise ValueError(f"signal_num {signal_num} is not a GLONASS FDMA signal (8-11)")
    number = _ints(freq_nr) - _FREQ_NR_OFFSET
    g1 = _G1_BASE_HZ + number * _G1_STEP_HZ
    g2 = _G2_BASE_HZ + number * _G2_STEP_HZ
    return np.where(signal_num <= 9, g1, g2)
