"""Regression tests for ``_preprocess_aux_data_with_hermite``'s day_start.

SBF filenames (e.g. ``ract001a00.25_``) never match the RINEX v3 long-name
pattern ``_parse_sampling_interval_from_filename`` expects, so every SBF site
always takes the "read first file" fallback path. SBF's epoch grid is offset
by a few seconds from the day boundary, so the very first file of a day can
have its first epoch land a few seconds into the *previous* UTC day. The
fallback used to re-derive ``day_start`` by truncating that first epoch to a
date, silently shifting the whole day's target_epochs grid back by 24h and
corrupting the resulting theta/phi geometry for most satellites
(canvodpy #geometry-augmentation-bug round 2, 2026-08). ``day_start`` must
stay pinned to the already-known YYYYDOY regardless of what the fallback's
sample file's first epoch says.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.utils.tools.date_utils import YYYYDOY


def _synthetic_ephemeris_ds() -> xr.Dataset:
    """A tiny (epoch, sid) ephemeris dataset spanning several days."""
    epochs = np.array(
        [
            np.datetime64("2024-12-30T00:00:00") + np.timedelta64(i * 900, "s")
            for i in range(480)  # 5 days at 15-min cadence
        ]
    )
    n = len(epochs)
    t = np.arange(n, dtype=float)
    return xr.Dataset(
        {
            "X": (["epoch", "sid"], (2e7 + 1e3 * t)[:, None]),
            "Y": (["epoch", "sid"], (1e7 + 1e3 * t)[:, None]),
            "Z": (["epoch", "sid"], (1.5e7 + 1e3 * t)[:, None]),
            "Vx": (["epoch", "sid"], np.full((n, 1), 1e3 / 900)),
            "Vy": (["epoch", "sid"], np.full((n, 1), 1e3 / 900)),
            "Vz": (["epoch", "sid"], np.full((n, 1), 1e3 / 900)),
        },
        coords={"epoch": epochs, "sid": ["G01|L1|C"]},
    )


def _fake_self(tmp_path: Path) -> SimpleNamespace:
    config = mock.MagicMock()
    config.processing.aux_data.zarr_async_concurrency = None

    aux_pipeline = mock.MagicMock()
    aux_pipeline.get.return_value = _synthetic_ephemeris_ds()
    aux_pipeline.is_loaded.return_value = False

    # File whose first epoch is a few seconds into the *previous* day, as
    # the real ract001a00.25_ file was while SBF epochs were stored in UTC.
    sbf_like_epochs = np.array(
        [
            np.datetime64("2024-12-31T23:59:42"),
            np.datetime64("2025-01-01T00:00:02"),
        ]
    )
    fake_reader = mock.MagicMock()
    fake_reader.to_ds.return_value = xr.Dataset(coords={"epoch": sbf_like_epochs})

    return SimpleNamespace(
        _logger=mock.MagicMock(),
        _config=config,
        aux_pipeline=aux_pipeline,
        matched_data_dirs=SimpleNamespace(yyyydoy=YYYYDOY(year=2025, doy=1)),
        _parse_sampling_interval_from_filename=(
            RinexDataProcessor._parse_sampling_interval_from_filename
        ),
        _make_reader=mock.MagicMock(return_value=fake_reader),
    )


def test_day_start_not_shifted_by_fallback_first_epoch(tmp_path: Path) -> None:
    fake_self = _fake_self(tmp_path)
    # SBF-style filename: no underscores, so the fast filename-based
    # sampling-interval detection fails and the fallback (which used to
    # clobber day_start) always fires.
    rinex_files = [tmp_path / "ract001a00.25_"]
    rinex_files[0].touch()
    output_path = tmp_path / "aux_2025001.zarr"

    RinexDataProcessor._preprocess_aux_data_with_hermite(
        fake_self, rinex_files, output_path
    )

    written = xr.open_zarr(output_path, consolidated=False, decode_timedelta=True)
    assert written.epoch.values[0] == np.datetime64("2025-01-01T00:00:00"), (
        "day_start was shifted back a day by the fallback's first_ds.epoch "
        "truncation instead of staying pinned to the known YYYYDOY (2025001)"
    )
    assert written.epoch.values[-1] < np.datetime64("2025-01-02T00:00:00")
