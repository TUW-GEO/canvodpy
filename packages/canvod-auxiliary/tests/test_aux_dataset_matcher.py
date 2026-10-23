"""Test matching auxiliary datasets to a file's epochs."""

import numpy as np
import xarray as xr

from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy
from canvod.auxiliary.matching.dataset_matcher import DatasetMatcher

_T0 = np.datetime64("2025-01-01T00:00:00", "ns")
_SIDS = ["G01|L1|C", "G02|L1|C"]


def _orbits() -> xr.Dataset:
    """Orbits every 15 minutes, moving 1 m per second in X."""
    seconds = np.arange(0, 7200 + 1, 900)
    x = np.repeat(2e7 + seconds[:, None].astype(float), len(_SIDS), axis=1)
    ds = xr.Dataset(
        {
            "X": (("epoch", "sid"), x),
            "Y": (("epoch", "sid"), x),
            "Z": (("epoch", "sid"), x),
        },
        coords={"epoch": _T0 + seconds.astype("m8[s]"), "sid": _SIDS},
    )
    ds.attrs["interpolator_config"] = Sp3InterpolationStrategy(
        config=Sp3Config(use_velocities=False)
    ).to_attrs()
    return ds


def _file(seconds: np.ndarray) -> xr.Dataset:
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.ones((seconds.size, len(_SIDS))))},
        coords={"epoch": _T0 + seconds.astype("m8[s]"), "sid": _SIDS},
    )


def test_file_starting_with_a_gap_is_matched_at_its_sampling():
    # A 1 s file whose first two epochs are 30 minutes apart: the orbits
    # (15 min) are coarser than the file, so they are interpolated.
    seconds = np.concatenate([[0], np.arange(1800, 1901)])

    matched = DatasetMatcher().match_datasets(_file(seconds), ephemerides=_orbits())

    x = matched["ephemerides"]["X"].sel(epoch=_T0 + np.timedelta64(1850, "s"))
    np.testing.assert_allclose(x.values, 2e7 + 1850, atol=1.0)
