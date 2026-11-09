"""Fuzz the RINEX 3 observation reader (``Rnxv3Obs``).

Allowed for bad input: ``RinexError``, pydantic's ``ValidationError`` and
``ValueError``, which the reader still raises for bad input in several
places (docs/packages/readers/rinex-format.md, "Error handling"), but never
``UnicodeError``. Plain ``ValueError`` goes once those places raise reader
errors (canvodpy #680).
"""

from __future__ import annotations

from fuzzing import as_file, main
from pydantic import ValidationError

from canvod.readers.gnss_specs.exceptions import RinexError
from canvod.readers.rinex.v3_04 import Rnxv3Obs

NAME = "FANA01INK_R_20250010000_15M_05S_AA.rnx"


def fuzz_one_input(data: bytes) -> None:
    """Read one input as a RINEX 3 file; raise only for a bug."""
    try:
        Rnxv3Obs(fpath=as_file(data, NAME), completeness_mode="off").to_ds()
    except UnicodeError:
        raise
    except RinexError, ValidationError, ValueError:
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
