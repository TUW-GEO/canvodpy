"""``IcechunkDataReader`` is deprecated (left over from development).

The warnings fire before any work is done, so neither a site nor data is
needed to check them. ``parsed_rinex_data_gen_v2`` raises right away.
"""

import re

import pytest

from canvod.store import reader
from canvod.store.reader import IcechunkDataReader

LEFT_OVER = "left over from development"
REPLACEMENT = r"canvodpy\.Site\(<site>\)\.pipeline\(\)\.process_date\(<date>\)"


class _StopInitError(Exception):
    """Raised instead of loading the configuration."""


def _stop_init():
    raise _StopInitError


def test_instantiation_is_deprecated(monkeypatch):
    monkeypatch.setattr(reader, "load_config", _stop_init)
    with (
        pytest.warns(FutureWarning, match=f"IcechunkDataReader.*{LEFT_OVER}"),
        pytest.raises(_StopInitError),
    ):
        IcechunkDataReader(matched_dirs=None)


def test_generator_is_deprecated():
    # Calling the generator function warns; the body only runs on iteration.
    method = "parsed_rinex_data_gen"
    with pytest.warns(FutureWarning, match=f"{method}.*{LEFT_OVER}") as record:
        getattr(IcechunkDataReader, method)(object())
    assert re.search(REPLACEMENT, str(record[0].message))


def test_generator_v2_raises():
    method = "parsed_rinex_data_gen_v2"
    with (
        pytest.warns(FutureWarning, match=f"{method}.*{LEFT_OVER}") as record,
        pytest.raises(RuntimeError, match=f"does not run.*{REPLACEMENT}"),
    ):
        getattr(IcechunkDataReader, method)(object())
    message = str(record[0].message)
    assert "does not run" in message
    assert re.search(REPLACEMENT, message)
