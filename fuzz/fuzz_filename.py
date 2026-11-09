"""Fuzz the canonical file name parser (``CanVODFilename.from_filename``).

The input is the name, as UTF-8 with invalid bytes replaced. Allowed for
bad input: ``ValueError``, which ``from_filename`` documents (pydantic's
``ValidationError`` is one).
"""

from __future__ import annotations

from fuzzing import main

from canvod.preflight.convention import CanVODFilename


def fuzz_one_input(data: bytes) -> None:
    """Read one input as a file name; raise only for a bug."""
    try:
        CanVODFilename.from_filename(data.decode("utf-8", errors="replace"))
    except ValueError:
        # a documented error for bad input: not a bug
        pass


if __name__ == "__main__":
    main(fuzz_one_input)
