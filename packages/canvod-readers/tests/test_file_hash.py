"""Every reader computes the same file hash, the one the stores record."""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import pytest

from canvod.readers.gnss_specs import utils as old_utils
from canvod.readers.nmea.v4_00 import NmeaObs
from canvod.readers.rinex.v2_11 import Rnxv2Obs
from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.readers.sbf.reader import SbfReader
from canvod.utils.tools import bytes_hash, file_hash

TEST_DATA_DIR = Path(__file__).parent / "test_data" / "valid"

CASES = [
    (
        Rnxv3Obs,
        "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/"
        "ROSA01TUW_R_20250010000_15M_05S_AA.rnx",
    ),
    (
        Rnxv2Obs,
        "rinex_v2_11/02_Moflux/01_reference/25001/MOZR01CAL_R_20250010000_01H_15S_AA.rnx",
    ),
    (
        SbfReader,
        "sbf/01_Rosalia/01_reference/25001/ROSR01TUW_R_20250010000_15M_05S_AA.sbf",
    ),
    (
        NmeaObs,
        "nmea/01_Rosalia/01_reference/ROSR01TUW_R_20250010000_15M_05S_AA.nmea",
    ),
]


@pytest.mark.parametrize(
    ("reader_cls", "relpath"), CASES, ids=[c[0].__name__ for c in CASES]
)
def test_reader_hash_is_the_shared_file_hash(reader_cls, relpath):
    path = TEST_DATA_DIR / relpath
    if not path.exists():
        pytest.skip(f"Test file not found: {path}")
    # Computed independently: the first 16 hex digits of the SHA-256.
    expected = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    assert reader_cls(fpath=path).file_hash == expected
    assert file_hash(path) == expected
    assert bytes_hash(path.read_bytes()) == expected


def test_old_helpers_warn_and_delegate(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"canvod")
    with pytest.warns(FutureWarning, match="canvod.utils.tools.file_hash"):
        assert old_utils.file_hash(path) == file_hash(path)
    with pytest.warns(FutureWarning, match="canvod.utils.tools.isfloat"):
        assert old_utils.isfloat("3.5")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        file_hash(path)
