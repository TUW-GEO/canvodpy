"""Tests for loky/pickle serialization of flat batch processing arguments.

Verifies that all argument types passed to ``preprocess_with_hermite_aux``
via loky workers can round-trip through pickle.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from canvod.utils import testing


@pytest.fixture
def sample_task_args(tmp_path: Path) -> tuple:
    """Build a representative task_args tuple matching prepare_batch_tasks output."""
    from canvod.auxiliary.position.position import ECEFPosition

    rnx_file = tmp_path / "FANA00INK_R_20230010000_01D_30S_MO.rnx"
    rnx_file.touch()

    keep_vars: list[str] = ["C1C", "L1C", "S1C"]
    aux_zarr_path = tmp_path / "aux_hermite.zarr"
    aux_zarr_path.mkdir()

    receiver_position = ECEFPosition(
        x=testing.ECEF_X, y=testing.ECEF_Y, z=testing.ECEF_Z
    )
    receiver_name = "FANA"
    keep_sids: list[str] | None = ["G01", "G02", "G03"]

    return (
        rnx_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_name,
        keep_sids,
    )


class TestTaskSerialization:
    """Verify that task arguments survive pickle round-trip (loky default)."""

    def test_task_args_pickle_roundtrip(self, sample_task_args: tuple):
        """Full task_args tuple must survive pickle serialization."""
        data = pickle.dumps(sample_task_args)
        restored = pickle.loads(data)

        assert len(restored) == len(sample_task_args)
        # Path objects
        assert restored[0] == sample_task_args[0]
        assert restored[2] == sample_task_args[2]
        # Primitives
        assert restored[1] == sample_task_args[1]
        assert restored[4] == sample_task_args[4]
        assert restored[5] == sample_task_args[5]

    def test_ecef_position_pickle(self):
        """ECEFPosition (frozen dataclass) must be picklable."""
        from canvod.auxiliary.position.position import ECEFPosition

        pos = ECEFPosition(x=1.0, y=2.0, z=3.0)
        restored = pickle.loads(pickle.dumps(pos))

        assert restored.x == pos.x
        assert restored.y == pos.y
        assert restored.z == pos.z

    def test_path_pickle(self, tmp_path: Path):
        """Path objects must survive pickle (used for rnx_file, aux_zarr_path)."""
        p = tmp_path / "sub" / "file.rnx"
        restored = pickle.loads(pickle.dumps(p))
        assert restored == p

    def test_keep_sids_none_pickle(self, sample_task_args: tuple):
        """Task args with keep_sids=None must be picklable."""
        args = (*sample_task_args[:5], None)
        restored = pickle.loads(pickle.dumps(args))
        assert restored[5] is None


class TestSamplingIntervalFromFilename:
    """Verify fast sampling interval extraction from RINEX v3 long filenames."""

    @staticmethod
    def _parse(name: str) -> float | None:
        from canvodpy.orchestrator.processor import RinexDataProcessor

        return RinexDataProcessor._parse_sampling_interval_from_filename(name)

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("FANA01INK_R_20250020000_01D_05S_AA.rnx", 5.0),
            ("FANR01INK_R_20250010000_01D_30S_AA.rnx", 30.0),
            ("FANA00INK_R_20230010000_01D_01S_MO.rnx", 1.0),
            ("FANA01INK_R_20250020000_01D_15M_AA.rnx", 900.0),
            ("FANA01INK_R_20250020000_01D_01H_AA.rnx", 3600.0),
        ],
    )
    def test_standard_intervals(self, filename: str, expected: float):
        assert self._parse(filename) == expected

    def test_short_filename_returns_none(self):
        assert self._parse("data.rnx") is None

    def test_non_rinex_returns_none(self):
        assert self._parse("readme.txt") is None

    def test_full_path(self):
        result = self._parse("/data/rinex/FANA01INK_R_20250020000_01D_05S_AA.rnx")
        assert result == 5.0
