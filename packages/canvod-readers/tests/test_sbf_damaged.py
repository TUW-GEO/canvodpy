"""SBF files with damaged blocks, and blocks sbf-parser can't decode safely.

sbf-parser 1.0.3 crashes the Python process on a block header with Length
0 or 4, and on a DiffCorrIn block (canvodpy #678). The reader must hand it
neither; these tests never pass such bytes to sbf-parser themselves.
"""

from __future__ import annotations

import binascii
import struct
from pathlib import Path

import pytest
from sbf_parser.block_structure import BLOCKNAMES
from structlog.testing import capture_logs

from canvod.readers.gnss_specs.exceptions import SbfError
from canvod.readers.sbf._blocks import IntactBlocks
from canvod.readers.sbf.reader import _EPOCH_BLOCKS, SbfReader

SBF_FILE = (
    Path(__file__).parent
    / "test_data/valid/sbf/01_Rosalia/02_canopy/25001/ROSA01TUW_R_20250010000_15M_05S_AA.sbf"
)
#: Name of the copies the tests write: the test persona's site
#: (canvod.utils.testing)
NAME = "FANA01INK_R_20250010000_15M_05S_AA.sbf"
MEAS_EPOCH = 4027
DIFF_CORR_IN = 5919


def _block(number: int, body: bytes) -> bytes:
    """An intact SBF block: sync, CRC, ID, Length, body padded to 4 bytes."""
    body += b"\x00" * (-(8 + len(body)) % 4)
    id_length = struct.pack("<HH", number, 8 + len(body))
    return (
        b"$@"
        + struct.pack("<H", binascii.crc_hqx(id_length + body, 0))
        + id_length
        + body
    )


def _with_length(block: bytes, length: int) -> bytes:
    """The block with its Length field set to ``length`` (CRC left as it was)."""
    return block[:6] + struct.pack("<H", length) + block[8:]


def _diff_corr_in() -> bytes:
    """A valid DiffCorrIn block carrying the start of an RTCM 3 frame."""
    # TOW, WNc, Mode 2 (RTCM 3), Source (RefGuide-4.14.0, DiffCorrIn block)
    return _block(
        DIFF_CORR_IN, struct.pack("<IHBB", 0, 0, 2, 0) + bytes.fromhex("d300133ed00003")
    )


@pytest.mark.parametrize("length", [0, 4])
def test_a_header_with_length_0_or_4_is_dropped(length: int) -> None:
    good = _block(MEAS_EPOCH, b"\x01" * 16)
    raw = good + _with_length(_block(MEAS_EPOCH, b"\x02" * 16), length) + good

    blocks = IntactBlocks(raw, frozenset({MEAS_EPOCH}))

    assert list(blocks) == [good, good]
    assert blocks.n_intact == 2
    assert blocks.dropped_stretches == 1
    assert blocks.dropped_bytes == 24  # the whole damaged block


def test_a_block_of_a_type_not_read_is_never_kept() -> None:
    good = _block(MEAS_EPOCH, b"\x01" * 16)

    blocks = IntactBlocks(good + _diff_corr_in() + good, frozenset({MEAS_EPOCH}))

    assert list(blocks) == [good, good]
    assert blocks.n_intact == 3
    assert blocks.dropped_bytes == 0


def test_the_walk_goes_only_as_far_as_it_is_read() -> None:
    good = _block(MEAS_EPOCH, b"\x01" * 16)
    blocks = IntactBlocks(good + b"\x00" * 12 + good, frozenset({MEAS_EPOCH}))

    walk = iter(blocks)
    assert next(walk) == good
    assert blocks.dropped_bytes == 0  # the damage after the first block

    assert list(walk) == [good]
    assert blocks.dropped_bytes == 12


def test_every_block_the_reader_reads_is_known_to_sbf_parser() -> None:
    # the reader takes block numbers from sbf-parser's internal block table
    assert _EPOCH_BLOCKS | {"ReceiverSetup"} <= set(BLOCKNAMES)


@pytest.fixture(scope="module")
def sbf_bytes() -> bytes:
    if not SBF_FILE.exists():
        pytest.skip(f"SBF test file not found: {SBF_FILE}")
    return SBF_FILE.read_bytes()


def _n_epochs(path: Path) -> int:
    return sum(1 for _ in SbfReader(fpath=path).iter_epochs())


def _write(tmp_path: Path, raw: bytes) -> Path:
    path = tmp_path / NAME
    path.write_bytes(raw)
    return path


def _first_block(raw: bytes, number: int) -> int:
    """Offset of the first block with this number in a clean file."""
    start = 0
    while True:
        _, block_id, length = struct.unpack_from("<HHH", raw, start + 2)
        if block_id & 0x1FFF == number:
            return start
        start += length


@pytest.mark.integration
def test_a_damaged_block_drops_only_its_epoch_and_warns(
    sbf_bytes: bytes, tmp_path: Path
) -> None:
    clean = _n_epochs(_write(tmp_path, sbf_bytes))
    at = _first_block(sbf_bytes, MEAS_EPOCH)
    damaged = sbf_bytes[: at + 6] + b"\x00\x00" + sbf_bytes[at + 8 :]

    with capture_logs() as logs:
        n = _n_epochs(_write(tmp_path, damaged))

    assert n == clean - 1
    warnings = [log for log in logs if log["event"] == "sbf_damaged_bytes_skipped"]
    assert len(warnings) == 1
    assert warnings[0]["file"] == NAME
    assert warnings[0]["stretches"] == 1
    assert warnings[0]["bytes"] > 0


@pytest.mark.integration
def test_a_damaged_file_warns_once_per_reader(sbf_bytes: bytes, tmp_path: Path) -> None:
    at = _first_block(sbf_bytes, MEAS_EPOCH)
    damaged = sbf_bytes[: at + 6] + b"\x00\x00" + sbf_bytes[at + 8 :]
    reader = SbfReader(fpath=_write(tmp_path, damaged))

    with capture_logs() as logs:
        _ = reader.start_time, reader.end_time, reader.num_epochs
        reader.to_ds()

    warnings = [log for log in logs if log["event"] == "sbf_damaged_bytes_skipped"]
    assert len(warnings) == 1


@pytest.mark.integration
def test_a_diff_corr_in_block_is_read_past(sbf_bytes: bytes, tmp_path: Path) -> None:
    clean = _n_epochs(_write(tmp_path, sbf_bytes))
    at = _first_block(sbf_bytes, MEAS_EPOCH)
    with_corrections = sbf_bytes[:at] + _diff_corr_in() + sbf_bytes[at:]

    assert _n_epochs(_write(tmp_path, with_corrections)) == clean


def test_a_file_of_damaged_blocks_only_is_an_sbf_error(tmp_path: Path) -> None:
    damaged = _with_length(_block(MEAS_EPOCH, b"\x01" * 16), 0) * 3
    with pytest.raises(SbfError, match=r"_AA\.sbf holds no intact SBF block"):
        _ = SbfReader(fpath=_write(tmp_path, damaged)).header


def test_the_sbf_error_is_a_value_error_and_a_lookup_error() -> None:
    assert issubclass(SbfError, ValueError)
    assert issubclass(SbfError, LookupError)
