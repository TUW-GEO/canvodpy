"""Unit tests for canvod.auxiliary.pipeline.AuxDataPipeline."""

from datetime import date
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest
import xarray as xr

from canvod.auxiliary.pipeline import AuxDataPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_matched_dirs():
    """Create a mock MatchedDirs with required attributes."""
    md = MagicMock()
    md.yyyydoy.to_str.return_value = "2024302"
    md.yyyydoy.date = MagicMock()
    return md


def _make_aux_ds(n_epochs: int = 10, n_sids: int = 3) -> xr.Dataset:
    """Minimal auxiliary dataset."""
    rng = np.random.default_rng(42)
    epochs = np.array(
        [
            np.datetime64("2024-10-29T00:00:00") + np.timedelta64(i * 900, "s")
            for i in range(n_epochs)
        ]
    )
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    return xr.Dataset(
        {
            "X": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Y": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
            "Z": (["epoch", "sid"], rng.uniform(1e7, 3e7, (n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


def _make_clock_ds(n_epochs: int = 10, n_sids: int = 3) -> xr.Dataset:
    """Minimal clock dataset."""
    rng = np.random.default_rng(42)
    epochs = np.array(
        [
            np.datetime64("2024-10-29T00:00:00") + np.timedelta64(i * 30, "s")
            for i in range(n_epochs)
        ]
    )
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    return xr.Dataset(
        {
            "clock_offset": (
                ["epoch", "sid"],
                rng.uniform(-1e-3, 1e-3, (n_epochs, n_sids)),
            ),
        },
        coords={"epoch": epochs, "sid": sids},
    )


# ---------------------------------------------------------------------------
# AuxDataPipeline
# ---------------------------------------------------------------------------


class TestAuxDataPipeline:
    """Tests for AuxDataPipeline."""

    def test_init(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        assert pipeline.matched_dirs is md
        assert pipeline._registry == {}
        assert pipeline._cache == {}

    def test_init_with_keep_sids(self):
        md = _make_mock_matched_dirs()
        sids = ["G01|L1C", "G02|L1C"]
        pipeline = AuxDataPipeline(md, keep_sids=sids)
        assert pipeline.keep_sids == sids

    def test_register(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        handler = MagicMock()
        handler.fpath = "/fake/path/sp3.gz"

        pipeline.register("ephemerides", handler, required=True)

        assert "ephemerides" in pipeline._registry
        assert pipeline._registry["ephemerides"]["required"] is True
        assert pipeline._registry["ephemerides"]["loaded"] is False

    def test_register_overwrites(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        handler1 = MagicMock()
        handler1.fpath = "/fake/path/sp3_1.gz"
        handler2 = MagicMock()
        handler2.fpath = "/fake/path/sp3_2.gz"

        pipeline.register("ephemerides", handler1)
        pipeline.register("ephemerides", handler2)

        assert pipeline._registry["ephemerides"]["handler"] is handler2

    def test_is_loaded_false_before_load(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        handler = MagicMock()
        handler.fpath = "/fake"
        pipeline.register("ephemerides", handler)

        assert pipeline.is_loaded("ephemerides") is False

    def test_is_loaded_unregistered(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        assert pipeline.is_loaded("nonexistent") is False

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_load_all_success(self, mock_prep):
        """load_all should cache preprocessed datasets."""
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        aux_ds = _make_aux_ds()
        preprocessed_ds = _make_aux_ds()

        handler = MagicMock()
        handler.fpath = "/fake/path"
        type(handler).data = PropertyMock(return_value=aux_ds)
        mock_prep.return_value = preprocessed_ds

        pipeline.register("ephemerides", handler, required=True)
        pipeline.load_all()

        assert pipeline.is_loaded("ephemerides") is True
        assert "ephemerides" in pipeline._cache

    @pytest.mark.parametrize("aggregate", [True, False])
    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_load_all_passes_glonass_setting(self, mock_prep, aggregate):
        """The aux SIDs must use the reader's GLONASS FDMA setting."""
        pipeline = AuxDataPipeline(
            _make_mock_matched_dirs(), aggregate_glonass_fdma=aggregate
        )
        handler = MagicMock()
        handler.fpath = "/fake/path"
        type(handler).data = PropertyMock(return_value=_make_aux_ds())
        mock_prep.return_value = _make_aux_ds()

        pipeline.register("ephemerides", handler, required=True)
        pipeline.load_all()

        assert mock_prep.call_args.kwargs["aggregate_glonass_fdma"] is aggregate

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_load_all_required_failure_raises(self, mock_prep):
        """Required file failure should raise RuntimeError."""
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        handler = MagicMock()
        handler.fpath = "/fake"
        type(handler).data = PropertyMock(side_effect=FileNotFoundError("not found"))

        pipeline.register("ephemerides", handler, required=True)

        with pytest.raises(RuntimeError, match="Required auxiliary file"):
            pipeline.load_all()

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_load_all_optional_failure_continues(self, mock_prep):
        """Optional file failure should not raise."""
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        handler = MagicMock()
        handler.fpath = "/fake"
        type(handler).data = PropertyMock(side_effect=FileNotFoundError("not found"))

        pipeline.register("optional_file", handler, required=False)
        pipeline.load_all()  # Should not raise

        assert pipeline.is_loaded("optional_file") is False

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_get_returns_cached(self, mock_prep):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        preprocessed = _make_aux_ds()
        handler = MagicMock()
        handler.fpath = "/fake"
        type(handler).data = PropertyMock(return_value=_make_aux_ds())
        mock_prep.return_value = preprocessed

        pipeline.register("ephemerides", handler, required=True)
        pipeline.load_all()

        result = pipeline.get("ephemerides")
        assert result is preprocessed

    def test_get_unregistered_raises(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        with pytest.raises(KeyError, match="not registered"):
            pipeline.get("nonexistent")

    def test_get_not_loaded_raises(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        handler = MagicMock()
        handler.fpath = "/fake"
        pipeline.register("ephemerides", handler)

        with pytest.raises(ValueError, match="not loaded"):
            pipeline.get("ephemerides")

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_get_ephemerides_convenience(self, mock_prep):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        preprocessed = _make_aux_ds()
        handler = MagicMock()
        handler.fpath = "/fake"
        type(handler).data = PropertyMock(return_value=_make_aux_ds())
        mock_prep.return_value = preprocessed

        pipeline.register("ephemerides", handler, required=True)
        pipeline.load_all()

        assert pipeline.get_ephemerides() is preprocessed

    @patch("canvod.auxiliary.pipeline.prep_aux_ds")
    def test_get_for_time_range(self, mock_prep):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)

        preprocessed = _make_aux_ds(n_epochs=96)  # 96 * 15min = 24h
        handler = MagicMock()
        handler.fpath = "/fake"
        type(handler).data = PropertyMock(return_value=_make_aux_ds())
        mock_prep.return_value = preprocessed

        pipeline.register("ephemerides", handler, required=True)
        pipeline.load_all()

        start = np.datetime64("2024-10-29T01:00:00")
        end = np.datetime64("2024-10-29T02:00:00")
        sliced = pipeline.get_for_time_range(
            "ephemerides", start, end, buffer_minutes=5
        )

        # Should be a subset of the full dataset
        assert len(sliced.epoch) <= len(preprocessed.epoch)

    def test_list_registered(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        handler = MagicMock()
        handler.fpath = "/fake"
        pipeline.register("ephemerides", handler, required=True)

        info = pipeline.list_registered()
        assert "ephemerides" in info
        assert info["ephemerides"]["required"] is True
        assert info["ephemerides"]["loaded"] is False

    def test_repr(self):
        md = _make_mock_matched_dirs()
        pipeline = AuxDataPipeline(md)
        r = repr(pipeline)
        assert "AuxDataPipeline" in r
        assert "2024302" in r


class TestCreateStandardFetchClock:
    """create_standard()'s clock-fetching gate."""

    @staticmethod
    def _make_config(fetch_clock: bool):
        cfg = MagicMock()
        cfg.processing.aux_data.agency = "COD"
        cfg.processing.aux_data.product_type = "final"
        cfg.processing.aux_data.ftp_timeout_s = 30
        cfg.processing.aux_data.fetch_clock = fetch_clock
        cfg.processing.aux_data.get_ftp_servers.return_value = [
            ("ftp://gssc.esa.int", None)
        ]
        cfg.nasa_earthdata_acc_mail = None
        return cfg

    @staticmethod
    def _make_matched_dirs():
        md = _make_mock_matched_dirs()
        md.yyyydoy.date = date(2024, 10, 29)
        return md

    @patch("canvod.auxiliary.ephemeris.Sp3File")
    @patch("canvod.auxiliary.clock.ClkFile")
    @patch("canvod.config.load_config")
    def test_fetch_clock_true_registers_both(
        self, mock_load_config, mock_clk, mock_sp3, tmp_path
    ):
        mock_load_config.return_value = self._make_config(fetch_clock=True)
        mock_sp3.from_datetime_date.return_value = MagicMock(fpath="/fake/sp3")
        mock_clk.from_datetime_date.return_value = MagicMock(fpath="/fake/clk")

        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=self._make_matched_dirs(),
            aux_file_path=tmp_path,
        )

        assert "ephemerides" in pipeline._registry
        assert "clock" in pipeline._registry

    @patch("canvod.auxiliary.ephemeris.Sp3File")
    @patch("canvod.auxiliary.clock.ClkFile")
    @patch("canvod.config.load_config")
    def test_fetch_clock_false_via_config_skips_clock(
        self, mock_load_config, mock_clk, mock_sp3, tmp_path
    ):
        mock_load_config.return_value = self._make_config(fetch_clock=False)
        mock_sp3.from_datetime_date.return_value = MagicMock(fpath="/fake/sp3")

        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=self._make_matched_dirs(),
            aux_file_path=tmp_path,
        )

        assert "ephemerides" in pipeline._registry
        assert "clock" not in pipeline._registry
        mock_clk.from_datetime_date.assert_not_called()

    @patch("canvod.auxiliary.ephemeris.Sp3File")
    @patch("canvod.auxiliary.clock.ClkFile")
    @patch("canvod.config.load_config")
    def test_explicit_fetch_clock_overrides_config(
        self, mock_load_config, mock_clk, mock_sp3, tmp_path
    ):
        # Config says True; explicit kwarg (False) should win.
        mock_load_config.return_value = self._make_config(fetch_clock=True)
        mock_sp3.from_datetime_date.return_value = MagicMock(fpath="/fake/sp3")

        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=self._make_matched_dirs(),
            aux_file_path=tmp_path,
            fetch_clock=False,
        )

        assert "clock" not in pipeline._registry
        mock_clk.from_datetime_date.assert_not_called()
