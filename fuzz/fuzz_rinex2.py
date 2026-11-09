"""Fuzz the RINEX 2 observation reader (``Rnxv2Obs``).

Allowed for bad input: ``RinexError``, pydantic's ``ValidationError`` and
``ValueError``, which the reader still raises for bad input in several
places, but never ``UnicodeError``. Plain ``ValueError`` goes once those
places raise reader errors (canvodpy #680).
"""

from __future__ import annotations

from fuzzing import as_file, main
from pydantic import ValidationError

from canvod.readers.gnss_specs.exceptions import RinexError
from canvod.readers.rinex.v2_11 import Rnxv2Obs

NAME = "FANA01INK_R_20250010000_01H_15S_AA.rnx"


def fuzz_one_input(data: bytes) -> None:
    """Read one input as a RINEX 2 file; raise only for a bug."""
    try:
        Rnxv2Obs(fpath=as_file(data, NAME)).to_ds()
    except UnicodeError:
        raise
    except RinexError, ValidationError, ValueError:
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
