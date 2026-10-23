"""Tests for SbfBroadcastProvider (theta/phi from SBF SatVisibility)."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.auxiliary.ephemeris.provider import SbfBroadcastProvider

EPOCHS = np.array(
    ["2025-01-01T00:00:00", "2025-01-01T00:00:05"], dtype="datetime64[ns]"
)
SIDS = np.array(["G01|L1|C", "C06|B1I|I", "S20|L1|C"])

SBF_FILE = (
    Path(__file__).parents[2]
    / "canvod-readers/tests/test_data/valid/sbf/01_Rosalia/02_canopy/25001"
    / "ROSA01TUW_R_20250010600_15M_05S_AA.sbf"
)


def _obs() -> xr.Dataset:
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.ones((2, 3)))},
        coords={"epoch": EPOCHS, "sid": SIDS},
    )


def _sbf_obs(source: list[list[int]]) -> xr.Dataset:
    theta = np.full((2, 3), 0.5)
    phi = np.full((2, 3), 1.0)
    return xr.Dataset(
        {
            "broadcast_theta": (("epoch", "sid"), theta),
            "broadcast_phi": (("epoch", "sid"), phi),
            "broadcast_angle_source": (
                ("epoch", "sid"),
                np.array(source, dtype=np.int8),
            ),
        },
        coords={"epoch": EPOCHS, "sid": SIDS},
    )


def test_only_ephemeris_angles_are_used() -> None:
    """Almanac (1) and unknown (-1) angles become NaN, ephemeris (2) stays."""
    meta = _sbf_obs([[2, 1, -1], [2, 2, 1]])
    ds = SbfBroadcastProvider().augment_dataset(
        _obs(), None, aux_datasets={"sbf_obs": meta}
    )
    expected = np.array([[0.5, np.nan, np.nan], [0.5, 0.5, np.nan]])
    np.testing.assert_array_equal(ds["theta"].values, expected)
    np.testing.assert_array_equal(np.isnan(ds["phi"].values), np.isnan(expected))


def test_raises_without_ephemeris_angles() -> None:
    meta = _sbf_obs([[1, 1, 1], [1, -1, 1]])
    with pytest.raises(ValueError, match="no ephemeris-based"):
        SbfBroadcastProvider().augment_dataset(
            _obs(), None, aux_datasets={"sbf_obs": meta}
        )


def test_raises_without_angle_source() -> None:
    meta = _sbf_obs([[2, 2, 2], [2, 2, 2]]).drop_vars("broadcast_angle_source")
    with pytest.raises(ValueError, match="broadcast_angle_source"):
        SbfBroadcastProvider().augment_dataset(
            _obs(), None, aux_datasets={"sbf_obs": meta}
        )


def test_rejects_non_sbf_canopy_format() -> None:
    with pytest.raises(ValueError, match="only SBF"):
        SbfBroadcastProvider(canopy_reader_format="rinex3")


@pytest.mark.skipif(not SBF_FILE.exists(), reason="SBF test data not available")
def test_real_file_masks_almanac_angles() -> None:
    """On real data, theta is set exactly where the receiver used ephemeris."""
    from canvod.readers.sbf.reader import SbfReader

    obs, aux = SbfReader(fpath=SBF_FILE).to_ds_and_auxiliary()
    meta = aux["sbf_obs"]
    ds = SbfBroadcastProvider().augment_dataset(obs, None, aux_datasets=aux)

    src = meta["broadcast_angle_source"].values
    assert (src == 1).any(), "test file should contain almanac-based angles"
    has_theta = ~np.isnan(ds["theta"].values)
    np.testing.assert_array_equal(has_theta, src == 2)
    np.testing.assert_array_equal(
        ds["theta"].values[has_theta], meta["broadcast_theta"].values[has_theta]
    )


@pytest.mark.skipif(not SBF_FILE.exists(), reason="SBF test data not available")
def test_canopy_file_geometry() -> None:
    """canopy_file reads the geometry from that file, not from aux_datasets."""
    from canvod.readers.sbf.reader import SbfReader

    obs, aux = SbfReader(fpath=SBF_FILE).to_ds_and_auxiliary()
    own = SbfBroadcastProvider().augment_dataset(obs.copy(), None, aux_datasets=aux)
    via_canopy = SbfBroadcastProvider(canopy_file=SBF_FILE).augment_dataset(
        obs.copy(), None, aux_datasets=None
    )
    xr.testing.assert_identical(own["theta"], via_canopy["theta"])
