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
SBF_DIR = TEST_DATA / "sbf/01_Rosalia/02_canopy/25001"
DAY = np.datetime64("2025-01-01", "ns")

#: The canopy receiver of the test data (APPROX POSITION XYZ of its RINEX
#: observation files).
RECEIVER = ECEFPosition(x=4127445.9131, y=1206914.4723, z=4695541.0831)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not NAV_DIR.exists(), reason="test data not initialized"),
]


#: One signal of each system for the test observations.
SIGNAL = {
    "G": "L1|C",
    "E": "E1|C",
    "R": "G1|C",
    "C": "B1I|I",
    "J": "L1|C",
    "S": "L1|C",
}


def _observations(epochs: np.ndarray, svs: list[str]) -> xr.Dataset:
    sids = [f"{sv}|{SIGNAL[sv[0]]}" for sv in svs]
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


def _broadcast_angles(epochs: np.ndarray, svs: list[str]) -> xr.Dataset:
    provider = RinexNavProvider(nav_files=sorted(NAV_DIR.glob("*.25p")))
    provider.preprocess_day("2025001", site_config=None)
    return provider.augment_dataset(_observations(epochs, svs), RECEIVER)


@pytest.mark.parametrize(
    "system, svs, limit",
    [
        ("E", [f"E{n:02d}" for n in range(1, 37)], 0.002),
        ("C", [f"C{n:02d}" for n in range(6, 63)], 0.002),
        ("R", [f"R{n:02d}" for n in range(1, 25)], 0.001),
    ],
)
def test_angles_agree_with_cod_final(system: str, svs: list[str], limit: float) -> None:
    """Galileo, BeiDou and GLONASS theta/phi within ``limit`` deg of COD final.

    Prototype: max 0.0011 deg (Galileo), 0.0000 deg (BeiDou, GLONASS). The
    limits are guardrails that catch regressions, not scientific
    requirements (#568, #569). COD final has no BeiDou GEO satellite of the
    day (C05).
    """
    epochs = DAY + np.arange(0, 86_400, 30) * np.timedelta64(1, "s")
    ds = _broadcast_angles(epochs, svs)

    theta_ref, phi_ref = _cod_final_angles(epochs, svs)
    sep = _separation_deg(ds.theta.values, ds.phi.values, theta_ref, phi_ref)
    assert np.isfinite(sep).sum() > 0.2 * sep.size
    assert np.nanmax(sep) < limit, system


@pytest.mark.skipif(not SBF_DIR.exists(), reason="SBF test data not initialized")
def test_beidou_geo_angles_agree_with_the_receiver() -> None:
    """C05, a GEO satellite, within 0.05 deg of the receiver's own angles.

    COD final has no C05, so the SatVisibility angles of the same receiver
    (SBF, from its broadcast ephemeris, 0.01 deg resolution) are the
    reference. Without the GEO rotations of BDS-SIS-ICD-B1I-3.0, Table 5-11,
    C05 is off by about 5 deg. The navigation files hold seven C05 records;
    around 16:00 none is within 2 hours, while the receiver still gives
    angles.
    """
    from canvod.readers.sbf.reader import SbfReader

    files = sorted(SBF_DIR.glob("*.sbf"))[::4]  # one per hour
    theta_sbf, phi_sbf, epochs = [], [], []
    for path in files:
        _, aux = SbfReader(fpath=path).to_ds_and_auxiliary(pad_global_sid=False)
        meta = aux["sbf_obs"]
        c05 = [i for i, sid in enumerate(meta.sid.values) if str(sid)[:3] == "C05"]
        if not c05:
            continue
        source = meta["broadcast_angle_source"].values[:, c05[0]]
        ok = source == 2  # from the broadcast ephemeris
        theta_sbf.append(meta["broadcast_theta"].values[ok, c05[0]])
        phi_sbf.append(meta["broadcast_phi"].values[ok, c05[0]])
        epochs.append(meta.epoch.values[ok])
    epochs = np.concatenate(epochs).astype("datetime64[ns]")
    assert epochs.size > 1000
    ds = _broadcast_angles(epochs, ["C05"])

    sep = _separation_deg(
        ds.theta.values[:, 0],
        ds.phi.values[:, 0],
        np.concatenate(theta_sbf),
        np.concatenate(phi_sbf),
    )
    assert np.isfinite(sep).sum() > 0.8 * sep.size
    assert np.nanmax(sep) < 0.05


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


def test_qzss_orbits_follow_the_gps_algorithm_within_two_hours() -> None:
    """A QZSS record gives the orbit a GPS record with the same elements
    gives (IS-QZSS-PNT-005, 5.6.1), valid for 1 hour either side of its
    time of ephemeris (fit interval 2 hours, Table 4.1.1-2)."""
    from canvod.readers.rinex.nav import read_rinex_nav

    from canvod.auxiliary.ephemeris.broadcast import broadcast_orbits

    gps = read_rinex_nav([NAV_DIR / "ract001a00.25p"])["G"]
    g01 = gps.isel(record=np.flatnonzero(gps.sv.values == "G01")[:1])
    j01 = g01.assign_coords(sv=("record", ["J01"])).drop_vars("fit_interval")
    j01["fit_interval_flag"] = ("record", [0.0])

    grid = broadcast_orbits({"G": g01, "J": j01}, DAY)

    toe = DAY + np.timedelta64(2, "h")  # G01 record of 02:00
    hours = (grid.epoch.values - toe) / np.timedelta64(1, "h")
    within = np.abs(hours) <= 1
    for name in ("X", "Vx"):
        np.testing.assert_array_equal(
            grid[name].sel(sv="J01").values[within],
            grid[name].sel(sv="G01").values[within],
        )
    assert np.isnan(grid["X"].sel(sv="J01").values[~within]).all()
    assert np.isfinite(grid["X"].sel(sv="G01").values[np.abs(hours) <= 2]).all()


def test_no_glonass_angles_beyond_15_minutes_of_a_record() -> None:
    """A GLONASS record is used within 15 minutes of its time (ICD GLONASS,
    A.3.1.2). The first file of the day holds one R20 record, of 00:15 UTC
    (00:15:18 GPS time): grid times 00:05 to 00:30 only.
    """
    epochs = DAY + np.arange(0, 2 * 3600, 30) * np.timedelta64(1, "s")
    provider = RinexNavProvider(nav_files=[NAV_DIR / "ract001a00.25p"])
    provider.preprocess_day("2025001", site_config=None)
    ds = provider.augment_dataset(_observations(epochs, ["R20"]), RECEIVER)
    after = ds.epoch.values > DAY + np.timedelta64(35, "m")
    assert np.isnan(ds.theta.values[after]).all()
    assert np.isfinite(ds.theta.values[~after]).any()


#: Orbital slots of the EGNOS satellites, deg East (EGNOS Service Notice 33,
#: 2025-08-08, Table 1: ASTRA SES-5 PRN 136, ASTRA 5-B PRN 123, Eutelsat 5
#: West B PRN 121; RINEX numbers SBAS satellites PRN - 100).
EGNOS_SLOTS = {"S36": 5.0, "S23": 23.5, "S21": -5.0}

#: Radius of the geostationary orbit, m: (mu / omega^2)^(1/3) with the
#: WGS 84 values of IS-GPS-200N, Table 20-IV.
GEO_RADIUS_M = (3.986005e14 / 7.2921151467e-5**2) ** (1 / 3)


def test_sbas_angles_agree_with_the_published_orbital_slots() -> None:
    """EGNOS theta/phi within 0.01 deg of the satellites' published slots.

    COD final has no SBAS satellite. The reference is a satellite at rest on
    the equator at the geostationary radius and the slot longitude of EGNOS
    Service Notice 33, Table 1. EGNOS broadcasts the nominal slot (URA index
    15, RINEX 3.05, Section 5.4.4). Measured: max 0.0002 deg; the limit is
    a guardrail, not a scientific requirement (#570). The files hold no S36
    record from 07:27 to 10:37.
    """
    svs = ["S23", "S36"]
    epochs = DAY + np.arange(0, 86_400, 30) * np.timedelta64(1, "s")
    ds = _broadcast_angles(epochs, svs)

    lon = np.deg2rad([EGNOS_SLOTS[sv] for sv in svs])
    xyz = [
        np.broadcast_to(c, (epochs.size, len(svs)))
        for c in (
            GEO_RADIUS_M * np.cos(lon),
            GEO_RADIUS_M * np.sin(lon),
            np.zeros(len(svs)),
        )
    ]
    _, theta_ref, phi_ref = compute_spherical_coordinates(*xyz, RECEIVER)
    sep = _separation_deg(ds.theta.values, ds.phi.values, theta_ref, phi_ref)
    assert np.isfinite(sep).mean() > 0.9
    assert np.nanmax(sep) < 0.01


def test_sbas_positions_follow_velocity_and_acceleration() -> None:
    """An SBAS record moves its position with its velocity and acceleration
    from its time of clock (RINEX 3.05, Table A16).

    Worked example, 300 s after the record: x = 42000 km + 0.001 km/s * 300 s
    + 1e-7 km/s2 * (300 s)^2 / 2 = 42000304.5 m; vx = 1 m/s + 1e-4 m/s2 *
    300 s = 1.03 m/s.
    """
    from canvod.auxiliary.ephemeris.broadcast import broadcast_orbits

    record = {name: ("record", [0.0]) for name in ("y", "vy", "ay", "z", "vz", "az")}
    sbas = xr.Dataset(
        record
        | {"x": ("record", [42_000.0]), "vx": ("record", [0.001])}
        | {"ax": ("record", [1e-7])},
        coords={"sv": ("record", ["S23"]), "toc": ("record", [DAY])},
    )
    grid = broadcast_orbits({"S": sbas}, DAY).sel(sv="S23")
    at = grid.sel(epoch=DAY + np.timedelta64(300, "s"))
    np.testing.assert_allclose(at.X.item(), 42_000_304.5, rtol=0, atol=1e-6)
    np.testing.assert_allclose(at.Vx.item(), 1.03, rtol=0, atol=1e-9)


def test_no_sbas_angles_beyond_six_minutes_of_a_record() -> None:
    """An SBAS record is used within 360 s of its time of clock, the time-out
    of the GEO navigation message. The files of the day hold S21 records
    from 11:22:24 to 18:16:48 only.
    """
    epochs = DAY + np.arange(0, 86_400, 30) * np.timedelta64(1, "s")
    ds = _broadcast_angles(epochs, ["S21"])
    first = DAY + np.timedelta64(11 * 3600 + 22 * 60 + 24 - 360, "s")
    last = DAY + np.timedelta64(18 * 3600 + 16 * 60 + 48 + 360, "s")
    outside = (ds.epoch.values < first) | (ds.epoch.values > last)
    assert np.isnan(ds.theta.values[outside]).all()
    assert np.isfinite(ds.theta.values[~outside]).any()
