"""Fan-out vs single-file preprocessing on the real single-day test data.

Same comparison as ``test_reference_fanout.py``, but with a real RINEX v3.04
reference file and the committed Hermite aux cache (``aux_2025001.zarr``)
instead of mocked readers and synthetic ephemerides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import xarray as xr
from canvodpy.orchestrator.processor import (
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition
from canvod.readers.rinex.v3_04 import Rnxv3Obs

VALID = Path(__file__).parents[2] / "packages/canvod-readers/tests/test_data/valid"
AUX_ZARR = VALID / "aux_data/aux_2025001.zarr"
REF_DIR = VALID / "rinex_v3_04/01_Rosalia/01_reference/01_GNSS/01_raw/25001"
CAN_DIR = VALID / "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
FILES = [
    "ROSR01TUW_R_20250010000_15M_05S_AA.rnx",
    "ROSR01TUW_R_20250011200_15M_05S_AA.rnx",
]

# Set from the wall clock at each read.
_WALL_CLOCK_ATTRS = ("Created",)

pytestmark = pytest.mark.skipif(
    not (AUX_ZARR.exists() and REF_DIR.exists()), reason="test data not available"
)


def _position(fpath: Path) -> ECEFPosition:
    ds = Rnxv3Obs(fpath=fpath).to_ds(keep_data_vars=["SNR"], write_global_attrs=True)
    return ECEFPosition.from_ds_metadata(ds)


@pytest.mark.parametrize("fname", FILES)
def test_fanout_matches_single_file_path_on_real_data(fname):
    ref_file = REF_DIR / fname
    can_file = CAN_DIR / fname.replace("ROSR", "ROSA")
    positions = {
        "reference_01_canopy_01": _position(can_file),
        "reference_01_self": _position(ref_file),
    }
    keep = ["SNR"]

    _f, by_pairing, aux_new, sids_new = preprocess_reference_with_hermite_aux_fanout(
        ref_file, keep, AUX_ZARR, positions, "reference"
    )
    for name, pos in positions.items():
        _f, ds_old, aux_old, sids_old = preprocess_with_hermite_aux(
            ref_file, keep, AUX_ZARR, pos, "reference"
        )
        new = by_pairing[name]
        for ds in (new, ds_old):  # wall-clock attributes set per call
            for attr in _WALL_CLOCK_ATTRS:
                ds.attrs.pop(attr, None)
        xr.testing.assert_identical(new, ds_old)
        assert sids_new == sids_old
        assert aux_new.keys() == aux_old.keys()
