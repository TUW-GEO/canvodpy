"""Fuzz the SBF reader (``SbfReader``).

Allowed for bad input: ``SbfError`` and pydantic's ``ValidationError``.
sbf-parser crashes the whole process on some blocks (canvodpy #678); the
reader never hands it those, and the fuzzer reports any crash.
"""

from __future__ import annotations

from fuzzing import as_file, main
from pydantic import ValidationError

from canvod.readers.gnss_specs.exceptions import SbfError
from canvod.readers.sbf.reader import SbfReader

NAME = "FANA01INK_R_20250010000_15M_05S_AA.sbf"


def fuzz_one_input(data: bytes) -> None:
    """Read one input as an SBF file; raise only for a bug."""
    try:
        SbfReader(fpath=as_file(data, NAME)).to_ds()
    except SbfError, ValidationError:
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
