"""Unit tests for SBF physical-unit scaling functions.

All expected values are derived from the Septentrio AsteRx SB3 ProBase
Firmware v4.14.0 Reference Guide (RefGuide-4.14.0).

These are pure-function tests — no test data files required. The functions
take scalars or arrays and return float arrays, NaN where Do-Not-Use.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from canvod.readers.gnss_specs.constants import SPEEDOFLIGHT, UREG
from canvod.readers.sbf._scaling import (
    _DOPPLER_DNU,
    _signed_n_bit,
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

# Speed of light for hand-calculations
_C = float(SPEEDOFLIGHT.to(UREG.meter / UREG.second).magnitude)


# ===================================================================
# decode_signal_num — RefGuide-4.14.0, p.261
# Type byte bits 0-4 = SigIdxLo
# If SigIdxLo == 31: signal_num = (ObsInfo >> 3) & 0x1F + 32
# Otherwise: signal_num = SigIdxLo
# ===================================================================


class TestDecodeSignalNum:
    """Signal number extraction from Type/ObsInfo byte pair."""

    @pytest.mark.parametrize(
        "type_byte,obs_info,expected",
        [
            # Normal signals: SigIdxLo < 31 — obs_info ignored
            (0, 0, 0),  # GPS L1CA
            (1, 0, 1),  # GPS L1P
            (2, 0, 2),  # GPS L2P
            (17, 0, 17),  # Galileo E1
            (30, 0, 30),  # BeiDou B3I
            # Antenna bits 5-7 set — must be masked out
            (0b11100000 | 4, 0, 4),  # antenna=7, SigIdxLo=4 → GPS L5
            (0b01100000 | 20, 0, 20),  # antenna=3, SigIdxLo=20 → Galileo E5a
            # Extended signal: SigIdxLo == 31, actual in ObsInfo bits 3-7
            # ObsInfo bits 3-7 = 0 → signal_num = 0 + 32 = 32 (QZSS L1C)
            (31, 0b00000_000, 32),
            # ObsInfo bits 3-7 = 1 → 1 + 32 = 33 (QZSS L1S)
            (31, 0b00001_000, 33),
            # ObsInfo bits 3-7 = 2 → 2 + 32 = 34 (BeiDou B2b)
            (31, 0b00010_000, 34),
            # ObsInfo bits 3-7 = 6 → 6 + 32 = 38 (QZSS L1CB tentative)
            (31, 0b00110_000, 38),
            # ObsInfo bits 3-7 = 7 → 7 + 32 = 39 (QZSS L5S tentative)
            (31, 0b00111_000, 39),
            # Extended + antenna bits + low ObsInfo bits set (must isolate correctly)
            (0b11100000 | 31, 0b00010_101, 34),  # only bits 3-7 matter
        ],
    )
    def test_decode_signal_num(self, type_byte, obs_info, expected):
        assert decode_signal_num(type_byte, obs_info) == expected

    def test_array_input(self):
        """Arrays are decoded element-wise."""
        np.testing.assert_array_equal(
            decode_signal_num([0, 31, 17], [0, 0b00010_000, 0]), [0, 34, 17]
        )


# ===================================================================
# glonass_freq_nr — RefGuide-4.14.0, MeasEpochChannelType1.ObsInfo, p.262
# For GLONASS FDMA signals (SigIdxLo 8-11), ObsInfo bits 3-7 hold the
# frequency number with an offset of 8. -1 for all other signals.
# ===================================================================


class TestGlonassFreqNr:
    """GLONASS frequency number from Type/ObsInfo."""

    @pytest.mark.parametrize(
        "type_byte,obs_info,expected",
        [
            (8, 0b01001_000, 9),  # GLONASS L1CA, FreqNr 9 (k=+1)
            (11, 0b00001_000, 1),  # GLONASS L2CA, FreqNr 1 (k=-7)
            (0b11100000 | 9, 0b10101_111, 21),  # antenna bits, low bits set
            (0, 0b01001_000, -1),  # GPS L1CA: not FDMA
            (31, 0b00010_000, -1),  # extended signal: bits 3-7 are not FreqNr
        ],
    )
    def test_glonass_freq_nr(self, type_byte, obs_info, expected):
        assert glonass_freq_nr(type_byte, obs_info) == expected


# ===================================================================
# cn0_dbhz — RefGuide-4.14.0, p.261
# C/N0 [dB-Hz] = raw * 0.25 + 10  (normal)
# C/N0 [dB-Hz] = raw * 0.25       (signals 1 and 2 only)
# DNU: raw == 255
# ===================================================================


class TestCn0Dbhz:
    """CN0 byte → C/N0 in dB-Hz."""

    def test_dnu_returns_nan(self):
        """Do-Not-Use sentinel: raw == 255 (u1 max, field not available)."""
        assert math.isnan(cn0_dbhz(255, 0))
        assert math.isnan(cn0_dbhz(255, 17))

    @pytest.mark.parametrize(
        "raw,sig_num,expected_dbhz",
        [
            # Normal signals: raw * 0.25 + 10
            (0, 0, 0.0 + 10.0),  # GPS L1CA, raw == 0 is valid (not DNU)
            (1, 0, 0.25 + 10.0),  # GPS L1CA, min non-DNU
            (100, 0, 25.0 + 10.0),  # GPS L1CA
            (200, 17, 50.0 + 10.0),  # Galileo E1
            (160, 20, 40.0 + 10.0),  # Galileo E5a, typical strong signal
            (254, 0, 63.5 + 10.0),  # Max valid raw for GPS L1CA (255 is DNU)
            # Signals 1 and 2: raw * 0.25 (no +10 offset)
            (100, 1, 25.0),  # GPS L1P
            (100, 2, 25.0),  # GPS L2P
            (200, 1, 50.0),  # GPS L1P
            (1, 2, 0.25),  # GPS L2P, min non-DNU
        ],
    )
    def test_cn0_scaling(self, raw, sig_num, expected_dbhz):
        assert abs(cn0_dbhz(raw, sig_num) - expected_dbhz) < 1e-10

    def test_array_input(self):
        """Element-wise, with the offset chosen per signal."""
        np.testing.assert_allclose(
            cn0_dbhz([100, 100, 255], [0, 1, 0]), [35.0, 25.0, np.nan]
        )


# ===================================================================
# pseudorange_m — RefGuide-4.14.0, p.261
# PR [m] = (CodeMSB * 4294967296 + CodeLSB) * 0.001
# CodeMSB = Misc & 0x0F
# DNU: CodeMSB == 0 AND CodeLSB == 0
# ===================================================================


class TestPseudorangeM:
    """Type1 pseudorange scaling."""

    def test_dnu_returns_nan(self):
        """Do-Not-Use: CodeMSB==0 and CodeLSB==0."""
        assert math.isnan(pseudorange_m(misc=0, code_lsb=0))

    def test_dnu_misc_has_upper_bits(self):
        """Upper nibble of Misc doesn't affect CodeMSB; DNU still triggers."""
        assert math.isnan(pseudorange_m(misc=0xF0, code_lsb=0))

    def test_basic_scaling(self):
        """CodeMSB=0, CodeLSB=20_000_000 → 20_000 m."""
        assert abs(pseudorange_m(misc=0, code_lsb=20_000_000) - 20_000.0) < 1e-6

    def test_code_msb_contribution(self):
        """CodeMSB=1, CodeLSB=0 → 1 * 4294967296 * 0.001 = 4_294_967.296 m."""
        assert abs(pseudorange_m(misc=1, code_lsb=0) - 4_294_967.296) < 1e-3

    def test_gps_typical_pseudorange(self):
        """GPS MEO pseudorange ~20,000–26,000 km.

        CodeMSB=5, CodeLSB=0 → 5 * 4294967.296 m ≈ 21,475 km.
        """
        pr_km = pseudorange_m(misc=5, code_lsb=0) / 1000
        assert 19_000 < pr_km < 30_000

    def test_misc_upper_nibble_ignored(self):
        """Bits 4-7 of Misc are reserved; only bits 0-3 (CodeMSB) matter."""
        assert pseudorange_m(misc=0x01, code_lsb=1_000_000) == pseudorange_m(
            misc=0xF1, code_lsb=1_000_000
        )


# ===================================================================
# doppler_hz — RefGuide-4.14.0, p.261
# D [Hz] = raw * 0.0001
# DNU: raw == -2147483648 (i4 minimum)
# ===================================================================


class TestDopplerHz:
    """Type1 Doppler scaling."""

    def test_dnu_returns_nan(self):
        assert math.isnan(doppler_hz(_DOPPLER_DNU))
        assert math.isnan(doppler_hz(-(1 << 31)))

    def test_zero_doppler(self):
        assert doppler_hz(0) == 0.0

    @pytest.mark.parametrize(
        "raw,expected_hz",
        [
            (10_000, 1.0),  # 10000 * 0.0001 = 1.0 Hz
            (-10_000, -1.0),
            (1, 0.0001),
            (100_000_000, 10_000.0),  # Strong Doppler
        ],
    )
    def test_doppler_scaling(self, raw, expected_hz):
        assert abs(doppler_hz(raw) - expected_hz) < 1e-10


# ===================================================================
# phase_cycles — RefGuide-4.14.0, p.261
# L [cycles] = PR [m] / λ + (CarrierMSB * 65536 + CarrierLSB) * 0.001
# λ = c / freq_hz
# DNU: CarrierMSB == -128 AND CarrierLSB == 0
# ===================================================================

_PR_M = 22_000_000.0
_L1_HZ = 1575.42e6


class TestPhaseCycles:
    """Type1 carrier phase scaling."""

    def test_dnu_returns_nan(self):
        """Do-Not-Use: CarrierMSB==-128 and CarrierLSB==0."""
        assert math.isnan(phase_cycles(_PR_M, -128, 0, _L1_HZ))

    def test_not_dnu_when_carrier_msb_minus128_lsb_nonzero(self):
        """If CarrierLSB != 0, this is NOT DNU even with CarrierMSB == -128."""
        assert not math.isnan(phase_cycles(_PR_M, -128, 1, _L1_HZ))

    def test_nan_pseudorange_or_frequency(self):
        """Unknown pseudorange or frequency gives NaN."""
        assert math.isnan(phase_cycles(np.nan, 0, 0, _L1_HZ))
        assert math.isnan(phase_cycles(_PR_M, 0, 0, np.nan))

    def test_hand_calculation_gps_l1(self):
        """Manual calculation for GPS L1 (1575.42 MHz).

        λ = c / f = 299792458 / 1575420000 = 0.190293673 m
        PR = 22_000_000 m
        CarrierMSB = 0, CarrierLSB = 0
        L = PR / λ + 0 = 22_000_000 / 0.190293673 ≈ 115,610,321.5 cycles
        """
        expected = _PR_M / (_C / _L1_HZ)
        assert abs(phase_cycles(_PR_M, 0, 0, _L1_HZ) - expected) < 1.0

    def test_carrier_offset_contribution(self):
        """Verify the (CarrierMSB * 65536 + CarrierLSB) * 0.001 term."""
        base = phase_cycles(_PR_M, 0, 0, _L1_HZ)
        with_offset = phase_cycles(_PR_M, 1, 1000, _L1_HZ)
        offset_cycles = (1 * 65536 + 1000) * 0.001
        assert abs((with_offset - base) - offset_cycles) < 1e-6

    def test_negative_carrier_msb(self):
        """Negative CarrierMSB produces a negative offset."""
        base = phase_cycles(_PR_M, 0, 0, _L1_HZ)
        neg = phase_cycles(_PR_M, -1, 0, _L1_HZ)
        assert abs((neg - base) - (-1 * 65536 * 0.001)) < 1e-6


# ===================================================================
# _signed_n_bit and decode_offsets_msb — RefGuide-4.14.0, p.263
# OffsetMSB bits 0-2: CodeOffsetMSB (3-bit two's complement, -4..+3)
# OffsetMSB bits 3-7: DopplerOffsetMSB (5-bit two's complement, -16..+15)
# ===================================================================


class TestSignedNBit:
    """Two's complement reinterpretation helper."""

    @pytest.mark.parametrize(
        "value,bits,expected",
        [
            (0, 3, 0),
            (3, 3, 3),  # max positive 3-bit
            (4, 3, -4),  # min negative 3-bit (100₂ = -4)
            (7, 3, -1),  # 111₂ = -1
            (5, 3, -3),  # 101₂ = -3
            (0, 5, 0),
            (15, 5, 15),  # max positive 5-bit
            (16, 5, -16),  # min negative 5-bit
            (31, 5, -1),
        ],
    )
    def test_signed_n_bit(self, value, bits, expected):
        assert _signed_n_bit(value, bits) == expected


class TestDecodeOffsetsMsb:
    """OffsetMSB byte → (CodeOffsetMSB, DopplerOffsetMSB)."""

    def test_zero_byte(self):
        code, doppler = decode_offsets_msb(0)
        assert code == 0
        assert doppler == 0

    def test_max_positive_code_only(self):
        """Bits 0-2 = 011 = 3 (max positive), bits 3-7 = 0."""
        code, doppler = decode_offsets_msb(0b00000_011)
        assert code == 3
        assert doppler == 0

    def test_min_negative_code_only(self):
        """Bits 0-2 = 100 = -4 (min negative 3-bit), bits 3-7 = 0."""
        code, doppler = decode_offsets_msb(0b00000_100)
        assert code == -4
        assert doppler == 0

    def test_max_positive_doppler_only(self):
        """Bits 0-2 = 0, bits 3-7 = 01111 = 15."""
        code, doppler = decode_offsets_msb(0b01111_000)
        assert code == 0
        assert doppler == 15

    def test_min_negative_doppler_only(self):
        """Bits 0-2 = 0, bits 3-7 = 10000 = -16."""
        code, doppler = decode_offsets_msb(0b10000_000)
        assert code == 0
        assert doppler == -16

    def test_both_extreme_negative(self):
        """Code = -4 (100₂), Doppler = -16 (10000₂)."""
        # byte = 10000_100 = 0x84
        code, doppler = decode_offsets_msb(0b10000_100)
        assert code == -4
        assert doppler == -16

    def test_both_max_positive(self):
        """Code = +3 (011₂), Doppler = +15 (01111₂)."""
        code, doppler = decode_offsets_msb(0b01111_011)
        assert code == 3
        assert doppler == 15

    def test_dnu_code_pattern(self):
        """CodeOffsetMSB==-4 is the DNU marker for Type2 pseudorange."""
        code, _ = decode_offsets_msb(0b00000_100)
        assert code == -4

    def test_dnu_doppler_pattern(self):
        """DopplerOffsetMSB==-16 is the DNU marker for Type2 Doppler."""
        _, doppler = decode_offsets_msb(0b10000_000)
        assert doppler == -16


# ===================================================================
# pr2_m — RefGuide-4.14.0, p.263
# PR_type2 = PR_type1 + (CodeOffsetMSB * 65536 + CodeOffsetLSB) * 0.001
# DNU: CodeOffsetMSB == -4 AND CodeOffsetLSB == 0
# ===================================================================


class TestPr2M:
    """Type2 pseudorange from Type1 base + offset."""

    def test_dnu_returns_nan(self):
        assert math.isnan(pr2_m(_PR_M, code_offset_msb=-4, code_offset_lsb=0))

    def test_not_dnu_when_lsb_nonzero(self):
        assert not math.isnan(pr2_m(_PR_M, code_offset_msb=-4, code_offset_lsb=1))

    def test_zero_offset(self):
        """Zero offset means Type2 == Type1."""
        assert abs(pr2_m(_PR_M, 0, 0) - _PR_M) < 1e-6

    def test_positive_offset(self):
        """CodeOffsetMSB=1, CodeOffsetLSB=0 → offset = 65536 * 0.001 = 65.536 m."""
        assert abs(pr2_m(_PR_M, 1, 0) - (_PR_M + 65.536)) < 1e-3

    def test_negative_offset(self):
        """CodeOffsetMSB=-1, CodeOffsetLSB=0 → offset = -65.536 m."""
        assert abs(pr2_m(_PR_M, -1, 0) - (_PR_M - 65.536)) < 1e-3


# ===================================================================
# doppler2_hz — RefGuide-4.14.0, p.263
# D_type2 = D_type1 * (freq_type2 / freq_type1)
#          + (DopplerOffsetMSB * 65536 + DopplerOffsetLSB) * 1e-4
# DNU: DopplerOffsetMSB == -16 AND DopplerOffsetLSB == 0
# ===================================================================

_L2_HZ = 1227.60e6


class TestDoppler2Hz:
    """Type2 Doppler from Type1 base and differential offset."""

    def test_dnu_returns_nan(self):
        assert math.isnan(doppler2_hz(1000.0, -16, 0, _L2_HZ, _L1_HZ))

    def test_not_dnu_when_lsb_nonzero(self):
        assert not math.isnan(doppler2_hz(1000.0, -16, 1, _L2_HZ, _L1_HZ))

    def test_same_frequency_zero_offset(self):
        """Same freq, zero offset → D_type2 == D_type1."""
        assert abs(doppler2_hz(1500.0, 0, 0, _L1_HZ, _L1_HZ) - 1500.0) < 1e-6

    def test_frequency_ratio_scaling(self):
        """L2/L1 frequency ratio should scale the Doppler.

        alpha = 1227.60 / 1575.42 ≈ 0.7792
        D_type2 = 1000 * 0.7792 + 0 = 779.2 Hz (approx)
        """
        expected = 1000.0 * (1227.60 / 1575.42)
        assert abs(doppler2_hz(1000.0, 0, 0, _L2_HZ, _L1_HZ) - expected) < 0.01


# ===================================================================
# glonass_freq_hz — RefGuide-4.14.0, Table 4.1.10, p.256
# G1 [MHz] = 1602.000 + (FreqNr - 8) * 9/16
# G2 [MHz] = 1246.000 + (FreqNr - 8) * 7/16
# FreqNr = GLONASS frequency number + 8; valid range 1..21 (-7..+13)
# ===================================================================


class TestGlonassFreqHz:
    """GLONASS FDMA carrier frequency computation, in Hz."""

    @pytest.mark.parametrize(
        "sig_num,freq_nr,expected_mhz",
        [
            (8, 8, 1602.000),
            (8, 1, 1602.000 - 7 * 9 / 16),  # 1598.0625
            (8, 21, 1602.000 + 13 * 9 / 16),  # 1609.3125
            (9, 8, 1602.000),  # L1P: G1 band too
            (10, 8, 1246.000),
            (10, 1, 1246.000 - 7 * 7 / 16),  # 1242.9375
            (10, 21, 1246.000 + 13 * 7 / 16),  # 1251.6875
            (11, 8, 1246.000),  # L2CA: G2 band too
        ],
    )
    def test_frequency(self, sig_num, freq_nr, expected_mhz):
        assert abs(glonass_freq_hz(sig_num, freq_nr) - expected_mhz * 1e6) < 1e-3

    def test_array_input(self):
        np.testing.assert_allclose(
            glonass_freq_hz([8, 10], [9, 9]), [1602.5625e6, 1246.4375e6]
        )

    def test_non_fdma_raises(self):
        """Non-FDMA signal numbers (0-7, 12+) must raise ValueError."""
        with pytest.raises(ValueError, match="not a GLONASS FDMA signal"):
            glonass_freq_hz(signal_num=0, freq_nr=8)

    def test_non_fdma_glonass_l3_raises(self):
        """GLONASS L3 CDMA (signal 12) is not FDMA — must raise."""
        with pytest.raises(ValueError, match="not a GLONASS FDMA signal"):
            glonass_freq_hz(signal_num=12, freq_nr=8)
