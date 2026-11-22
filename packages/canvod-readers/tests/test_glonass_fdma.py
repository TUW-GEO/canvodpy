"""GLONASS FDMA carrier frequencies and frequency channels."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from canvod.readers.gnss_specs import (
    SatelliteCatalog,
    glonass_carrier_frequency_hz,
    glonass_channel,
    glonass_fdma_frequency_hz,
)
from canvod.readers.gnss_specs.constellations import GLONASS
from canvod.readers.gnss_specs.satellite_catalog import _FALLBACK_SNX
from canvod.readers.sbf._scaling import glonass_freq_hz


@pytest.fixture(scope="module")
def bundled_catalog() -> SatelliteCatalog:
    """The IGS satellite metadata shipped with the package (no network)."""
    return SatelliteCatalog.from_file(_FALLBACK_SNX)


class TestFdmaFrequency:
    # GLONASS FDMA ICD 5.1, Table 3.1 (K = -7, 0, +6)
    @pytest.mark.parametrize(
        ("band", "channel", "mhz"),
        [
            ("G1", -7, 1598.0625),
            ("G1", 0, 1602.0),
            ("G1", 6, 1605.375),
            ("G2", -7, 1242.9375),
            ("G2", 0, 1246.0),
            ("G2", 6, 1248.625),
        ],
    )
    def test_icd_values(self, band: str, channel: int, mhz: float):
        assert float(glonass_fdma_frequency_hz(band, channel)) == mhz * 1e6

    def test_array_input(self):
        np.testing.assert_array_equal(
            glonass_fdma_frequency_hz("G1", [-7, 0, 12]),
            [1598.0625e6, 1602.0e6, 1608.75e6],
        )

    @pytest.mark.parametrize("band", ["G3", "G1a", "L1", "1"])
    def test_refuses_non_fdma_band(self, band: str):
        with pytest.raises(ValueError, match="not a GLONASS FDMA band"):
            glonass_fdma_frequency_hz(band, 0)

    @pytest.mark.parametrize("channel", [-8, 13, [0, 13]])
    def test_refuses_channel_out_of_range(self, channel):
        with pytest.raises(ValueError, match=r"outside -7\.\.\.12"):
            glonass_fdma_frequency_hz("G1", channel)

    def test_refuses_non_integer_channel(self):
        with pytest.raises(ValueError, match="integers"):
            glonass_fdma_frequency_hz("G1", 0.5)


class TestSameValuesEverywhere:
    """The SBF decoder and the aggregated bands use the same plan."""

    @pytest.mark.parametrize("channel", range(-7, 13))
    def test_sbf_matches(self, channel: int):
        freq_nr = channel + 8  # SBF FreqNr has an offset of 8
        assert glonass_freq_hz(8, freq_nr) == glonass_fdma_frequency_hz("G1", channel)
        assert glonass_freq_hz(11, freq_nr) == glonass_fdma_frequency_hz("G2", channel)

    def test_aggregated_bands_unchanged(self):
        props = GLONASS.AGGR_G1_G2_BAND_PROPERTIES
        assert props["G1"]["freq"].to("MHz").magnitude == 1601.71875
        assert props["G1"]["bandwidth"].to("MHz").magnitude == pytest.approx(8.3345)
        assert props["G2"]["freq"].to("MHz").magnitude == 1245.78125
        assert props["G2"]["bandwidth"].to("MHz").magnitude == pytest.approx(6.7095)

    def test_fdma_placeholders_unchanged(self):
        props = GLONASS(aggregate_fdma=False).BAND_PROPERTIES
        assert props["G1_FDMA"]["freq"].to("MHz").magnitude == 1602.0
        assert props["G2_FDMA"]["freq"].to("MHz").magnitude == 1246.0


class TestChannelOnDate:
    def test_slot_reassigned_satellite(self, bundled_catalog: SatelliteCatalog):
        # R25 was SVN R807 (channel -5) on 2023-01-15; the static table has
        # no slot 25 at all.
        assert glonass_channel("R25", date(2023, 1, 15), bundled_catalog) == -5

    def test_carrier_frequency(self, bundled_catalog: SatelliteCatalog):
        day = date(2023, 1, 15)
        assert glonass_carrier_frequency_hz("R25", "G1", day, bundled_catalog) == (
            1602.0e6 - 5 * 0.5625e6
        )
        assert glonass_carrier_frequency_hz("R25", "G2", day, bundled_catalog) == (
            1246.0e6 - 5 * 0.4375e6
        )

    def test_unknown_slot_gives_none(self, bundled_catalog: SatelliteCatalog):
        assert glonass_channel("R99", date(2023, 1, 15), bundled_catalog) is None
        assert (
            glonass_carrier_frequency_hz(
                "R99", "G1", date(2023, 1, 15), bundled_catalog
            )
            is None
        )

    def test_refuses_other_systems(self, bundled_catalog: SatelliteCatalog):
        with pytest.raises(ValueError, match="not a GLONASS satellite"):
            glonass_channel("G01", date(2023, 1, 15), bundled_catalog)

    def test_refuses_wrong_band_before_lookup(self, bundled_catalog: SatelliteCatalog):
        with pytest.raises(ValueError, match="not a GLONASS FDMA band"):
            glonass_carrier_frequency_hz(
                "R99", "G3", date(2023, 1, 15), bundled_catalog
            )


class TestStaticTableDeprecated:
    def test_get_channel_used_by_sv_warns_once(self):
        glonass = GLONASS()
        with pytest.warns(FutureWarning, match="glonass_channel") as record:
            glonass.get_channel_used_by_SV("R01")
        assert len([w for w in record if w.category is FutureWarning]) == 1

    def test_glonass_slots_channels_warns(self):
        with pytest.warns(FutureWarning, match="glonass_channel"):
            _ = GLONASS().glonass_slots_channels

    def test_channel_file_argument_warns(self):
        from canvod.readers.gnss_specs.constellations import _GLONASS_CHANNELS_TXT

        with pytest.warns(FutureWarning, match="glonass_channel"):
            GLONASS(glonass_channel_pth=_GLONASS_CHANNELS_TXT)
