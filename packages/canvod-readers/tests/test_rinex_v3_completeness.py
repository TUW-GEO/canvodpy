"""Epoch completeness check of the RINEX v3 reader (``completeness_mode``)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from canvod.readers.gnss_specs.exceptions import MissingEpochError
from canvod.readers.rinex.v3_04 import Rnxv3Obs

RINEX_FILE = (
    Path(__file__).parent
    / "test_data/valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001"
    / "ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)


@pytest.fixture
def epoch_blocks() -> tuple[list[str], list[list[str]]]:
    """Header lines and one list of lines per epoch of a 15M_05S file."""
    if not RINEX_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_FILE}")
    lines = RINEX_FILE.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    blocks: list[list[str]] = []
    for line in lines[end:]:
        if line.startswith(">"):
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return lines[:end], blocks


def _write(path: Path, header: list[str], blocks: list[list[str]]) -> Path:
    path.write_text("".join(header) + "".join("".join(b) for b in blocks))
    return path


def _retimed(blocks: list[list[str]], step_s: float) -> list[list[str]]:
    """The same epochs, ``step_s`` seconds apart from 19:45:00."""
    t0 = datetime(2025, 1, 1, 19, 45)
    out = []
    for k, block in enumerate(blocks):
        t = t0 + timedelta(seconds=step_s * k)
        sec = f"{t.second + t.microsecond / 1e6:11.7f}"
        line = (
            f"> {t.year:4d} {t.month:02d} {t.day:02d} {t.hour:02d} {t.minute:02d}{sec}"
        )
        out.append([line + block[0][29:], *block[1:]])
    return out


@pytest.mark.parametrize("step_s", [3, 20, 0.5])
def test_any_sampling_interval_is_read(tmp_path, epoch_blocks, step_s):
    """Not only the sampling intervals of one receiver vendor."""
    header, blocks = epoch_blocks
    path = _write(tmp_path / "f.rnx", header, _retimed(blocks, step_s))
    assert len(Rnxv3Obs(fpath=path).get_epoch_record_batches()) == len(blocks)


def test_complete_file_passes(epoch_blocks):
    Rnxv3Obs(
        fpath=RINEX_FILE,
        expected_dump_interval="15 min",
        expected_sampling_interval="5 s",
    )


def test_gap_is_found_without_expected_intervals(tmp_path, epoch_blocks):
    header, blocks = epoch_blocks
    path = _write(tmp_path / "f.rnx", header, blocks[:50] + blocks[60:])
    with pytest.raises(MissingEpochError, match="10 of 180 epochs are missing"):
        Rnxv3Obs(fpath=path)


def test_file_cut_short_needs_the_expected_length(tmp_path, epoch_blocks):
    """Epochs missing at the end show only against the intended length."""
    header, blocks = epoch_blocks
    path = _write(tmp_path / "f.rnx", header, blocks[:150])
    Rnxv3Obs(fpath=path)
    with pytest.raises(MissingEpochError, match="30 of 180 epochs are missing"):
        Rnxv3Obs(
            fpath=path,
            expected_dump_interval="15 min",
            expected_sampling_interval="5 s",
        )


def test_warn_mode_keeps_the_file(tmp_path, epoch_blocks):
    header, blocks = epoch_blocks
    path = _write(tmp_path / "f.rnx", header, blocks[:50] + blocks[60:])
    with pytest.warns(RuntimeWarning, match="10 of 180 epochs are missing"):
        obs = Rnxv3Obs(fpath=path, completeness_mode="warn")
    assert obs.to_ds().sizes["epoch"] == 170
