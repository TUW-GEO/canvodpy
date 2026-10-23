"""Tests for canvod.readers.gnss_specs.bands and constellations modules."""

import pytest

from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    OBS_TYPE_PATTERN,
    QZSS,
    SBAS,
    SV_PATTERN,
    ConstellationBase,
)

# ---------------------------------------------------------------------------
# SV / observation type regex patterns
# ---------------------------------------------------------------------------


class TestPatterns:
    """Tests for pre-compiled regex patterns."""

    @pytest.mark.parametrize("sv", ["G01", "R12", "E25", "C03", "J01", "S20", "I05"])
    def test_sv_pattern_valid(self, sv):
        assert SV_PATTERN.match(sv) is not None

    @pytest.mark.parametrize("sv", ["X01", "GG1", "G1", "G001", "", "g01"])
    def test_sv_pattern_invalid(self, sv):
        assert SV_PATTERN.match(sv) is None

    @pytest.mark.parametrize("obs", ["L1C", "C5X", "S1C", "D2P"])
    def test_obs_type_pattern_valid(self, obs):
        assert OBS_TYPE_PATTERN.match(obs) is not None


# ---------------------------------------------------------------------------
# GPS
# ---------------------------------------------------------------------------


class TestGPS:
    """Tests for GPS constellation."""

    def test_init(self):
        gps = GPS()
        assert gps.constellation == "GPS"

    def test_static_svs(self):
        gps = GPS()
        assert len(gps.svs) == 32
        assert gps.svs[0] == "G01"
        assert gps.svs[-1] == "G32"

    def test_bands(self):
        assert "1" in GPS.BANDS
        assert "2" in GPS.BANDS
        assert "5" in GPS.BANDS
        assert GPS.BANDS["1"] == "L1"

    def test_band_properties(self):
        assert "L1" in GPS.BAND_PROPERTIES
        assert "L2" in GPS.BAND_PROPERTIES
        assert "L5" in GPS.BAND_PROPERTIES

        l1_freq = GPS.BAND_PROPERTIES["L1"]["freq"]
        assert l1_freq.magnitude == pytest.approx(1575.42)


# ---------------------------------------------------------------------------
# GALILEO
# ---------------------------------------------------------------------------


class TestGALILEO:
    """Tests for Galileo constellation."""

    def test_init(self):
        gal = GALILEO()
        assert gal.constellation == "GALILEO"

    def test_static_svs(self):
        gal = GALILEO()
        assert gal.svs[0] == "E01"
        assert len(gal.svs) == 36

    def test_bands(self):
        assert "1" in GALILEO.BANDS
        assert GALILEO.BANDS["1"] == "E1"
        assert GALILEO.BANDS["5"] == "E5a"
        assert GALILEO.BANDS["7"] == "E5b"
        assert GALILEO.BANDS["8"] == "E5"

    def test_band_properties(self):
        e1 = GALILEO.BAND_PROPERTIES["E1"]
        assert e1["freq"].magnitude == pytest.approx(1575.42)
        assert e1["system"] == "E"


# ---------------------------------------------------------------------------
# GLONASS
# ---------------------------------------------------------------------------


class TestGLONASS:
    """Tests for GLONASS constellation."""

    def test_init_aggregate(self):
        glo = GLONASS(aggregate_fdma=True)
        assert "1" in glo.BANDS
        assert glo.BANDS["1"] == "G1"

    def test_init_non_aggregate(self):
        glo = GLONASS(aggregate_fdma=False)
        assert glo.BANDS["1"] == "G1_FDMA"

    def test_static_svs(self):
        glo = GLONASS()
        assert len(glo.svs) == 24
        assert glo.svs[0] == "R01"

    def test_channel_lookup(self):
        glo = GLONASS()
        # This should not raise (channel file is included with the package)
        ch = glo.get_channel_used_by_SV("R01")
        assert isinstance(ch, int)

    def test_glonass_slots_channels(self):
        glo = GLONASS()
        sc = glo.glonass_slots_channels
        assert isinstance(sc, dict)
        assert len(sc) > 0


# ---------------------------------------------------------------------------
# BEIDOU
# ---------------------------------------------------------------------------


class TestBEIDOU:
    """Tests for BeiDou constellation."""

    def test_init(self):
        bds = BEIDOU()
        assert bds.constellation == "BEIDOU"

    def test_static_svs(self):
        bds = BEIDOU()
        assert bds.svs[0] == "C01"
        assert len(bds.svs) == 63

    def test_bands(self):
        assert "2" in BEIDOU.BANDS
        assert BEIDOU.BANDS["2"] == "B1I"
        assert BEIDOU.BANDS["1"] == "B1C"

    def test_band_properties(self):
        b1i = BEIDOU.BAND_PROPERTIES["B1I"]
        assert b1i["freq"].magnitude == pytest.approx(1561.098)
        assert b1i["system"] == "C"


# ---------------------------------------------------------------------------
# SBAS
# ---------------------------------------------------------------------------


class TestSBAS:
    """Tests for SBAS constellation."""

    def test_init(self):
        sbas = SBAS()
        assert sbas.constellation == "SBAS"

    def test_static_svs(self):
        # Snn = PRN - 100 over the full two-digit range (RINEX 2.11 9.1,
        # RINEX 3.04 8.4), so real GEOs like EGNOS PRN 148 (S48) are kept.
        sbas = SBAS()
        assert sbas.svs[0] == "S01"
        assert sbas.svs[-1] == "S99"
        assert len(sbas.svs) == 99
        assert "S48" in sbas.svs

    def test_bands(self):
        assert SBAS.BANDS["1"] == "L1"
        assert SBAS.BANDS["5"] == "L5"


# ---------------------------------------------------------------------------
# IRNSS
# ---------------------------------------------------------------------------


class TestIRNSS:
    """Tests for IRNSS (NavIC) constellation."""

    def test_init(self):
        irnss = IRNSS()
        assert irnss.constellation == "IRNSS"

    def test_static_svs(self):
        irnss = IRNSS()
        assert irnss.svs[0] == "I01"
        assert len(irnss.svs) == 14

    def test_bands(self):
        assert IRNSS.BANDS["5"] == "L5"
        assert IRNSS.BANDS["9"] == "S"

    def test_s_band_frequency(self):
        s_band = IRNSS.BAND_PROPERTIES["S"]
        assert s_band["freq"].magnitude == pytest.approx(2492.028)


# ---------------------------------------------------------------------------
# QZSS
# ---------------------------------------------------------------------------


class TestQZSS:
    """Tests for QZSS constellation."""

    def test_init(self):
        qzss = QZSS()
        assert qzss.constellation == "QZSS"

    def test_static_svs(self):
        qzss = QZSS()
        assert len(qzss.svs) == 10
        assert qzss.svs[0] == "J01"

    def test_bands(self):
        assert QZSS.BANDS["6"] == "L6"

    def test_l6_frequency(self):
        l6 = QZSS.BAND_PROPERTIES["L6"]
        assert l6["freq"].magnitude == pytest.approx(1278.75)


# ---------------------------------------------------------------------------
# Bands registry
# ---------------------------------------------------------------------------


class TestBandsRegistry:
    """Tests for the Bands registry class."""

    def test_init_default(self):
        from canvod.readers.gnss_specs.bands import Bands

        bands = Bands()
        assert len(bands.BAND_PROPERTIES) > 0
        assert len(bands.SYSTEM_BANDS) == 7  # G, R, E, C, I, S, J

    def test_system_bands_mapping(self):
        from canvod.readers.gnss_specs.bands import Bands

        bands = Bands()
        assert "G" in bands.SYSTEM_BANDS
        assert "L1" in bands.SYSTEM_BANDS["G"].values()

    def test_overlapping_groups(self):
        from canvod.readers.gnss_specs.bands import Bands

        bands = Bands()
        assert "group_1" in bands.OVERLAPPING_GROUPS
        assert "L1" in bands.OVERLAPPING_GROUPS["group_1"]

    def test_strip_units(self):
        from canvod.readers.gnss_specs.bands import Bands

        raw = {"L1": {"freq": 1575.42 * UREG.MHz, "system": "G"}}
        stripped = Bands.strip_units(raw)
        assert isinstance(stripped["L1"]["freq"], float)
        assert stripped["L1"]["system"] == "G"

    def test_aggregate_vs_non_aggregate(self):
        from canvod.readers.gnss_specs.bands import Bands

        bands_agg = Bands(aggregate_glonass_fdma=True)
        bands_no_agg = Bands(aggregate_glonass_fdma=False)

        assert "G1" in bands_agg.OVERLAPPING_GROUPS.get("group_7", [])
        assert "G1_FDMA" in bands_no_agg.OVERLAPPING_GROUPS.get("group_7", [])


# ---------------------------------------------------------------------------
# ConstellationBase
# ---------------------------------------------------------------------------


class TestConstellationBase:
    """Test base class behaviour."""

    def test_can_instantiate_directly(self):
        """ConstellationBase is no longer abstract after removing freqs_lut."""
        cb = ConstellationBase(constellation="test", static_svs=["T01"])
        assert cb.constellation == "test"
        assert cb.svs == ["T01"]
