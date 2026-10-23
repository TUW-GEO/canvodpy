"""Tests for the functional L4 API (canvodpy.functional)."""

from __future__ import annotations

import pickle
import unittest.mock
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


def _make_ds(n_epochs: int = 5, n_sids: int = 3) -> xr.Dataset:
    epochs = pd.date_range("2025-01-01", periods=n_epochs, freq="30s")
    sids = [f"G0{i}|L1|C" for i in range(1, n_sids + 1)]
    return xr.Dataset(
        {
            "SNR": (["epoch", "sid"], np.ones((n_epochs, n_sids))),
            "theta": (["epoch", "sid"], np.full((n_epochs, n_sids), 0.5)),
            "phi": (["epoch", "sid"], np.zeros((n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


# ---------------------------------------------------------------------------
# read_rinex
# ---------------------------------------------------------------------------


class TestReadRinex:
    def test_delegates_to_reader_factory(self):
        from canvodpy.functional import read_rinex

        mock_ds = _make_ds()
        mock_reader = unittest.mock.MagicMock()
        mock_reader.to_ds.return_value = mock_ds

        with unittest.mock.patch(
            "canvodpy.functional.ReaderFactory.create", return_value=mock_reader
        ) as mock_create:
            result = read_rinex("fake.rnx", reader="rinex3")

        mock_create.assert_called_once_with("rinex3", fpath="fake.rnx")
        mock_reader.to_ds.assert_called_once()
        assert result is mock_ds

    def test_passes_extra_kwargs_to_factory(self):
        from canvodpy.functional import read_rinex

        mock_reader = unittest.mock.MagicMock()
        mock_reader.to_ds.return_value = _make_ds()

        with unittest.mock.patch(
            "canvodpy.functional.ReaderFactory.create", return_value=mock_reader
        ) as mock_create:
            read_rinex("fake.rnx", reader="custom", keep_vars=["SNR"])

        mock_create.assert_called_once_with(
            "custom", fpath="fake.rnx", keep_vars=["SNR"]
        )


# ---------------------------------------------------------------------------
# augment_with_ephemeris
# ---------------------------------------------------------------------------


class TestAugmentWithEphemeris:
    def test_final_source_calls_agency_provider(self):
        from canvodpy.functional import augment_with_ephemeris

        ds = _make_ds()
        mock_provider = unittest.mock.MagicMock()
        mock_provider.augment_dataset.return_value = ds

        # AgencyEphemerisProvider is imported locally inside augment_with_ephemeris;
        # patch at the source module so the local import picks up the mock.
        with unittest.mock.patch(
            "canvod.auxiliary.ephemeris.provider.AgencyEphemerisProvider",
            return_value=mock_provider,
        ):
            result = augment_with_ephemeris(
                ds, receiver_position=object(), source="final"
            )

        mock_provider.augment_dataset.assert_called_once()
        assert result is ds

    def test_broadcast_source_calls_sbf_provider(self):
        from canvodpy.functional import augment_with_ephemeris

        ds = _make_ds()
        mock_provider = unittest.mock.MagicMock()
        mock_provider.augment_dataset.return_value = ds

        with unittest.mock.patch(
            "canvod.auxiliary.ephemeris.provider.SbfBroadcastProvider",
            return_value=mock_provider,
        ):
            result = augment_with_ephemeris(
                ds, receiver_position=object(), source="broadcast"
            )

        mock_provider.augment_dataset.assert_called_once()

    def test_unknown_source_raises(self):
        from canvodpy.functional import augment_with_ephemeris

        with pytest.raises(ValueError, match="Unknown ephemeris source"):
            augment_with_ephemeris(
                _make_ds(), receiver_position=object(), source="mystery"
            )

    def test_final_with_date_calls_preprocess_day(self):
        from canvodpy.functional import augment_with_ephemeris

        ds = _make_ds()
        mock_provider = unittest.mock.MagicMock()
        mock_provider.augment_dataset.return_value = ds

        with unittest.mock.patch(
            "canvod.auxiliary.ephemeris.provider.AgencyEphemerisProvider",
            return_value=mock_provider,
        ):
            augment_with_ephemeris(
                ds,
                receiver_position=object(),
                source="final",
                date="2025001",
                site_config=object(),
            )

        mock_provider.preprocess_day.assert_called_once()


# ---------------------------------------------------------------------------
# create_grid
# ---------------------------------------------------------------------------


class TestCreateGrid:
    def test_delegates_to_grid_factory(self):
        from canvodpy.functional import create_grid

        mock_grid = unittest.mock.MagicMock()
        mock_grid.ncells = 324
        mock_builder = unittest.mock.MagicMock()
        mock_builder.build.return_value = mock_grid

        with unittest.mock.patch(
            "canvodpy.functional.GridFactory.create", return_value=mock_builder
        ) as mock_create:
            result = create_grid("equal_area", angular_resolution=5.0)

        mock_create.assert_called_once_with("equal_area", angular_resolution=5.0)
        mock_builder.build.assert_called_once()
        assert result is mock_grid


# ---------------------------------------------------------------------------
# assign_grid_cells
# ---------------------------------------------------------------------------


class TestAssignGridCells:
    def test_delegates_to_add_cell_ids_fast(self):
        from canvodpy.functional import assign_grid_cells

        ds = _make_ds()
        mock_grid = unittest.mock.MagicMock()
        expected = ds.assign_coords(
            cell=(["epoch", "sid"], np.zeros((5, 3), dtype=int))
        )

        # add_cell_ids_to_ds_fast is imported locally inside assign_grid_cells;
        # patch at the source module.
        with unittest.mock.patch(
            "canvod.grids.add_cell_ids_to_ds_fast", return_value=expected
        ) as mock_fn:
            result = assign_grid_cells(ds, mock_grid, grid_name="equal_area")

        mock_fn.assert_called_once_with(ds, mock_grid, "equal_area")
        assert result is expected


# ---------------------------------------------------------------------------
# calculate_vod
# ---------------------------------------------------------------------------


class TestCalculateVod:
    def test_delegates_to_vod_factory(self):
        from canvodpy.functional import calculate_vod

        canopy_ds = _make_ds()
        sky_ds = _make_ds()
        mock_vod = xr.Dataset({"VOD": (["epoch", "sid"], np.zeros((5, 3)))})
        mock_calc = unittest.mock.MagicMock()
        mock_calc.calculate_vod.return_value = mock_vod

        with unittest.mock.patch(
            "canvodpy.functional.VODFactory.create", return_value=mock_calc
        ) as mock_create:
            result = calculate_vod(canopy_ds, sky_ds, calculator="tau_omega")

        mock_create.assert_called_once_with(
            "tau_omega", canopy_ds=canopy_ds, sky_ds=sky_ds
        )
        mock_calc.calculate_vod.assert_called_once()
        assert result is mock_vod


# ---------------------------------------------------------------------------
# _to_file variants
# ---------------------------------------------------------------------------


class _PickleableGrid:
    """Minimal pickleable grid substitute (MagicMock is not pickleable)."""

    ncells = 100


class TestFunctionalToFile:
    def test_read_rinex_to_file_writes_netcdf(self, tmp_path):
        from canvodpy.functional import read_rinex_to_file

        ds = _make_ds()
        out = tmp_path / "out.nc"

        with unittest.mock.patch("canvodpy.functional.read_rinex", return_value=ds):
            result = read_rinex_to_file("fake.rnx", str(out))

        assert Path(result).exists()
        loaded = xr.open_dataset(result)
        assert "SNR" in loaded.data_vars
        loaded.close()

    def test_create_grid_to_file_pickles_grid(self, tmp_path):
        from canvodpy.functional import create_grid_to_file

        fake_grid = _PickleableGrid()
        out = tmp_path / "grid.pkl"

        with unittest.mock.patch(
            "canvodpy.functional.create_grid", return_value=fake_grid
        ):
            # signature: create_grid_to_file(output_path, grid_type, **grid_params)
            result = create_grid_to_file(str(out), "equal_area")

        assert Path(result).exists()
        loaded = pickle.loads(Path(result).read_bytes())
        assert loaded.ncells == 100

    def test_assign_grid_cells_to_file_round_trip(self, tmp_path):
        from canvodpy.functional import assign_grid_cells_to_file

        ds = _make_ds()
        ds.to_netcdf(tmp_path / "ds.nc")
        fake_grid = _PickleableGrid()
        grid_out = tmp_path / "grid.pkl"
        grid_out.write_bytes(pickle.dumps(fake_grid))
        expected = ds.assign_coords(
            cell=(["epoch", "sid"], np.zeros((5, 3), dtype=int))
        )
        out = tmp_path / "out.nc"

        with unittest.mock.patch(
            "canvodpy.functional.assign_grid_cells", return_value=expected
        ):
            result = assign_grid_cells_to_file(
                str(tmp_path / "ds.nc"), str(grid_out), str(out)
            )

        assert Path(result).exists()

    def test_calculate_vod_to_file_round_trip(self, tmp_path):
        from canvodpy.functional import calculate_vod_to_file

        canopy_ds = _make_ds()
        sky_ds = _make_ds()
        canopy_ds.to_netcdf(tmp_path / "canopy.nc")
        sky_ds.to_netcdf(tmp_path / "sky.nc")
        mock_vod = xr.Dataset({"VOD": (["epoch", "sid"], np.zeros((5, 3)))})
        out = tmp_path / "vod.nc"

        with unittest.mock.patch(
            "canvodpy.functional.calculate_vod", return_value=mock_vod
        ):
            result = calculate_vod_to_file(
                str(tmp_path / "canopy.nc"),
                str(tmp_path / "sky.nc"),
                str(out),
            )

        assert Path(result).exists()


# ---------------------------------------------------------------------------
# Deprecation
# ---------------------------------------------------------------------------


class TestDeprecation:
    @pytest.mark.filterwarnings("default::FutureWarning")
    @pytest.mark.parametrize(
        "name",
        [
            "read_rinex",
            "augment_with_ephemeris",
            "create_grid",
            "assign_grid_cells",
            "calculate_vod",
            "read_rinex_to_file",
            "create_grid_to_file",
            "assign_grid_cells_to_file",
            "calculate_vod_to_file",
        ],
    )
    def test_warns_and_names_replacement(self, name: str) -> None:
        from canvodpy import functional

        func = getattr(functional, name)
        # Fail inside the body: only the warning on entry matters here.
        with (
            unittest.mock.patch.object(functional, "log") as log,
            pytest.warns(FutureWarning, match="left over from development") as record,
        ):
            log.info.side_effect = RuntimeError("stop")
            with pytest.raises((RuntimeError, TypeError, OSError, ValueError)):
                func(*([None] * 3))
        assert len(record) == 1
        message = str(record[0].message)
        assert f"canvodpy.functional.{name}()" in message
        assert "no longer maintained" in message
        assert " instead." in message
