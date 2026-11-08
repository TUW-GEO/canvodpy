"""Tests for GNSS signal mapping system."""

import pytest

from canvod.readers.gnss_specs.bands import Bands
from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper


class TestSignalIDMapper:
    """Test SignalIDMapper class."""

    def test_initialization(self):
        """Test SignalIDMapper can be initialized."""
        mapper = SignalIDMapper(aggregate_glonass_fdma=True)

        assert mapper is not None
        assert mapper.aggregate_glonass_fdma is True
        assert mapper.SYSTEM_BANDS is not None
        assert mapper.BAND_PROPERTIES is not None
        assert mapper.OVERLAPPING_GROUPS is not None

    def test_system_bands_coverage(self):
        """Test all GNSS systems have band mappings."""
        mapper = SignalIDMapper()

        expected_systems = ["G", "E", "R", "C", "I", "S", "J"]
        for system in expected_systems:
            assert system in mapper.SYSTEM_BANDS, f"Missing system: {system}"
            assert len(mapper.SYSTEM_BANDS[system]) > 0

    def test_get_band_frequency(self):
        """Test band frequency retrieval."""
        mapper = SignalIDMapper()

        # GPS L1
        freq = mapper.get_band_frequency("L1")
        assert freq == pytest.approx(1575.42)

        # GPS L2
        freq = mapper.get_band_frequency("L2")
        assert freq == pytest.approx(1227.60)

        # GPS L5
        freq = mapper.get_band_frequency("L5")
        assert freq == pytest.approx(1176.45)

        # Galileo E1
        freq = mapper.get_band_frequency("E1")
        assert freq == pytest.approx(1575.42)

    def test_get_band_bandwidth(self):
        """Test band bandwidth retrieval."""
        mapper = SignalIDMapper()

        # GPS L1
        bw = mapper.get_band_bandwidth("L1")
        assert bw == pytest.approx(30.69)

        # GPS L5
        bw = mapper.get_band_bandwidth("L5")
        assert bw == pytest.approx(24.0)

        # Galileo E1
        bw = mapper.get_band_bandwidth("E1")
        assert bw == pytest.approx(24.552)

    def test_get_overlapping_group(self):
        """Test overlapping group identification."""
        mapper = SignalIDMapper()

        # L1/E1/B1I are in same group (~1575 MHz)
        group_l1 = mapper.get_overlapping_group("L1")
        group_e1 = mapper.get_overlapping_group("E1")
        group_b1i = mapper.get_overlapping_group("B1I")

        assert group_l1 is not None
        assert group_l1 == group_e1
        assert group_l1 == group_b1i

        # L5/E5a are in same group (~1176 MHz)
        group_l5 = mapper.get_overlapping_group("L5")
        group_e5a = mapper.get_overlapping_group("E5a")

        assert group_l5 is not None
        assert group_l5 == group_e5a

    def test_unknown_band_returns_none(self):
        """Test unknown band returns None for frequency/bandwidth/group."""
        mapper = SignalIDMapper()

        assert mapper.get_band_frequency("UnknownBand9") is None
        assert mapper.get_band_bandwidth("UnknownBand9") is None
        assert mapper.get_overlapping_group("UnknownBand9") is None


class TestBands:
    """Test Bands class."""

    def test_initialization(self):
        """Test Bands can be initialized."""
        bands = Bands(aggregate_glonass_fdma=True)

        assert bands is not None
        assert bands.BAND_PROPERTIES is not None
        assert bands.SYSTEM_BANDS is not None
        assert bands.OVERLAPPING_GROUPS is not None

    def test_band_properties_structure(self):
        """Test BAND_PROPERTIES has correct structure."""
        bands = Bands()

        # Check L1 band exists
        assert "L1" in bands.BAND_PROPERTIES
        l1_props = bands.BAND_PROPERTIES["L1"]

        assert "freq" in l1_props
        assert "bandwidth" in l1_props
        assert "system" in l1_props

        assert isinstance(l1_props["freq"], (int, float))
        assert isinstance(l1_props["bandwidth"], (int, float))
        # System can be 'G' (GPS), 'J' (QZSS), or 'S' (SBAS) - all use L1
        assert l1_props["system"] in ["G", "J", "S"]

    def test_system_bands_structure(self):
        """Test SYSTEM_BANDS has correct structure."""
        bands = Bands()

        # Check GPS
        assert "G" in bands.SYSTEM_BANDS
        gps_bands = bands.SYSTEM_BANDS["G"]

        assert "1" in gps_bands  # L1
        assert "2" in gps_bands  # L2
        assert "5" in gps_bands  # L5

        assert gps_bands["1"] == "L1"
        assert gps_bands["2"] == "L2"
        assert gps_bands["5"] == "L5"

    def test_overlapping_groups_structure(self):
        """Test OVERLAPPING_GROUPS has correct structure."""
        bands = Bands()

        # Find group containing L1
        l1_group = None
        for group, band_list in bands.OVERLAPPING_GROUPS.items():
            if "L1" in band_list:
                l1_group = band_list
                break

        assert l1_group is not None
        assert "L1" in l1_group
        assert "E1" in l1_group  # Galileo E1 overlaps with L1

    def test_all_systems_present(self):
        """Test all GNSS systems are present."""
        bands = Bands()

        expected_systems = ["G", "E", "R", "C", "I", "S", "J"]
        for system in expected_systems:
            assert system in bands.SYSTEM_BANDS

    def test_glonass_fdma_aggregation(self):
        """Test GLONASS FDMA aggregation option."""
        # With aggregation
        bands_agg = Bands(aggregate_glonass_fdma=True)
        assert "R" in bands_agg.SYSTEM_BANDS
        r_bands_agg = bands_agg.SYSTEM_BANDS["R"]
        assert "1" in r_bands_agg  # G1 should be present
        assert "2" in r_bands_agg  # G2 should be present

        # Without aggregation
        bands_no_agg = Bands(aggregate_glonass_fdma=False)
        r_bands_no_agg = bands_no_agg.SYSTEM_BANDS["R"]
        assert r_bands_no_agg["1"] == "G1_FDMA"
        assert r_bands_no_agg["2"] == "G2_FDMA"


class TestConstellations:
    """Test constellation classes."""

    def test_gps_initialization(self):
        """Test GPS constellation can be initialized."""
        gps = GPS()

        assert gps.constellation == "GPS"
        assert len(gps.svs) > 0
        assert gps.svs[0].startswith("G")
        assert len(gps.BANDS) > 0
        assert "L1" in gps.BAND_PROPERTIES

    def test_gps_static_svs(self):
        """Test GPS has static SV list."""
        gps = GPS()

        assert len(gps.svs) == 32
        assert "G01" in gps.svs
        assert "G32" in gps.svs

    def test_galileo_initialization(self):
        """Test Galileo constellation can be initialized."""
        galileo = GALILEO()

        assert galileo.constellation == "GALILEO"
        assert "E1" in galileo.BAND_PROPERTIES
        assert len(galileo.BANDS) > 0

    def test_glonass_initialization(self):
        """Test GLONASS constellation can be initialized."""
        glonass = GLONASS(aggregate_fdma=True)

        # GLONASS has custom __init__ and doesn't set constellation attribute
        assert len(glonass.svs) == 24
        assert glonass.svs[0].startswith("R")
        assert glonass.aggregate_fdma is True

    def test_beidou_initialization(self):
        """Test BeiDou constellation can be initialized."""
        beidou = BEIDOU()

        assert beidou.constellation == "BEIDOU"
        assert "B1I" in beidou.BAND_PROPERTIES
        assert len(beidou.BANDS) > 0

    def test_irnss_initialization(self):
        """Test IRNSS constellation can be initialized."""
        irnss = IRNSS()

        assert irnss.constellation == "IRNSS"
        assert "L5" in irnss.BAND_PROPERTIES
        assert "S" in irnss.BAND_PROPERTIES

    def test_qzss_initialization(self):
        """Test QZSS constellation can be initialized."""
        qzss = QZSS()

        assert qzss.constellation == "QZSS"
        assert "L1" in qzss.BAND_PROPERTIES
        assert "L6" in qzss.BAND_PROPERTIES  # Unique to QZSS

    def test_sbas_initialization(self):
        """Test SBAS constellation can be initialized."""
        sbas = SBAS()

        assert sbas.constellation == "SBAS"
        assert len(sbas.svs) > 0
        assert sbas.svs[0].startswith("S")


class TestIntegration:
    """Integration tests for signal mapping with RINEX reader."""

    def test_overlapping_group_filtering(self):
        """Test overlapping group identification for filtering."""
        mapper = SignalIDMapper()

        # L1 and E1 should be in same overlapping group
        group_l1 = mapper.get_overlapping_group("L1")
        group_e1 = mapper.get_overlapping_group("E1")

        assert group_l1 == group_e1  # Should be in same group

    def test_frequency_consistency(self):
        """Test frequency values are consistent across systems."""
        mapper = SignalIDMapper()

        # L1 and E1 should have same frequency (1575.42 MHz)
        freq_l1 = mapper.get_band_frequency("L1")
        freq_e1 = mapper.get_band_frequency("E1")

        assert freq_l1 == freq_e1
        assert freq_l1 == pytest.approx(1575.42)
