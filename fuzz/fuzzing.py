"""What the canvodpy fuzz harnesses share (``fuzz/fuzz_<target>.py``).

Each harness feeds one input to one reader, as a file with a canonical
name, and lets through only the errors the reader documents for bad input.
Any other exception is a bug, and so is a hang or a memory blow-up (the
fuzzer's ``-timeout`` and ``-rss_limit_mb``).

Run a harness with ``just fuzz <target>`` (Linux x86_64 only: atheris has
no other wheels). The tests replay the saved inputs in ``fuzz/corpus`` and
``fuzz/crashes`` on every platform, without atheris
(``fuzz/tests/test_fuzz_replay.py``).

The seeds in ``fuzz/corpus`` are cut from the test data, with the station
in their headers and positions replaced by the test persona's site
Fangorn (:mod:`canvod.utils.testing`). Their observations are scrambled
(pseudoranges, carrier phases, Doppler, satellite azimuths and
elevations), so no station position can be computed from them.
"""

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

_FOLDER = Path(tempfile.mkdtemp(prefix="canvodpy-fuzz-"))
atexit.register(shutil.rmtree, _FOLDER, ignore_errors=True)


def as_file(data: bytes, name: str) -> Path:
    """Write ``data`` to a file called ``name`` in a temporary folder."""
    path = _FOLDER / name
    path.write_bytes(data)
    return path


def main(fuzz_one_input: Callable[[bytes], None]) -> None:
    """Fuzz with atheris; the arguments go to libFuzzer."""
    try:
        import atheris
    except ImportError:
        sys.exit("atheris runs on Linux x86_64 only: uv sync --group fuzz there")

    import logging
    import warnings

    import structlog

    # the readers log and warn about bad input; the fuzzer needs neither
    warnings.simplefilter("ignore")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL)
    )
    atheris.instrument_all()
    atheris.Setup(sys.argv, fuzz_one_input)
    atheris.Fuzz()
