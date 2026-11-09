"""Fuzz the NMEA reader (``NmeaObs``).

Allowed for bad input: ``NmeaError``, pydantic's ``ValidationError`` and
``ValueError``, which the reader still raises for bad input, but never
``UnicodeError``. Plain ``ValueError`` goes once it raises reader errors
there (canvodpy #680).
"""

from __future__ import annotations

from fuzzing import as_file, main
from pydantic import ValidationError

from canvod.readers.gnss_specs.exceptions import NmeaError
from canvod.readers.nmea.v4_00 import NmeaObs

NAME = "FANA01INK_R_20250010000_01H_01S_AA.nmea"


def fuzz_one_input(data: bytes) -> None:
    """Read one input as an NMEA file; raise only for a bug."""
    try:
        NmeaObs(fpath=as_file(data, NAME)).to_ds()
    except UnicodeError:
        raise
    except NmeaError, ValidationError, ValueError:
        # a documented error for bad input: not a bug
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
