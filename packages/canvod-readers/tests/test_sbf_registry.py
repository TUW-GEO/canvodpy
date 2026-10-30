"""Unit tests for SBF static lookup tables (_registry.py).

All expected values are verified against the Septentrio AsteRx SB3 ProBase
Firmware v4.14.0 Reference Guide:
- Table 4.1.9 (p.255): SVID-to-system/PRN mapping
- Table 4.1.10 (p.256): Signal type definitions

These are pure lookup-table tests — no test data files required.
"""

from __future__ import annotations

import pytest

from canvod.readers.sbf._registry import (
    FDMA_SIGNAL_NUMS,
    SIGNAL_TABLE,
    SignalDef,
    decode_svid,
    svid_to_sv,
)

# ===================================================================
# decode_svid — RefGuide-4.14.0, Table 4.1.9, p.255
# ===================================================================


class TestDecodeSvid:
    """SVID-to-(system, PRN) mapping against Table 4.1.9."""

    # --- GPS: SVID 1-37, PRN = SVID ---

    @pytest.mark.parametrize(
        "svid,expected_system,expected_prn",
        [
            (1, "G", 1),  # GPS first
            (32, "G", 32),  # GPS last nominal
            (37, "G", 37),  # GPS last extended
        ],
    )
    def test_gps(self, svid, expected_system, expected_prn):
        system, prn = decode_svid(svid)
        assert system == expected_system
        assert prn == expected_prn

    # --- GLONASS: SVID 38-61 (R01-R24), 62 (R00 unknown), 63-68 (R25-R30) ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (38, 1),  # R01 = SVID - 37
            (61, 24),  # R24 = SVID - 37
            (63, 25),  # R25 = SVID - 38
            (68, 30),  # R30 = SVID - 38
        ],
    )
    def test_glonass_slots(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "R"
        assert prn == expected_prn

    def test_glonass_unknown_slot(self):
        """SVID 62: GLONASS with unknown slot → R00."""
        system, prn = decode_svid(62)
        assert system == "R"
        assert prn == 0  # unknown slot encoded as PRN=0

    # --- Galileo: SVID 71-106, PRN = SVID - 70 ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (71, 1),  # E01
            (106, 36),  # E36
        ],
    )
    def test_galileo(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "E"
        assert prn == expected_prn

    # --- L-Band MSS: SVID 107-119 ---

    def test_lband_mss(self):
        system, _ = decode_svid(107)
        assert system == "L"

    # --- SBAS: SVID 120-140 (PRN = SVID), 198-215 (PRN = SVID - 57) ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (120, 120),  # S120 (PRN = SVID)
            (140, 140),  # S140
            (198, 141),  # S141 = SVID - 57
            (215, 158),  # S158 = SVID - 57
        ],
    )
    def test_sbas(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "S"
        assert prn == expected_prn

    # --- SBAS names: RINEX Snn, nn = PRN - 100 (RINEX 3.04, Section 8.4) ---

    @pytest.mark.parametrize(
        "svid,expected_sv",
        [
            (120, "S20"),  # PRN 120
            (123, "S23"),  # PRN 123 (EGNOS)
            (140, "S40"),  # PRN 140
            (198, "S41"),  # PRN 141
            (215, "S58"),  # PRN 158
        ],
    )
    def test_sbas_sv_name_follows_rinex(self, svid, expected_sv):
        assert svid_to_sv(svid) == expected_sv

    @pytest.mark.parametrize(
        "svid,expected_sv",
        [(1, "G01"), (71, "E01"), (141, "C01"), (181, "J01"), (245, "C63")],
    )
    def test_sv_name_of_other_systems(self, svid, expected_sv):
        assert svid_to_sv(svid) == expected_sv

    # --- BeiDou: SVID 141-180 (C01-C40), 223-245 (C41-C63) ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (141, 1),  # C01 = SVID - 140
            (180, 40),  # C40 = SVID - 140
            (223, 41),  # C41 = SVID - 182
            (245, 63),  # C63 = SVID - 182
        ],
    )
    def test_beidou(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "C"
        assert prn == expected_prn

    # --- QZSS: SVID 181-187 (J01-J07) ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (181, 1),  # J01 = SVID - 180
            (187, 7),  # J07 = SVID - 180
        ],
    )
    def test_qzss(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "J"
        assert prn == expected_prn

    # --- NavIC/IRNSS: SVID 191-197 (I01-I07), 216-222 (I08-I14) ---

    @pytest.mark.parametrize(
        "svid,expected_prn",
        [
            (191, 1),  # I01 = SVID - 190
            (197, 7),  # I07 = SVID - 190
            (216, 8),  # I08 = SVID - 208
            (222, 14),  # I14 = SVID - 208
        ],
    )
    def test_navic(self, svid, expected_prn):
        system, prn = decode_svid(svid)
        assert system == "I"
        assert prn == expected_prn

    # --- Unknown SVIDs ---

    def test_unknown_svid_returns_question_mark(self):
        """SVIDs outside all defined ranges return ("?", svid)."""
        system, prn = decode_svid(0)
        assert system == "?"
        assert prn == 0

    def test_unknown_svid_in_gap(self):
        """SVID 69 is between GLONASS (63-68) and Galileo (71-106)."""
        system, prn = decode_svid(69)
        assert system == "?"

    def test_svid_above_max(self):
        system, prn = decode_svid(250)
        assert system == "?"
        assert prn == 250

    # --- Boundary completeness ---

    def test_all_gps_svids_decode_to_g(self):
        for svid in range(1, 38):
            system, _ = decode_svid(svid)
            assert system == "G", f"SVID {svid} should be GPS"

    def test_all_galileo_svids_decode_to_e(self):
        for svid in range(71, 107):
            system, prn = decode_svid(svid)
            assert system == "E", f"SVID {svid} should be Galileo"
            assert prn == svid - 70


# ===================================================================
# SIGNAL_TABLE — RefGuide-4.14.0, Table 4.1.10, p.256
# ===================================================================


class TestSignalTable:
    """Signal type table completeness and correctness."""

    def test_signal_table_is_dict(self):
        assert isinstance(SIGNAL_TABLE, dict)

    def test_signal_table_not_empty(self):
        assert len(SIGNAL_TABLE) > 0

    def test_all_entries_are_signal_def(self):
        for num, sdef in SIGNAL_TABLE.items():
            assert isinstance(sdef, SignalDef), f"Signal {num} is not SignalDef"

    def test_signal_number_matches_key(self):
        """Each SignalDef.number must match its dict key."""
        for num, sdef in SIGNAL_TABLE.items():
            assert sdef.number == num, f"Key {num} != SignalDef.number {sdef.number}"

    # --- Verify specific signals from Table 4.1.10 ---

    @pytest.mark.parametrize(
        "sig_num,expected_type,expected_sys,expected_rinex,expected_band",
        [
            (0, "L1CA", "G", "1C", "L1"),
            (1, "L1P", "G", "1W", "L1"),
            (2, "L2P", "G", "2W", "L2"),
            (3, "L2C", "G", "2L", "L2"),
            (4, "L5", "G", "5Q", "L5"),
            (5, "L1C", "G", "1L", "L1"),
            (6, "L1CA", "J", "1C", "L1"),  # QZSS
            (7, "L2C", "J", "2L", "L2"),
            (8, "L1CA", "R", "1C", "G1"),  # GLONASS FDMA
            (9, "L1P", "R", "1P", "G1"),
            (10, "L2P", "R", "2P", "G2"),
            (11, "L2CA", "R", "2C", "G2"),
            (12, "L3", "R", "3Q", "G3"),  # GLONASS CDMA
            (13, "B1C", "C", "1P", "B1C"),  # BeiDou
            (14, "B2a", "C", "5P", "B2a"),
            (15, "L5", "I", "5A", "L5"),  # NavIC
            (17, "E1", "E", "1C", "E1"),  # Galileo
            (19, "E6", "E", "6C", "E6"),
            (20, "E5a", "E", "5Q", "E5a"),
            (21, "E5b", "E", "7Q", "E5b"),
            (22, "E5", "E", "8Q", "E5"),  # AltBOC
            (24, "L1CA", "S", "1C", "L1"),  # SBAS
            (25, "L5", "S", "5I", "L5"),
            (26, "L5", "J", "5Q", "L5"),  # QZSS L5
            (27, "L6", "J", "6E", "L6"),
            (28, "B1I", "C", "2I", "B1I"),  # BeiDou legacy
            (29, "B2I", "C", "7I", "B2I"),
            (30, "B3I", "C", "6I", "B3I"),
            (32, "L1C", "J", "1L", "L1"),  # QZSS L1C
            (33, "L1S", "J", "1Z", "L1"),  # QZSS SLAS
            (34, "B2b", "C", "7D", "B2b"),  # BeiDou B2b
        ],
    )
    def test_signal_definition(
        self, sig_num, expected_type, expected_sys, expected_rinex, expected_band
    ):
        sdef = SIGNAL_TABLE[sig_num]
        assert sdef.signal_type == expected_type, (
            f"Signal {sig_num}: type={sdef.signal_type}, expected={expected_type}"
        )
        assert sdef.system == expected_sys, (
            f"Signal {sig_num}: system={sdef.system}, expected={expected_sys}"
        )
        assert sdef.rinex_obs == expected_rinex, (
            f"Signal {sig_num}: rinex_obs={sdef.rinex_obs}, expected={expected_rinex}"
        )
        assert sdef.band == expected_band, (
            f"Signal {sig_num}: band={sdef.band}, expected={expected_band}"
        )

    # --- CN0 offset flags ---

    def test_only_signals_1_and_2_have_no_offset(self):
        """Per p.261: only GPS L1P (sig 1) and GPS L2P (sig 2) omit +10 dB."""
        for num, sdef in SIGNAL_TABLE.items():
            if num in (1, 2):
                assert sdef.cn0_no_offset is True, (
                    f"Signal {num} should have cn0_no_offset=True"
                )
            else:
                assert sdef.cn0_no_offset is False, (
                    f"Signal {num} should have cn0_no_offset=False"
                )

    # --- Frequency correctness ---

    def test_gps_l1_frequency(self):
        """GPS L1 carrier = 1575.42 MHz (IS-GPS-200)."""
        sdef = SIGNAL_TABLE[0]  # L1CA
        assert abs(sdef.freq.to("MHz").magnitude - 1575.42) < 0.01

    def test_gps_l2_frequency(self):
        """GPS L2 carrier = 1227.60 MHz."""
        sdef = SIGNAL_TABLE[2]  # L2P
        assert abs(sdef.freq.to("MHz").magnitude - 1227.60) < 0.01

    def test_gps_l5_frequency(self):
        """GPS L5 carrier = 1176.45 MHz."""
        sdef = SIGNAL_TABLE[4]  # L5
        assert abs(sdef.freq.to("MHz").magnitude - 1176.45) < 0.01

    def test_galileo_e1_frequency(self):
        """Galileo E1 carrier = 1575.42 MHz (same as GPS L1)."""
        sdef = SIGNAL_TABLE[17]
        assert abs(sdef.freq.to("MHz").magnitude - 1575.42) < 0.01

    def test_galileo_e5a_frequency(self):
        """Galileo E5a carrier = 1176.45 MHz."""
        sdef = SIGNAL_TABLE[20]
        assert abs(sdef.freq.to("MHz").magnitude - 1176.45) < 0.01

    def test_galileo_e5b_frequency(self):
        """Galileo E5b carrier = 1207.14 MHz."""
        sdef = SIGNAL_TABLE[21]
        assert abs(sdef.freq.to("MHz").magnitude - 1207.14) < 0.01

    def test_galileo_e6_frequency(self):
        """Galileo E6 carrier = 1278.75 MHz."""
        sdef = SIGNAL_TABLE[19]
        assert abs(sdef.freq.to("MHz").magnitude - 1278.75) < 0.01

    def test_galileo_e5_altboc_frequency(self):
        """Galileo E5 AltBOC carrier = 1191.795 MHz."""
        sdef = SIGNAL_TABLE[22]
        assert abs(sdef.freq.to("MHz").magnitude - 1191.795) < 0.01

    def test_beidou_b1i_frequency(self):
        """BeiDou B1I carrier = 1561.098 MHz."""
        sdef = SIGNAL_TABLE[28]
        assert abs(sdef.freq.to("MHz").magnitude - 1561.098) < 0.01

    def test_beidou_b2i_frequency(self):
        """BeiDou B2I carrier = 1207.14 MHz (same as B2b)."""
        sdef = SIGNAL_TABLE[29]
        assert abs(sdef.freq.to("MHz").magnitude - 1207.14) < 0.01

    def test_beidou_b3i_frequency(self):
        """BeiDou B3I carrier = 1268.52 MHz."""
        sdef = SIGNAL_TABLE[30]
        assert abs(sdef.freq.to("MHz").magnitude - 1268.52) < 0.01

    def test_beidou_b1c_frequency(self):
        """BeiDou B1C carrier = 1575.42 MHz."""
        sdef = SIGNAL_TABLE[13]
        assert abs(sdef.freq.to("MHz").magnitude - 1575.42) < 0.01

    def test_glonass_l3_cdma_frequency(self):
        """GLONASS L3 CDMA carrier = 1202.025 MHz (fixed freq)."""
        sdef = SIGNAL_TABLE[12]
        assert abs(sdef.freq.to("MHz").magnitude - 1202.025) < 0.01

    # --- FDMA signals have freq=None ---

    def test_glonass_fdma_freq_is_none(self):
        """GLONASS FDMA signals (8-11) must have freq=None."""
        for sig_num in (8, 9, 10, 11):
            sdef = SIGNAL_TABLE[sig_num]
            assert sdef.freq is None, (
                f"Signal {sig_num} ({sdef.signal_type}) should have freq=None "
                f"(FDMA — use glonass_freq_hz())"
            )

    def test_fdma_signal_nums_set(self):
        """FDMA_SIGNAL_NUMS constant must match signals 8-11."""
        assert FDMA_SIGNAL_NUMS == frozenset({8, 9, 10, 11})

    # --- Reserved signals absent ---

    def test_reserved_signals_absent(self):
        """Reserved signal numbers must not appear in the table."""
        reserved = {16, 18, 31, 35, 36, 37}
        for num in reserved:
            assert num not in SIGNAL_TABLE, (
                f"Reserved signal {num} should not be in SIGNAL_TABLE"
            )

    # --- L-Band MSS ---

    def test_lband_mss_freq_is_none(self):
        """L-Band MSS (signal 23) has beam-specific freq → None."""
        sdef = SIGNAL_TABLE[23]
        assert sdef.freq is None
        assert sdef.system == "L"
