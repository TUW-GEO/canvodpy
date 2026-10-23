"""One decoder behind every SbfReader output, and the decoding it does.

``to_ds()``, ``to_ds_and_auxiliary()`` and ``iter_epochs()`` share one
decoder and must give the same values. The decoder must:

- pair each MeasEpoch block with the other blocks of the same receiver time
  stamp (RefGuide-4.14.0, Section 4.1.3, p.253);
- take the GLONASS frequency number from the MeasEpoch ObsInfo field
  (p.262), which needs no ChannelStatus block;
- drop SVID 62, GLONASS satellites whose slot number is unknown (p.255);
- match MeasExtra entries to observations by epoch, receiver channel and
  signal, with the extended signal number in MeasExtra Misc bits 3-7 (p.265).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import sbf_parser
import xarray as xr

from canvod.readers.sbf._registry import SIGNAL_TABLE, decode_svid
from canvod.readers.sbf.reader import (
    SbfReader,
    _decode_observations,
    _iter_epoch_groups,
)

SBF_DIR = Path(__file__).parent / "test_data" / "valid" / "sbf"
SBF_FILES = sorted(SBF_DIR.rglob("*.sbf")) if SBF_DIR.exists() else []
# Canopy file with SVID 62 observations
CANOPY_FILE = (
    SBF_DIR / "01_Rosalia/02_canopy/25001/ROSA01TUW_R_20250010600_15M_05S_AA.sbf"
)
REFERENCE_FILE = (
    SBF_DIR / "01_Rosalia/01_reference/25001/ROSR01TUW_R_20250010000_15M_05S_AA.sbf"
)
_RAW_VARS = ["SNR_raw", "Pseudorange_unsmoothed", "Pseudorange_raw", "Phase_raw"]

needs_canopy = pytest.mark.skipif(
    not CANOPY_FILE.exists(), reason="SBF test data not available"
)


def _assert_same(a: xr.Dataset, b: xr.Dataset, what: str) -> None:
    assert set(a.data_vars) == set(b.data_vars), f"{what}: data variables differ"
    assert set(a.coords) == set(b.coords), f"{what}: coordinates differ"
    for name in sorted(set(a.coords) | set(a.data_vars)):
        np.testing.assert_array_equal(
            a[name].values, b[name].values, err_msg=f"{what}: {name} differs"
        )


def _raw_blocks(fpath: Path, name: str) -> dict[int, dict]:
    """Blocks of one type keyed by TOW, read directly with sbf_parser."""
    return {
        int(data["TOW"]): data
        for block, data in sbf_parser.SbfParser().read(str(fpath))
        if block == name
    }


# ---------------------------------------------------------------------------
# Parity of the outputs
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not SBF_FILES, reason="SBF test data not available")
@pytest.mark.parametrize("fpath", SBF_FILES, ids=[p.name for p in SBF_FILES])
def test_to_ds_matches_combined_scan(fpath: Path) -> None:
    obs_std = SbfReader(fpath=fpath).to_ds(pad_global_sid=False, strip_fillval=False)
    obs_comb, aux = SbfReader(fpath=fpath).to_ds_and_auxiliary(
        pad_global_sid=False, strip_fillval=False, store_raw_observables=True
    )
    _assert_same(obs_std, obs_comb.drop_vars(_RAW_VARS), "obs")
    np.testing.assert_array_equal(aux["sbf_obs"].sid.values, obs_comb.sid.values)


@needs_canopy
def test_to_ds_matches_combined_scan_padded() -> None:
    obs_std = SbfReader(fpath=CANOPY_FILE).to_ds()
    obs_comb, aux = SbfReader(fpath=CANOPY_FILE).to_ds_and_auxiliary(
        store_raw_observables=False
    )
    _assert_same(obs_std, obs_comb, "obs")
    np.testing.assert_array_equal(aux["sbf_obs"].sid.values, obs_comb.sid.values)


@needs_canopy
@pytest.mark.parametrize("fpath", [CANOPY_FILE, REFERENCE_FILE], ids=["canopy", "ref"])
def test_iter_epochs_matches_to_ds(fpath: Path) -> None:
    ds = SbfReader(fpath=fpath).to_ds(pad_global_sid=False, strip_fillval=False)
    col = {sid: i for i, sid in enumerate(ds.sid.values.tolist())}
    n_checked = 0
    for e, epoch in enumerate(SbfReader(fpath=fpath).iter_epochs()):
        assert (
            np.datetime64(epoch.timestamp.replace(tzinfo=None), "ns")
            == (ds.epoch.values[e])
        )
        for obs in epoch.observations:
            sig = SIGNAL_TABLE[obs.signal_num]
            j = col[f"{obs.system}{obs.prn:02d}|{sig.band}|{sig.code}"]
            for var, value in (
                ("SNR", obs.cn0),
                ("Pseudorange", obs.pseudorange),
                ("Doppler", obs.doppler),
            ):
                expected = np.nan if value is None else value.magnitude
                np.testing.assert_allclose(
                    ds[var].values[e, j], expected, rtol=1e-6, err_msg=var
                )
            np.testing.assert_allclose(
                ds["Phase"].values[e, j],
                np.nan if obs.phase_cycles is None else obs.phase_cycles,
                rtol=1e-12,
            )
            n_checked += 1
    assert n_checked > 1000


# ---------------------------------------------------------------------------
# Bug fixes, checked against the raw blocks of a real file
# ---------------------------------------------------------------------------


@needs_canopy
def test_satvisibility_from_same_epoch() -> None:
    """broadcast_theta/phi come from the SatVisibility block of the same TOW."""
    _, aux = SbfReader(fpath=CANOPY_FILE).to_ds_and_auxiliary(
        pad_global_sid=False, strip_fillval=False
    )
    meta = aux["sbf_obs"]
    satvis = _raw_blocks(CANOPY_FILE, "SatVisibility")
    meas = _raw_blocks(CANOPY_FILE, "MeasEpoch")
    tows = sorted(meas)
    sv_of_sid = meta.sv.values.tolist()
    n_checked = 0
    for e, tow in enumerate(tows):
        for sat in satvis[tow]["SatInfo"]:
            svid = int(sat["SVID"])
            if svid in (0, 62) or int(sat["Elevation"]) == -32768:
                continue
            system, prn = decode_svid(svid)
            sv = f"{system}{prn:02d}"
            for s, sv_s in enumerate(sv_of_sid):
                if sv_s != sv:
                    continue
                expected = np.deg2rad(90.0 - int(sat["Elevation"]) * 0.01)
                assert meta["broadcast_theta"].values[e, s] == pytest.approx(
                    expected, abs=1e-6
                )
                n_checked += 1
    assert n_checked > 1000


@needs_canopy
def test_cn0_highres_from_same_epoch() -> None:
    """SNR - SNR_raw is the CN0HighRes of the MeasExtra block of the same TOW."""
    obs, _ = SbfReader(fpath=CANOPY_FILE).to_ds_and_auxiliary(
        pad_global_sid=False, strip_fillval=False
    )
    extra = _raw_blocks(CANOPY_FILE, "MeasExtra")
    meas = _raw_blocks(CANOPY_FILE, "MeasEpoch")
    col = {sid: i for i, sid in enumerate(obs.sid.values.tolist())}
    diff = obs["SNR"].values - obs["SNR_raw"].values
    n_checked = 0
    for e, tow in enumerate(sorted(meas)):
        # Type1 GPS L1 C/A (signal 0) only: unambiguous channel → sid
        sv_of_channel = {
            int(t1["RxChannel"]): int(t1["SVID"])
            for t1 in meas[tow]["Type_1"]
            if int(t1["Type"]) & 0x1F == 0
        }
        for ch in extra[tow]["MeasExtraChannel"]:
            if int(ch["Type"]) & 0x1F != 0:
                continue
            svid = sv_of_channel.get(int(ch["RxChannel"]))
            if svid is None:
                continue
            sid = f"G{svid:02d}|L1|C"
            if sid not in col or np.isnan(diff[e, col[sid]]):
                continue
            assert diff[e, col[sid]] == pytest.approx(
                (int(ch["Misc"]) & 0x07) * 0.03125, abs=1e-6
            )
            n_checked += 1
    assert n_checked > 1000


@needs_canopy
def test_glonass_frequency_matches_channelstatus() -> None:
    """GLONASS sid frequencies agree with the ChannelStatus FreqNr."""
    ds = SbfReader(fpath=CANOPY_FILE).to_ds(pad_global_sid=False, strip_fillval=False)
    freq_nr: dict[str, int] = {}
    for data in _raw_blocks(CANOPY_FILE, "ChannelStatus").values():
        for sat in data["SatInfo"]:
            svid = int(sat["SVID"])
            if 38 <= svid <= 61:
                freq_nr[f"R{svid - 37:02d}"] = int(sat["FreqNr"])
    n_checked = 0
    for sid, f_mhz in zip(ds.sid.values, ds.freq_center.values, strict=True):
        sv, band, _ = sid.split("|")
        if not sv.startswith("R") or band not in ("G1", "G2"):
            continue
        k = freq_nr[sv] - 8
        expected = 1602.0 + k * 9 / 16 if band == "G1" else 1246.0 + k * 7 / 16
        assert f_mhz == pytest.approx(expected, abs=1e-6), sid
        n_checked += 1
    assert n_checked > 10


@needs_canopy
def test_svid_62_dropped() -> None:
    """SVID 62 is in the raw file but in none of the outputs."""
    meas = _raw_blocks(CANOPY_FILE, "MeasEpoch")
    assert any(int(t1["SVID"]) == 62 for m in meas.values() for t1 in m["Type_1"])
    reader = SbfReader(fpath=CANOPY_FILE)
    obs, aux = reader.to_ds_and_auxiliary(pad_global_sid=False, strip_fillval=False)
    assert not any(sv == "R00" for sv in obs.sv.values)
    assert not any(sv == "R00" for sv in aux["sbf_obs"].sv.values)
    assert all(
        o.svid != 62 for epoch in reader.iter_epochs() for o in epoch.observations
    )


@needs_canopy
def test_epoch_groups_share_time_stamp() -> None:
    """Every block of a group has the TOW of its MeasEpoch block."""
    for group in _iter_epoch_groups(CANOPY_FILE):
        tow = int(group["MeasEpoch"]["TOW"])
        assert all(int(block["TOW"]) == tow for block in group.values())


# ---------------------------------------------------------------------------
# Decoder on synthetic blocks
# ---------------------------------------------------------------------------


def _type1(svid: int, rx_channel: int, type_byte: int, obs_info: int, type2=()) -> dict:
    return {
        "RxChannel": rx_channel,
        "Type": type_byte,
        "SVID": svid,
        "Misc": 5,
        "CodeLSB": 0,
        "Doppler": 0,
        "CarrierLSB": 0,
        "CarrierMSB": 0,
        "CN0": 120,
        "LockTime": 10,
        "ObsInfo": obs_info,
        "N2": len(type2),
        "Type_2": list(type2),
    }


def _type2(type_byte: int, obs_info: int) -> dict:
    return {
        "Type": type_byte,
        "LockTime": 10,
        "CN0": 100,
        "OffsetMSB": 0,
        "CarrierMSB": 0,
        "ObsInfo": obs_info,
        "CodeOffsetLSB": 0,
        "CarrierLSB": 0,
        "DopplerOffsetLSB": 0,
    }


def _extra(rx_channel: int, type_byte: int, misc: int) -> dict:
    return {
        "RxChannel": rx_channel,
        "Type": type_byte,
        "MPCorrection ": 1000,
        "SmoothingCorr": 0,
        "CodeVar": 1,
        "CarrierVar": 1,
        "LockTime": 10,
        "CumLossCont": 0,
        "CarMPCorr": 0,
        "Info": 0,
        "Misc": misc,
    }


def test_decoder_freq_nr_from_obs_info() -> None:
    """Type2 GLONASS signals take FreqNr from their Type1 ObsInfo."""
    # GLONASS R01 (SVID 38), L1CA (8) with FreqNr 9 and L2CA (11) as Type2
    group = {
        "MeasEpoch": {
            "Type_1": [_type1(38, 4, 8, 9 << 3, [_type2(11, 0)])],
        }
    }
    obs = _decode_observations([group])
    np.testing.assert_array_equal(obs.freq_nr, [9, 9])
    np.testing.assert_array_equal(obs.sig_num, [8, 11])


def test_decoder_drops_svid_62_and_dnu() -> None:
    group = {
        "MeasEpoch": {
            "Type_1": [
                _type1(62, 1, 8, 9 << 3),
                _type1(0, 2, 0, 0),
                _type1(5, 3, 0, 0),
            ]
        }
    }
    obs = _decode_observations([group])
    np.testing.assert_array_equal(obs.svid, [5])


def test_decoder_matches_extended_signal_via_misc() -> None:
    """MeasExtra extended signal numbers are in Misc bits 3-7, not Info."""
    # QZSS L1C (signal 32): SigIdxLo 31, ObsInfo bits 3-7 = 0. Second
    # QZSS signal L1S (33) on the same channel: ObsInfo bits 3-7 = 1.
    group = {
        "MeasEpoch": {
            "Type_1": [_type1(181, 7, 31, 0, [_type2(31, 1 << 3)])],
        },
        "MeasExtra": {
            "MeasExtraChannel": [
                _extra(7, 31, (0 << 3) | 2),  # signal 32, CN0HighRes 2
                _extra(7, 31, (1 << 3) | 5),  # signal 33, CN0HighRes 5
            ]
        },
    }
    obs = _decode_observations([group])
    np.testing.assert_array_equal(obs.sig_num, [32, 33])
    np.testing.assert_allclose(obs.cn0_highres_dbhz, [2 * 0.03125, 5 * 0.03125])
