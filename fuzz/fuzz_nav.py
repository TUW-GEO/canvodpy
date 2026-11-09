"""Fuzz the RINEX navigation file reader (``read_rinex_nav``).

Allowed for bad input: ``RinexNavError`` only, which names the file and,
for a record, its line.
"""

from __future__ import annotations

from fuzzing import as_file, main

from canvod.readers.gnss_specs.exceptions import RinexNavError
from canvod.readers.rinex.nav import read_rinex_nav

NAME = "FANA01INK_R_20250010000_15M_00U_AA.nav"


def fuzz_one_input(data: bytes) -> None:
    """Read one input as a navigation file; raise only for a bug."""
    try:
        read_rinex_nav([as_file(data, NAME)])
    except RinexNavError:
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
