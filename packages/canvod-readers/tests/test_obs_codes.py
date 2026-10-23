"""Tests for the RINEX observation code <-> signal ID mapping."""

from pathlib import Path

import pytest

from canvod.readers.gnss_specs.obs_codes import obs_code_for_sid, sid_for_obs_code
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.readers.rinex.v2_11 import Rnxv2Header
from canvod.readers.rinex.v3_04 import Rnxv3Obs

TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_V3_FILE = (
    TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
    "/ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)
RINEX_V2_FILE = (
    TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/01_reference/25001"
    "/MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
)


@pytest.mark.parametrize(
    ("sv", "obs_code", "sid"),
    [
        ("G01", "S1C", "G01|L1|C"),
        ("G01", "S2W", "G01|L2|W"),
        ("E05", "S1C", "E05|E1|C"),
        ("E05", "S5Q", "E05|E5a|Q"),
        ("E05", "S7Q", "E05|E5b|Q"),
        ("C08", "S2I", "C08|B1I|I"),
        ("R03", "S1C", "R03|G1|C"),
        ("S23", "S1C", "S23|L1|C"),
    ],
)
def test_rinex3_codes(sv, obs_code, sid):
    assert sid_for_obs_code(sv, obs_code) == sid
    assert obs_code_for_sid(sid) == obs_code


@pytest.mark.parametrize(
    ("sv", "obs_code", "sid", "back"),
    [
        ("G01", "S1", "G01|L1|u", "S1"),
        ("G01", "C1", "G01|L1|C", "C1C"),
        ("G01", "P2", "G01|L2|p", "C2"),
        ("G01", "C2", "G01|L2|l", "C2"),
        ("R03", "P1", "R03|G1|P", "C1P"),
        ("S23", "S1", "S23|L1|C", "S1C"),
    ],
)
def test_rinex2_codes(sv, obs_code, sid, back):
    """RINEX 2 codes resolve as in the v2.11 reader; markers map back without code."""
    assert sid_for_obs_code(sv, obs_code) == sid
    assert obs_code_for_sid(sid, obs_type=back[0]) == back


def test_obs_type_selects_the_observable():
    assert obs_code_for_sid("G01|L1|C", obs_type="L") == "L1C"


@pytest.mark.parametrize(
    ("sv", "obs_code"),
    [("G01", "S9C"), ("G01", "S"), ("X01", "S1C")],
)
def test_unknown_codes_raise(sv, obs_code):
    with pytest.raises(ValueError):
        sid_for_obs_code(sv, obs_code)


@pytest.mark.parametrize("sid", ["G01|E1|C", "G01|L1", "X01|L1|C"])
def test_unknown_sids_raise(sid):
    with pytest.raises(ValueError):
        obs_code_for_sid(sid)


def test_same_sids_as_the_rinex3_reader():
    """Every sid the v3.04 reader builds from a header follows the mapping."""
    if not RINEX_V3_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_V3_FILE}")
    reader = Rnxv3Obs(fpath=RINEX_V3_FILE)
    sids, _ = reader._precompute_sids_from_header()
    for sid in sids:
        sv = sid.split("|")[0]
        assert sid_for_obs_code(sv, obs_code_for_sid(sid)) == sid


def test_same_codes_as_the_rinex2_reader():
    """The v2.11 header resolves its codes with the same rules."""
    if not RINEX_V2_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_V2_FILE}")
    header = Rnxv2Header.from_file(RINEX_V2_FILE)
    bands = SignalIDMapper().SYSTEM_BANDS
    for system, codes in header.obs_codes_per_system.items():
        for v2_code, code in zip(header.obs_types, codes, strict=True):
            if v2_code[1] not in bands[system]:
                # No band for this frequency: the reader builds no sid either
                with pytest.raises(ValueError, match="has no band"):
                    sid_for_obs_code(f"{system}01", v2_code)
                continue
            sid = sid_for_obs_code(f"{system}01", v2_code)
            assert sid.split("|")[2] == code[2:]
