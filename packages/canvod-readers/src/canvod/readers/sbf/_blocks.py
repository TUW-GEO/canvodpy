"""The intact SBF blocks of a file, picked out before ``sbf-parser`` sees them.

``sbf-parser`` 1.0.3 decodes every block it finds, in compiled code, and two
inputs crash the Python process there instead of raising (canvodpy #678): a
block header whose Length is 0 or 4, and a ``DiffCorrIn`` block
(septentrio-gnss/SbfParser#8). The reader therefore walks the file itself
and hands ``sbf-parser`` only the intact blocks of the types it reads.

A block is intact when its Length is more than the 8 header bytes, a
multiple of 4, fits in the file, and its CRC matches: the CRC-CCITT
(polynomial x^16 + x^12 + x^5 + 1, seed 0) of the bytes from the ID field
to the end of the block. The block number is bits 0 to 12 of the ID field
(RefGuide-4.14.0, Section 4.1.1, p.252). Bytes outside an intact block are
dropped and counted, as ``sbf-parser`` itself drops a block whose CRC
fails.
"""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

#: First two bytes of every SBF block (RefGuide-4.14.0, Section 4.1.1, p.252)
SYNC: bytes = b"$@"
#: Sync, CRC, ID and Length (u2 each)
HEADER_LENGTH: int = 8
_BLOCK_NUMBER_MASK: int = 0x1FFF


@dataclass(frozen=True)
class IntactBlocks:
    """The intact blocks of the wanted types, and what was dropped.

    Attributes
    ----------
    data : bytes
        The wanted intact blocks, one after another, as in the file.
    n_intact : int
        Intact blocks of any type in the file.
    dropped_stretches : int
        Runs of bytes outside an intact block.
    dropped_bytes : int
        Bytes outside an intact block.
    """

    data: bytes
    n_intact: int
    dropped_stretches: int
    dropped_bytes: int


def _intact_length(raw: bytes, start: int) -> int:
    """Length of the intact block at ``start``, or 0 if there is none."""
    if raw[start : start + 2] != SYNC or start + HEADER_LENGTH > len(raw):
        return 0
    crc, _, length = struct.unpack_from("<HHH", raw, start + 2)
    if (
        length <= HEADER_LENGTH
        or length % 4
        or start + length > len(raw)
        or binascii.crc_hqx(raw[start + 4 : start + length], 0) != crc
    ):
        return 0
    return length


def intact_blocks(raw: bytes, block_numbers: frozenset[int]) -> IntactBlocks:
    """Pick the intact blocks of the given block numbers out of ``raw``.

    Parameters
    ----------
    raw : bytes
        The content of an SBF file.
    block_numbers : frozenset[int]
        Block numbers to keep (bits 0 to 12 of the ID field).

    Returns
    -------
    IntactBlocks
        The kept blocks and what was dropped.
    """
    kept: list[bytes] = []
    n_intact = dropped_stretches = dropped_bytes = 0
    in_gap = False
    start = 0
    while start < len(raw):
        length = _intact_length(raw, start)
        if length == 0:
            # resynchronize at the next sync, as sbf-parser does
            following = raw.find(SYNC, start + 1)
            end = len(raw) if following < 0 else following
            dropped_bytes += end - start
            if not in_gap:
                dropped_stretches += 1
                in_gap = True
            start = end
            continue
        in_gap = False
        n_intact += 1
        block_id = struct.unpack_from("<H", raw, start + 4)[0]
        if block_id & _BLOCK_NUMBER_MASK in block_numbers:
            kept.append(raw[start : start + length])
        start += length
    return IntactBlocks(b"".join(kept), n_intact, dropped_stretches, dropped_bytes)
