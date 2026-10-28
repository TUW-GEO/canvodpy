"""Tests for RinexNavProvider (theta/phi from RINEX navigation files)."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.auxiliary.ephemeris.parser import Sp3Parser
from canvod.auxiliary.ephemeris.provider import RinexNavProvider
from canvod.auxiliary.position.position import ECEFPosition
from canvod.auxiliary.position.spherical_coords import compute_spherical_coordinates

TEST_DATA = Path(__file__).parents[2] / "canvod-readers/tests/test_data/valid"
NAV_DIR = TEST_DATA / "rinex_v3_04_nav_data/02_canopy"
SP3_DIR = TEST_DATA / "aux_data/01_SP3"
DAY = np.datetime64("2025-01-01", "ns")

#: The canopy receiver of the test data (APPROX POSITION XYZ of its RINEX
#: observation files).
RECEIVER = ECEFPosition(x=4127445.9131, y=1206914.4723, z=4695541.0831)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not NAV_DIR.exists(), reason="test data not initialized"),
]


def _observations(epochs: np.ndarray, svs: list[str]) -> xr.Dataset:
    sids = [f"{sv}|L1|C" for sv in svs]
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.ones((epochs.size, len(sids))))},
        coords={"epoch": epochs, "sid": sids},
    )


def _lagrange(t: np.ndarray, y: np.ndarray, tq: np.ndarray, n: int = 10) -> np.ndarray:
    """``n``-point Lagrange interpolation of ``y`` (epoch, ...) at ``tq``."""
    lo = np.clip(np.searchsorted(t, tq) - n // 2, 0, t.size - n)
    idx = lo[:, None] + np.arange(n)[None, :]
    ts = t[idx]
    w = np.ones((tq.size, n))
    for j in range(n):
        for m in range(n):
            if m != j:
                w[:, j] *= (tq - ts[:, m]) / (ts[:, j] - ts[:, m])
    return np.einsum("tn,tn...->t...", w, y[idx])


def _cod_final_angles(epochs: np.ndarray, svs: list[str]):
    """theta, phi from COD final SP3 (three days), 10-point Lagrange."""
    sp3 = xr.concat(
        [
            Sp3Parser(SP3_DIR / f"COD0MGXFIN_{day}0000_01D_05M_ORB.SP3").parse()
            for day in ("2024366", "2025001", "2025002")
        ],
        dim="epoch",
    )
    sp3 = sp3.isel(epoch=np.unique(sp3.epoch.values, return_index=True)[1])
    sp3 = sp3.reindex(sv=svs)
    t = (sp3.epoch.values - DAY) / np.timedelta64(1, "s")
    tq = (epochs - DAY) / np.timedelta64(1, "s")
    xyz = [_lagrange(t, sp3[c].values, tq) for c in "XYZ"]
    _, theta, phi = compute_spherical_coordinates(*xyz, RECEIVER)
    return theta, phi


def _separation_deg(t1, p1, t2, p2) -> np.ndarray:
    c = np.cos(t1) * np.cos(t2) + np.sin(t1) * np.sin(t2) * np.cos(p1 - p2)
    return np.rad2deg(np.arccos(np.clip(c, -1, 1)))


def test_gps_angles_agree_with_cod_final() -> None:
    """GPS theta/phi within 0.001 deg of COD final (prototype: max 0.0001).

    The limit is a guardrail that catches regressions, not a scientific
    requirement (#567).
    """
    svs = [f"G{n:02d}" for n in range(1, 33)]
    epochs = DAY + np.arange(0, 86_400, 30) * np.timedelta64(1, "s")
    provider = RinexNavProvider(nav_files=sorted(NAV_DIR.glob("*.25p")))
    provider.preprocess_day("2025001", site_config=None)
    ds = provider.augment_dataset(_observations(epochs, svs), RECEIVER)

    theta_ref, phi_ref = _cod_final_angles(epochs, svs)
    sep = _separation_deg(ds.theta.values, ds.phi.values, theta_ref, phi_ref)
    both = np.isfinite(sep)
    assert both.sum() > 0.25 * sep.size  # about a third of GPS is in view
    assert np.nanmax(sep) < 0.001


def test_no_angles_outside_the_fit_interval() -> None:
    """Outside the fit interval of every record, a satellite has no angles.

    The first file of the day holds the G01 record of 02:00 with a fit
    interval of 4 hours: valid from 00:00 to 04:00 only.
    """
    epochs = DAY + np.arange(0, 6 * 3600, 30) * np.timedelta64(1, "s")
    provider = RinexNavProvider(nav_files=[NAV_DIR / "ract001a00.25p"])
    provider.preprocess_day("2025001", site_config=None)
    ds = provider.augment_dataset(_observations(epochs, ["G01"]), RECEIVER)
    after = ds.epoch.values > DAY + np.timedelta64(4, "h")
    assert np.isnan(ds.theta.values[after]).all()
    assert np.isfinite(ds.theta.values[~after]).any()
