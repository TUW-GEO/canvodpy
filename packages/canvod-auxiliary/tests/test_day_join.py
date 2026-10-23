"""Orbits and clocks joined with the neighboring days (no extrapolation)."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import xarray as xr
from canvod.utils.tools import YYYYDOY

from canvod.auxiliary.core.base import AuxFile
from canvod.auxiliary.interpolation import (
    Sp3Config,
    Sp3InterpolationStrategy,
    interpolate_aux_day,
)
from canvod.auxiliary.pipeline import AuxDataPipeline

DAY = np.datetime64("2025-01-01T00:00", "ns")


def _orbit(start: str, n: int, step_min: int, svs: list[str], offset: float = 0.0):
    """Circular orbit samples (X, Y, Z, and constant Vx..Vz placeholders)."""
    epochs = np.datetime64(start, "ns") + np.arange(n) * np.timedelta64(step_min, "m")
    t = (epochs - DAY) / np.timedelta64(1, "s")
    w = 2 * np.pi / 43080.0  # GPS orbital period
    r = 2.656e7
    x = np.stack([r * np.cos(w * t + k) for k in range(len(svs))], axis=1) + offset
    y = np.stack([r * np.sin(w * t + k) for k in range(len(svs))], axis=1)
    z = np.zeros_like(x)
    zero = np.zeros_like(x)
    return xr.Dataset(
        {
            "X": (("epoch", "sv"), x),
            "Y": (("epoch", "sv"), y),
            "Z": (("epoch", "sv"), z),
            "Vx": (("epoch", "sv"), zero),
            "Vy": (("epoch", "sv"), zero),
            "Vz": (("epoch", "sv"), zero),
        },
        coords={"epoch": epochs, "sv": svs},
        attrs={"file": start},
    )


def _file(ds: xr.Dataset, yyyydoy: str = "2025001"):
    return SimpleNamespace(data=ds, date=yyyydoy)


class TestJoinDays:
    def test_keeps_a_margin_of_each_neighbor(self):
        day = _orbit("2025-01-01T00:00", 289, 5, ["G01", "G02"])  # to 24:00
        prev = _orbit("2024-12-31T00:00", 289, 5, ["G01", "G02"])
        nxt = _orbit("2025-01-02T00:00", 289, 5, ["G01", "G02"])

        joined = AuxFile.join_days(_file(day), _file(prev), _file(nxt))

        e = joined.epoch.values
        assert e[0] == DAY - np.timedelta64(1, "h")
        assert e[-1] == DAY + np.timedelta64(25, "h")
        assert len(np.unique(e)) == len(e)  # 24:00 once
        assert joined.attrs == day.attrs

    def test_the_day_wins_where_files_overlap(self):
        day = _orbit("2025-01-01T00:00", 289, 5, ["G01"])
        nxt = _orbit("2025-01-02T00:00", 289, 5, ["G01"], offset=1.0)
        prev = _orbit("2024-12-31T00:00", 289, 5, ["G01"])

        joined = AuxFile.join_days(_file(day), _file(prev), _file(nxt))

        midnight = DAY + np.timedelta64(1, "D")
        assert joined["X"].sel(epoch=midnight).item() == pytest.approx(
            day["X"].sel(epoch=midnight).item()
        )

    def test_satellite_missing_in_a_neighbor_is_nan_there(self):
        day = _orbit("2025-01-01T00:00", 288, 5, ["G01", "G02"])
        prev = _orbit("2024-12-31T00:00", 288, 5, ["G01"])
        nxt = _orbit("2025-01-02T00:00", 288, 5, ["G01", "G02"])

        joined = AuxFile.join_days(_file(day), _file(prev), _file(nxt))

        before = joined.sel(epoch=slice(None, DAY - np.timedelta64(5, "m")))
        assert np.isnan(before["X"].sel(sv="G02")).all()
        assert np.isfinite(before["X"].sel(sv="G01")).all()


def _with_velocities(ds: xr.Dataset) -> xr.Dataset:
    t = (ds.epoch.values - ds.epoch.values[0]) / np.timedelta64(1, "s")
    return ds.assign(
        {
            v: (("epoch", "sv"), np.gradient(ds[c].values, t, axis=0))
            for c, v in (("X", "Vx"), ("Y", "Vy"), ("Z", "Vz"))
        }
    )


class TestInterpolationWithGaps:
    interp = Sp3InterpolationStrategy(
        config=Sp3Config(use_velocities=True, fallback_method="linear")
    )

    def test_no_value_outside_the_data(self):
        ds = _with_velocities(_orbit("2025-01-01T00:00", 96, 15, ["G01"]))  # 23:45
        targets = np.array([DAY + np.timedelta64(23 * 60 + 50, "m")])

        out = self.interp.interpolate(ds, targets)

        assert np.isnan(out["X"].values).all()

    def test_nan_epochs_are_skipped_and_wide_gaps_not_bridged(self):
        ds = _orbit("2025-01-01T00:00", 96, 15, ["G01", "G02"])
        x = ds["X"].values.copy()
        x[40:50, 1] = np.nan  # G02 missing 10:00..12:15
        ds = _with_velocities(ds.assign(X=(("epoch", "sv"), x)))
        targets = DAY + np.array([5 * 60, 11 * 60], dtype="timedelta64[m]")

        out = self.interp.interpolate(ds, targets)

        assert np.isfinite(out["X"].sel(sv="G01")).all()
        g02 = out["X"].sel(sv="G02").values
        assert np.isfinite(g02[0])  # 05:00, inside its data
        assert np.isnan(g02[1])  # 11:00, inside the gap


class TestCreateStandardNeighbors:
    def _config(self):
        cfg = MagicMock()
        cfg.processing.aux_data.agency = "COD"
        cfg.processing.aux_data.product_type = "final"
        cfg.processing.aux_data.ftp_timeout_s = 30
        cfg.processing.aux_data.fetch_clock = False
        cfg.processing.params.aggregate_glonass_fdma = True
        cfg.nasa_earthdata_acc_mail = None
        return cfg

    def _matched_dirs(self):
        md = MagicMock()
        md.yyyydoy.date = date(2025, 1, 4)  # Saturday, last day of GPS week 2347
        md.yyyydoy.to_str.return_value = "2025004"
        return md

    def test_registers_the_previous_and_next_day(self, tmp_path):
        made = []

        def make(date, **kwargs):
            made.append(date)
            return SimpleNamespace(fpath=tmp_path / f"{date}.SP3")

        with (
            patch("canvod.config.load_config", return_value=self._config()),
            patch(
                "canvod.auxiliary.ephemeris.Sp3File.from_datetime_date",
                side_effect=make,
            ),
        ):
            pipeline = AuxDataPipeline.create_standard(
                self._matched_dirs(), tmp_path, ftp_server="ftp://x"
            )

        assert sorted(made) == [date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5)]
        paths = pipeline.source_file_paths()
        assert set(paths) == {
            "ephemerides",
            "ephemerides_previous_day",
            "ephemerides_next_day",
        }

    def test_missing_next_day_stops_with_a_clear_error(self, tmp_path):
        def make(date, **kwargs):
            if date == date.__class__(2025, 1, 5):
                raise RuntimeError("No orbit file of COD/final for 2025005")
            return SimpleNamespace(fpath=tmp_path / f"{date}.SP3")

        with (
            patch("canvod.config.load_config", return_value=self._config()),
            patch(
                "canvod.auxiliary.ephemeris.Sp3File.from_datetime_date",
                side_effect=make,
            ),
            pytest.raises(RuntimeError, match="next day \\(2025005\\)") as err,
        ):
            AuxDataPipeline.create_standard(
                self._matched_dirs(), tmp_path, ftp_server="ftp://x"
            )
        assert "last epochs of 2025004" in str(err.value)
        assert "Process 2025004 once it is published" in str(err.value)


AUX_DATA = Path(__file__).parents[2] / "canvod-readers/tests/test_data/valid/aux_data"


@pytest.mark.skipif(
    not (AUX_DATA / "01_SP3/COD0MGXFIN_20250020000_01D_05M_ORB.SP3").exists(),
    reason="test data of the neighboring days not available",
)
class TestRealNeighborFiles:
    """2025-001 with the CODE files of 2024-366 and 2025-002, no download."""

    @pytest.fixture(scope="class")
    def pipeline(self):
        cfg = TestCreateStandardNeighbors()._config()
        cfg.processing.aux_data.fetch_clock = True
        md = SimpleNamespace(yyyydoy=YYYYDOY(year=2025, doy=1))
        with (
            patch("canvod.config.load_config", return_value=cfg),
            patch.object(
                AuxFile,
                "download_with_fallback",
                side_effect=AssertionError("must not download"),
            ),
        ):
            pipeline = AuxDataPipeline.create_standard(
                md, AUX_DATA, ftp_server="ftp://unused"
            )
            pipeline.load_all()
        return pipeline

    def test_the_day_lies_inside_the_data(self, pipeline):
        hour = np.timedelta64(1, "h")
        for name in ("ephemerides", "clock"):
            e = pipeline.get(name).epoch.values
            assert e[0] == DAY - hour
            assert e[-1] == DAY + np.timedelta64(1, "D") + hour

    def test_velocity_at_midnight_is_a_central_difference(self, pipeline):
        ephem = pipeline.get("ephemerides")
        midnight = DAY + np.timedelta64(1, "D")
        five = np.timedelta64(5, "m")
        sid = "G01|L1|C"
        dx = ephem["X"].sel(sid=sid, epoch=midnight + five) - ephem["X"].sel(
            sid=sid, epoch=midnight - five
        )
        assert ephem["Vx"].sel(sid=sid, epoch=midnight).item() == pytest.approx(
            dx.item() / 600.0
        )

    def test_committed_aux_cache_is_what_a_run_computes(self, pipeline):
        cache = xr.open_zarr(AUX_DATA / "aux_2025001.zarr", consolidated=False)
        edges = np.r_[0:120, -120:0]  # first and last 10 minutes
        expected = cache.isel(epoch=edges).compute()

        got = interpolate_aux_day(
            pipeline.get("ephemerides"), pipeline.get("clock"), expected.epoch.values
        )

        assert list(got.sid.values) == list(expected.sid.values)
        for var in ("X", "Y", "Z", "Vx", "Vy", "Vz", "clock_offset"):
            np.testing.assert_allclose(got[var], expected[var], rtol=0, atol=1e-9)
        assert np.isfinite(got["X"].sel(sid="G01|L1|C")).all()
