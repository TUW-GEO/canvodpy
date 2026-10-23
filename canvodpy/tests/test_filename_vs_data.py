"""Tests for warnings when filenames disagree with the data they hold."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import xarray as xr
from canvodpy.orchestrator.processor import _warn_if_aux_grid_coarser


def _epochs(step_s: int, n: int = 10) -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(n) * np.timedelta64(
        step_s, "s"
    )
    return xr.Dataset(coords={"epoch": epochs})


def test_warns_when_data_is_finer_than_grid() -> None:
    log = mock.Mock()
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(1), _epochs(5))
    log.warning.assert_called_once()
    assert log.warning.call_args.kwargs["data_sampling_s"] == 1.0
    assert log.warning.call_args.kwargs["ephemeris_grid_s"] == 5.0


def test_silent_when_grid_matches_or_is_finer() -> None:
    log = mock.Mock()
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(5), _epochs(5))
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(30), _epochs(5))
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(5, n=1), _epochs(5))
    log.warning.assert_not_called()


def test_warns_when_first_epoch_is_outside_named_span() -> None:
    from canvodpy.orchestrator.processor import _warn_if_name_disagrees_with_data

    name = "FANA01INK_R_20250010015_15M_05S_AA.rnx"  # 00:15 to 00:30
    log = mock.Mock()
    ok = _epochs(5)  # starts 00:00, outside 00:15 to 00:30
    _warn_if_name_disagrees_with_data(log, Path("f"), name, ok)
    log.warning.assert_called_once()

    log = mock.Mock()
    inside = ok.assign_coords(epoch=ok.epoch + np.timedelta64(15 * 60 - 3, "s"))
    _warn_if_name_disagrees_with_data(log, Path("f"), name, inside)  # 3 s early
    _warn_if_name_disagrees_with_data(log, Path("f"), "", ok)  # no name
    log.warning.assert_not_called()


def test_warns_when_epoch_count_differs_from_name() -> None:
    from canvodpy.orchestrator.processor import (
        _warn_if_epoch_count_differs_from_name,
    )

    name = "FANA01INK_R_20250010015_15M_05S_AA.rnx"  # 180 epochs
    log = mock.Mock()
    _warn_if_epoch_count_differs_from_name(log, Path("f"), name, _epochs(5, n=170))
    log.warning.assert_called_once()
    kwargs = log.warning.call_args.kwargs
    assert (kwargs["expected_epochs"], kwargs["missing_epochs"]) == (180, 10)

    log = mock.Mock()
    _warn_if_epoch_count_differs_from_name(log, Path("f"), name, _epochs(5, n=180))
    _warn_if_epoch_count_differs_from_name(log, Path("f"), "", _epochs(5, n=3))
    log.warning.assert_not_called()


def test_run_turns_the_rinex_readers_own_check_off() -> None:
    """A run checks every format against the name instead."""
    from canvodpy.orchestrator.processor import run_reader_options

    assert run_reader_options("rinex3") == {"completeness_mode": "off"}
    assert run_reader_options("rinex3_stripped") == {"completeness_mode": "off"}
    assert run_reader_options("sbf") == {}
