"""Tests for SatelliteCatalog IGS SINEX parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest

from canvod.readers.gnss_specs.satellite_catalog import (
    SatelliteCatalog,
    _extract_block,
    _parse_snx_epoch,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINI_SNX = dedent("""\
    %=SNX 2.02 IGS 25:001:00000 IGS 00:000:00000 00:000:00000 C 00000 0
    +SATELLITE/IDENTIFIER
    *SVN_ COSPAR ID SatCat Block__________ Comment__________________________________
    *
     G063 2011-036A  37753 GPS-IIF          Launched 2011-07-16; NAVSTAR 66
     G080 2024-242A  62339 GPS-IIIA         Launched 2024-12-17; NAVSTAR 83
     E210 2016-030B  41550 GAL-2            Launched 2016-05-24; GALILEO 13 (26A)
     R730 2009-070A  36111 GLO-M            Launched 2009-12-14; COSMOS 2456
    -SATELLITE/IDENTIFIER
    +SATELLITE/PRN
    *SVN_ Valid_From____ Valid_To______ PRN
    *
     G063 2011:197:42300 2024:103:00000 G01
     G049 2024:113:00000 2024:352:00000 G01
     G080 2024:352:00000 0000:000:00000 G01
     E210 2016:160:00000 0000:000:00000 E01
     R730 2010:061:00000 0000:000:00000 R01
    -SATELLITE/PRN
    +SATELLITE/TX_POWER
    *SVN_ Valid_From____ Valid_To______ P Comment
    *
     G063 2011:197:42300 0000:000:00000  240 GPS-IIF; [TX05]
     G080 2024:352:00000 0000:000:00000  300 GPS-IIIA; [TX13]
     E210 2016:160:00000 0000:000:00000  265 GAL-2; [TX06]
     R730 2010:061:00000 0000:000:00000   65 GLO-M; [TX02]
    -SATELLITE/TX_POWER
    +SATELLITE/MASS
    *SVN_ Valid_From____ Valid_To______ Mass_(kg)_ Comment
    *
     G063 2011:197:42300 0000:000:00000  1633.000  GPS-IIF; [MA04]
     G080 2024:352:00000 0000:000:00000  2161.000  GPS-III; [MA27]
    -SATELLITE/MASS
    +SATELLITE/FREQUENCY_CHANNEL
    *SVN_ Valid_From____ Valid_To______ chn Comment
    *
     R730 2010:061:00000 0000:000:00000   1 GLONASS; [FC04]
    -SATELLITE/FREQUENCY_CHANNEL
    +SATELLITE/PLANE
    *SVN_ Valid_From____ Valid_To______ P Slot__ Comment
    *
     G063 2011:199:00000 0000:000:00000 4 D2A    [PL01]
     G080 2024:352:00000 0000:000:00000 4 D2A    [PL01] January 1, 2025
    -SATELLITE/PLANE
    %ENDSNX
""")


@pytest.fixture
def mini_snx(tmp_path: Path) -> Path:
    """Write a minimal SNX file for testing."""
    p = tmp_path / "test_satellite_metadata.snx"
    p.write_text(MINI_SNX)
    return p


@pytest.fixture
def catalog(mini_snx: Path) -> SatelliteCatalog:
    return SatelliteCatalog.from_file(mini_snx)


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestParseSnxEpoch:
    def test_normal_epoch(self):
        assert _parse_snx_epoch("2024:352:00000") == date(2024, 12, 17)

    def test_open_ended(self):
        assert _parse_snx_epoch("0000:000:00000") is None

    def test_two_digit_year_post_80(self):
        assert _parse_snx_epoch("  95:001:00000") == date(1995, 1, 1)

    def test_two_digit_year_pre_80(self):
        assert _parse_snx_epoch("  25:001:00000") == date(2025, 1, 1)

    def test_malformed(self):
        assert _parse_snx_epoch("garbage") is None


class TestExtractBlock:
    def test_extracts_data_lines(self):
        lines = MINI_SNX.splitlines()
        block = _extract_block(lines, "SATELLITE/IDENTIFIER")
        assert len(block) == 4
        assert "G063" in block[0]

    def test_skips_comments(self):
        lines = MINI_SNX.splitlines()
        block = _extract_block(lines, "SATELLITE/IDENTIFIER")
        assert not any(line.startswith("*") for line in block)

    def test_missing_block(self):
        lines = MINI_SNX.splitlines()
        block = _extract_block(lines, "SATELLITE/NONEXISTENT")
        assert block == []


# ---------------------------------------------------------------------------
# Catalog construction
# ---------------------------------------------------------------------------


class TestCatalogConstruction:
    def test_identities_count(self, catalog: SatelliteCatalog):
        assert len(catalog.identities) == 4

    def test_prn_assignments_count(self, catalog: SatelliteCatalog):
        assert len(catalog.prn_assignments) == 5

    def test_tx_power_count(self, catalog: SatelliteCatalog):
        assert len(catalog.tx_power_records) == 4

    def test_mass_count(self, catalog: SatelliteCatalog):
        assert len(catalog.mass_records) == 2

    def test_freq_channel_count(self, catalog: SatelliteCatalog):
        assert len(catalog.frequency_channels) == 1

    def test_plane_count(self, catalog: SatelliteCatalog):
        assert len(catalog.plane_slots) == 2

    def test_source_path(self, catalog: SatelliteCatalog, mini_snx: Path):
        assert catalog.source_path == str(mini_snx)


# ---------------------------------------------------------------------------
# Identity parsing
# ---------------------------------------------------------------------------


class TestIdentityParsing:
    def test_gps_identity(self, catalog: SatelliteCatalog):
        ident = catalog.identities["G063"]
        assert ident.svn == "G063"
        assert ident.cospar_id == "2011-036A"
        assert ident.satcat == 37753
        assert ident.block == "GPS-IIF"
        assert "2011-07-16" in ident.comment

    def test_galileo_identity(self, catalog: SatelliteCatalog):
        ident = catalog.identities["E210"]
        assert ident.block == "GAL-2"

    def test_glonass_identity(self, catalog: SatelliteCatalog):
        ident = catalog.identities["R730"]
        assert ident.block == "GLO-M"


# ---------------------------------------------------------------------------
# PRN queries
# ---------------------------------------------------------------------------


class TestPrnQueries:
    def test_prn_to_svn_current(self, catalog: SatelliteCatalog):
        assert catalog.prn_to_svn("G01", date(2025, 1, 1)) == "G080"

    def test_prn_to_svn_historical(self, catalog: SatelliteCatalog):
        assert catalog.prn_to_svn("G01", date(2020, 1, 1)) == "G063"

    def test_prn_to_svn_mid_transition(self, catalog: SatelliteCatalog):
        assert catalog.prn_to_svn("G01", date(2024, 5, 1)) == "G049"

    def test_prn_to_svn_not_found(self, catalog: SatelliteCatalog):
        assert catalog.prn_to_svn("G99", date(2025, 1, 1)) is None

    def test_svn_to_prn(self, catalog: SatelliteCatalog):
        assert catalog.svn_to_prn("G080", date(2025, 1, 1)) == "G01"

    def test_prn_history(self, catalog: SatelliteCatalog):
        history = catalog.prn_history("G01")
        assert len(history) == 3
        assert history[0].svn == "G063"
        assert history[-1].svn == "G080"

    def test_svn_history(self, catalog: SatelliteCatalog):
        history = catalog.svn_history("G063")
        assert len(history) == 1
        assert history[0].prn == "G01"


# ---------------------------------------------------------------------------
# Reassignment detection
# ---------------------------------------------------------------------------


class TestReassignments:
    def test_detects_reassignment(self, catalog: SatelliteCatalog):
        reassigns = catalog.reassignments_in_range(
            "G01", date(2024, 1, 1), date(2025, 12, 31)
        )
        assert len(reassigns) == 2
        assert reassigns[0].old_svn == "G063"
        assert reassigns[0].new_svn == "G049"
        assert reassigns[1].old_svn == "G049"
        assert reassigns[1].new_svn == "G080"

    def test_no_reassignment_in_stable_period(self, catalog: SatelliteCatalog):
        reassigns = catalog.reassignments_in_range(
            "G01", date(2015, 1, 1), date(2020, 1, 1)
        )
        assert len(reassigns) == 0

    def test_no_reassignment_for_stable_prn(self, catalog: SatelliteCatalog):
        reassigns = catalog.reassignments_in_range(
            "E01", date(2020, 1, 1), date(2025, 12, 31)
        )
        assert len(reassigns) == 0


# ---------------------------------------------------------------------------
# Active PRNs
# ---------------------------------------------------------------------------


class TestActivePrns:
    def test_active_gps(self, catalog: SatelliteCatalog):
        active = catalog.active_prns("G", date(2025, 1, 1))
        assert active == ["G01"]

    def test_active_galileo(self, catalog: SatelliteCatalog):
        active = catalog.active_prns("E", date(2025, 1, 1))
        assert active == ["E01"]

    def test_no_active_beidou(self, catalog: SatelliteCatalog):
        active = catalog.active_prns("C", date(2025, 1, 1))
        assert active == []


# ---------------------------------------------------------------------------
# Satellite metadata queries
# ---------------------------------------------------------------------------


class TestMetadataQueries:
    def test_satellite_block(self, catalog: SatelliteCatalog):
        assert catalog.satellite_block("G063") == "GPS-IIF"
        assert catalog.satellite_block("XXXX") is None

    def test_tx_power(self, catalog: SatelliteCatalog):
        assert catalog.tx_power("G063", date(2020, 1, 1)) == 240
        assert catalog.tx_power("G080", date(2025, 1, 1)) == 300
        assert catalog.tx_power("R730", date(2020, 1, 1)) == 65

    def test_mass(self, catalog: SatelliteCatalog):
        assert catalog.mass("G063", date(2020, 1, 1)) == 1633.0
        assert catalog.mass("R730", date(2020, 1, 1)) is None

    def test_glonass_channel(self, catalog: SatelliteCatalog):
        assert catalog.glonass_channel("R730", date(2020, 1, 1)) == 1
        assert catalog.glonass_channel("G063", date(2020, 1, 1)) is None

    def test_plane_and_slot(self, catalog: SatelliteCatalog):
        result = catalog.plane_and_slot("G063", date(2020, 1, 1))
        assert result == ("4", "D2A")

    def test_get_prn_metadata(self, catalog: SatelliteCatalog):
        meta = catalog.get_prn_metadata("G01", date(2025, 1, 1))
        assert meta is not None
        assert meta["svn"] == "G080"
        assert meta["block"] == "GPS-IIIA"
        assert meta["tx_power_watts"] == 300
        assert meta["mass_kg"] == 2161.0
        assert meta["plane"] == "4"
        assert meta["slot"] == "D2A"

    def test_get_prn_metadata_not_found(self, catalog: SatelliteCatalog):
        assert catalog.get_prn_metadata("G99", date(2025, 1, 1)) is None


# ---------------------------------------------------------------------------
# Summary and repr
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary(self, catalog: SatelliteCatalog):
        s = catalog.summary()
        assert s["total_svns"] == 4
        assert s["prn_assignments"] == 5
        assert "GPS" in s["constellations"]

    def test_repr(self, catalog: SatelliteCatalog):
        r = repr(catalog)
        assert "4 SVNs" in r
        assert "SatelliteCatalog" in r


# ---------------------------------------------------------------------------
# Integration test with real IGS file
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Load / discovery
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_from_search_dirs(self, mini_snx: Path):
        # Rename to match expected filename
        canonical = mini_snx.parent / "igs_satellite_metadata.snx"
        mini_snx.rename(canonical)
        cat = SatelliteCatalog.load(
            search_dirs=[canonical.parent],
            allow_download=False,
        )
        assert len(cat.identities) == 4

    def test_load_bundled_fallback(self, tmp_path: Path):
        """Falls back to bundled file when no local copy exists."""
        cat = SatelliteCatalog.load(
            search_dirs=[tmp_path / "nonexistent"],
            allow_download=False,
        )
        # Bundled file should have real data
        assert len(cat.identities) > 100

    def test_load_offline_no_fail(self, tmp_path: Path):
        """Offline mode never raises."""
        cat = SatelliteCatalog.load(
            search_dirs=[tmp_path / "empty"],
            allow_download=False,
        )
        assert cat is not None


# ---------------------------------------------------------------------------
# DataFrame export
# ---------------------------------------------------------------------------


class TestDataFrame:
    def test_snapshot_dataframe(self, catalog: SatelliteCatalog):
        df = catalog.to_dataframe(on_date=date(2025, 1, 1))
        assert len(df) > 0
        assert "prn" in df.columns
        assert "svn" in df.columns
        assert "tx_power_watts" in df.columns
        assert "block" in df.columns

    def test_history_dataframe(self, catalog: SatelliteCatalog):
        df = catalog.to_dataframe()
        assert len(df) == 5  # 5 PRN assignments in mini fixture
        assert "start" in df.columns
        assert "end" in df.columns

    def test_snapshot_has_correct_prns(self, catalog: SatelliteCatalog):
        df = catalog.to_dataframe(on_date=date(2025, 1, 1))
        prns = df["prn"].to_list()
        assert "G01" in prns
        assert "E01" in prns
        assert "R01" in prns


# ---------------------------------------------------------------------------
# Dataset enrichment
# ---------------------------------------------------------------------------


class TestEnrichDataset:
    def test_enrich_adds_coordinates(self, catalog: SatelliteCatalog):
        """Regression test: real datasets carry compound sid values
        ("G01|L1|C"), never bare PRN codes — enrichment must match via the
        sv coordinate, not sid, or every real dataset silently enriches to
        empty placeholders.
        """
        import numpy as np
        import xarray as xr

        ds = xr.Dataset(
            {"snr": (("epoch", "sid"), np.ones((3, 2)))},
            coords={
                "epoch": np.array(
                    ["2025-01-01", "2025-01-01", "2025-01-01"],
                    dtype="datetime64[ns]",
                ),
                "sid": ["G01|L1|C", "E01|E1|C"],
                "sv": ("sid", ["G01", "E01"]),
            },
        )
        ds = catalog.enrich_dataset(ds, on_date=date(2025, 1, 1))
        assert "svn" in ds.coords
        assert "block" in ds.coords
        assert "tx_power_watts" in ds.coords
        assert "mass_kg" in ds.coords
        assert "plane" in ds.coords
        assert "slot" in ds.coords

        assert ds.coords["svn"].sel(sid="G01|L1|C").item() == "G080"
        assert ds.coords["block"].sel(sid="G01|L1|C").item() == "GPS-IIIA"
        assert ds.coords["tx_power_watts"].sel(sid="G01|L1|C").item() == 300.0

    def test_enrich_unknown_sid(self, catalog: SatelliteCatalog):
        import numpy as np
        import xarray as xr

        ds = xr.Dataset(
            {"snr": (("epoch", "sid"), np.ones((1, 1)))},
            coords={
                "epoch": np.array(["2025-01-01"], dtype="datetime64[ns]"),
                "sid": ["X99|L1|C"],
                "sv": ("sid", ["X99"]),
            },
        )
        ds = catalog.enrich_dataset(ds, on_date=date(2025, 1, 1))
        assert ds.coords["svn"].sel(sid="X99|L1|C").item() == ""
        assert np.isnan(ds.coords["tx_power_watts"].sel(sid="X99|L1|C").item())

    def test_enrich_all_unknown_logs_warning(
        self, catalog: SatelliteCatalog, monkeypatch: pytest.MonkeyPatch
    ):
        """0% enrichment must be loud (warning), not an info-level line
        indistinguishable from a fully successful run.
        """
        from unittest.mock import MagicMock

        import numpy as np
        import xarray as xr

        from canvod.readers.gnss_specs import satellite_catalog as sat_cat_module

        mock_log = MagicMock()
        monkeypatch.setattr(sat_cat_module, "_log", mock_log)

        ds = xr.Dataset(
            {"snr": (("epoch", "sid"), np.ones((1, 1)))},
            coords={
                "epoch": np.array(["2025-01-01"], dtype="datetime64[ns]"),
                "sid": ["X99|L1|C"],
                "sv": ("sid", ["X99"]),
            },
        )
        catalog.enrich_dataset(ds, on_date=date(2025, 1, 1))

        mock_log.warning.assert_called_once()
        mock_log.info.assert_not_called()
        assert mock_log.warning.call_args.args[0] == "dataset_enriched_with_catalog"

    def test_enrich_some_known_logs_info(
        self, catalog: SatelliteCatalog, monkeypatch: pytest.MonkeyPatch
    ):
        """Partial or full enrichment stays at info level, not warning."""
        from unittest.mock import MagicMock

        import numpy as np
        import xarray as xr

        from canvod.readers.gnss_specs import satellite_catalog as sat_cat_module

        mock_log = MagicMock()
        monkeypatch.setattr(sat_cat_module, "_log", mock_log)

        ds = xr.Dataset(
            {"snr": (("epoch", "sid"), np.ones((1, 1)))},
            coords={
                "epoch": np.array(["2025-01-01"], dtype="datetime64[ns]"),
                "sid": ["G01|L1|C"],
                "sv": ("sid", ["G01"]),
            },
        )
        catalog.enrich_dataset(ds, on_date=date(2025, 1, 1))

        mock_log.info.assert_called_once()
        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Integration test with real IGS file
# ---------------------------------------------------------------------------

IGS_SNX_PATH = Path.home() / ".cache/canvod/igs_satellite_metadata.snx"


@pytest.mark.skipif(not IGS_SNX_PATH.exists(), reason="IGS SNX file not available")
class TestRealIgsSNX:
    @pytest.fixture
    def real_catalog(self) -> SatelliteCatalog:
        return SatelliteCatalog.from_file(IGS_SNX_PATH)

    def test_has_all_constellations(self, real_catalog: SatelliteCatalog):
        s = real_catalog.summary()
        for name in ["GPS", "GLONASS", "Galileo", "BeiDou"]:
            assert name in s["constellations"], f"Missing {name}"

    def test_gps_has_32_active_prns(self, real_catalog: SatelliteCatalog):
        active = real_catalog.active_prns("G", date(2025, 1, 1))
        assert len(active) >= 31  # GPS nominal = 31-32

    def test_galileo_active(self, real_catalog: SatelliteCatalog):
        active = real_catalog.active_prns("E", date(2025, 1, 1))
        assert len(active) >= 24

    def test_g01_reassignment_history(self, real_catalog: SatelliteCatalog):
        reassigns = real_catalog.reassignments_in_range(
            "G01", date(2000, 1, 1), date(2025, 12, 31)
        )
        assert len(reassigns) >= 5  # G01 has been reassigned many times

    def test_tx_power_ranges(self, real_catalog: SatelliteCatalog):
        """TX power should be in physically sensible range."""
        for rec in real_catalog.tx_power_records:
            assert 10 <= rec.power_watts <= 600, (
                f"Unexpected TX power {rec.power_watts}W for {rec.svn}"
            )

    def test_round_trip_prn_svn(self, real_catalog: SatelliteCatalog):
        """prn_to_svn and svn_to_prn should be consistent."""
        d = date(2025, 1, 1)
        for prn_code in ["G01", "G10", "E01", "R01"]:
            svn = real_catalog.prn_to_svn(prn_code, d)
            if svn:
                prn_back = real_catalog.svn_to_prn(svn, d)
                assert prn_back == prn_code, f"{prn_code} -> {svn} -> {prn_back}"
