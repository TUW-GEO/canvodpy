"""The deprecated ``canvodpy.orchestrator.interpolator`` on the single-day test data.

All of canvodpy interpolates with ``canvod.auxiliary.interpolation``. The
deprecated module only keeps its names, as subclasses without logic of their
own; it must give the same satellite positions, velocities and clock
corrections from the same inputs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator import interpolator as orch

from canvod.auxiliary.clock.reader import ClkFile
from canvod.auxiliary.ephemeris.reader import Sp3File
from canvod.auxiliary.interpolation import interpolator as aux
from canvod.auxiliary.preprocessing import prep_aux_ds

AUX = (
    Path(__file__).parents[2] / "packages/canvod-readers/tests/test_data/valid/aux_data"
)
SP3 = AUX / "01_SP3/COD0MGXFIN_20250010000_01D_05M_ORB.SP3"
CLK = AUX / "02_CLK/COD0MGXFIN_20250010000_01D_30S_CLK.CLK"

pytestmark = [
    pytest.mark.skipif(
        not (SP3.exists() and CLK.exists()), reason="aux test data not available"
    ),
    pytest.mark.filterwarnings("ignore:.*left over from development:FutureWarning"),
]

# Same 5 s day grid as the orchestrator for 5 s data (processor.py:~1197).
TARGET = np.datetime64("2025-01-01T00:00:00", "ns") + np.arange(17280) * np.timedelta64(
    5, "s"
)


def _assert_same(a: xr.Dataset, b: xr.Dataset) -> None:
    assert set(a.data_vars) == set(b.data_vars), "data variables differ"
    np.testing.assert_array_equal(a["epoch"].values, b["epoch"].values)
    np.testing.assert_array_equal(a["sid"].values, b["sid"].values)
    for v in a.data_vars:
        np.testing.assert_array_equal(a[v].values, b[v].values, err_msg=f"{v} differs")


@pytest.fixture(scope="module")
def ephem_ds() -> xr.Dataset:
    return prep_aux_ds(Sp3File.from_file(SP3).data)


@pytest.fixture(scope="module")
def clock_ds() -> xr.Dataset:
    return prep_aux_ds(ClkFile.from_file(CLK).data)


def test_sp3_interpolators_agree(ephem_ds):
    kw = {"use_velocities": True, "fallback_method": "linear"}
    a = orch.Sp3InterpolationStrategy(config=orch.Sp3Config(**kw)).interpolate(
        ephem_ds, TARGET
    )
    b = aux.Sp3InterpolationStrategy(config=aux.Sp3Config(**kw)).interpolate(
        ephem_ds, TARGET
    )
    _assert_same(a, b)


def test_clock_interpolators_agree(clock_ds):
    kw = {"window_size": 9, "jump_threshold": 1e-6}
    a = orch.ClockInterpolationStrategy(config=orch.ClockConfig(**kw)).interpolate(
        clock_ds, TARGET
    )
    b = aux.ClockInterpolationStrategy(config=aux.ClockConfig(**kw)).interpolate(
        clock_ds, TARGET
    )
    _assert_same(a, b)
