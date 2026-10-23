"""``TIME OF FIRST OBS`` is parsed from the header (RINEX 3.04 Table A2).

It is mandatory, carries its own time system (default: the system of a
single-system file) and is kept as written, like the epochs of the file.
"""

from datetime import UTC, datetime

import pytest

from canvod.readers.rinex.v3_04 import Rnxv3Header


def _t0(value: str, file_system: str = "M") -> dict[str, datetime]:
    return Rnxv3Header._get_time_of_first_obs(
        {"TIME OF FIRST OBS": value}, file_system=file_system
    )


def test_time_of_first_obs_is_parsed_from_header():
    t0 = _t0("  2025     1     1     0     0    0.0000000     GPS")
    assert t0 == {"GPS": datetime(2025, 1, 1, tzinfo=UTC)}


def test_glonass_time_is_kept_as_written():
    """GLO is UTC already; no leap-second shift is applied."""
    t0 = _t0("  2025     1     1     0     0    0.0000000     GLO")
    assert t0 == {"GLO": datetime(2025, 1, 1, tzinfo=UTC)}


def test_fractional_seconds_are_kept():
    t0 = _t0("  2025     1     1     0     0   12.5000000     GAL")
    assert t0 == {"GAL": datetime(2025, 1, 1, 0, 0, 12, 500000, tzinfo=UTC)}


@pytest.mark.parametrize(("file_system", "expected"), [("G", "GPS"), ("C", "BDT")])
def test_single_system_file_defaults_to_its_time_system(file_system, expected):
    t0 = _t0("  2025     1     1     0     0    0.0000000", file_system)
    assert list(t0) == [expected]


def test_mixed_file_without_time_system_is_rejected():
    with pytest.raises(ValueError, match="compulsory in mixed files"):
        _t0("  2025     1     1     0     0    0.0000000", "M")


@pytest.mark.parametrize(
    "header",
    [{}, {"TIME OF FIRST OBS": "  2025     1"}, {"TIME OF FIRST OBS": "x" * 40}],
    ids=["missing", "short", "garbage"],
)
def test_missing_or_malformed_record_is_rejected(header):
    with pytest.raises(ValueError, match="TIME OF FIRST OBS"):
        Rnxv3Header._get_time_of_first_obs(header, file_system="G")
