"""The date of the RINEX 3 header record PGM / RUN BY / DATE."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from canvod.readers.gnss_specs.exceptions import CorruptedFileError
from canvod.readers.rinex.v3_04 import Rnxv3Header

FPATH = Path("FANA01INK_R_20250010000_15M_05S_AA.rnx")


def _record(date: str) -> dict[str, str]:
    # A20 program, A20 run by, A20 date (RINEX 3.04, Table A2)
    return {"PGM / RUN BY / DATE": f"{'sbf2rin-15.3.1':<20}{'':<20}{date:<20}"}


def test_a_utc_date_has_its_time_zone() -> None:
    pgm, _, date = Rnxv3Header._get_pgm_runby_date(
        _record("20250101 000012 UTC"), FPATH
    )
    assert pgm == "sbf2rin-15.3.1"
    assert date == datetime(2025, 1, 1, 0, 0, 12, tzinfo=UTC)


def test_a_local_date_has_no_time_zone() -> None:
    _, _, date = Rnxv3Header._get_pgm_runby_date(_record("20250101 000012 LCL"), FPATH)
    assert date == datetime(2025, 1, 1, 0, 0, 12)
    assert date.tzinfo is None


@pytest.mark.parametrize(
    "date",
    ["20250101 000012 ETC", "20251301 000012 UTC", "01-JAN-25 00:00   ", ""],
    ids=["unknown-zone", "month", "rinex-2-style", "blank"],
)
def test_a_date_that_cant_be_read_names_the_file(date: str) -> None:
    with pytest.raises(CorruptedFileError, match=r"_AA\.rnx: "):
        Rnxv3Header._get_pgm_runby_date(_record(date), FPATH)


def test_a_missing_record_names_the_file() -> None:
    with pytest.raises(CorruptedFileError, match=r"_AA\.rnx: .*PGM / RUN BY / DATE"):
        Rnxv3Header._get_pgm_runby_date({}, FPATH)
