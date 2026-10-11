"""The two RINEX v3 parsers on the same files.

``to_ds()`` uses the validated parser by default: every epoch passes the
pydantic epoch and satellite models, and epochs that fail are dropped and
logged. The unvalidated fast parser slices fixed columns without any check
and is opt-in only (``parser="unvalidated_fast"``). Both share the sid space,
the array allocation, the epoch-time conversion and the dataset assembly;
only the parsing differs.

Rules tested here:

- For a valid file both give the identical dataset (values, coordinates,
  attributes).
- For a corrupted file they may differ; the validated parser keeps only
  epochs that pass validation, the fast parser keeps whatever it can slice.
- Every use of the fast parser warns.

Real data can be added with ``CANVOD_PARITY_DATA_DIR`` (searched recursively
for ``*.rnx``/``*.??o``), e.g. a week of receiver files on an external drive.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.gnss_specs.exceptions import InvalidEpochError
from canvod.readers.rinex.v3_04 import (
    Rnxv3Obs,
    UnvalidatedParserWarning,
    _epoch_datetime64,
)
from canvod.readers.rinex.v3_05_stripped import Rnxv3StrippedObs

TEST_DATA_DIR = Path(__file__).parent / "test_data"
V304_DIR = TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia"
V305_DIR = TEST_DATA_DIR / "valid/rinex_v3_05_stripped"
INVALID_DIR = TEST_DATA_DIR / "invalid"
V304_FILE = (
    V304_DIR / "02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)

needs_v304 = pytest.mark.skipif(
    not V304_FILE.exists(), reason="RINEX v3.04 test data not available"
)
needs_invalid = pytest.mark.skipif(
    not INVALID_DIR.is_dir(), reason="invalid RINEX test data not available"
)


def _rinex_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and not p.name.startswith(".")
        and (p.suffix == ".rnx" or (len(p.suffix) == 4 and p.suffix[-1] == "o"))
    )


def _valid_cases() -> list:
    cases = [
        pytest.param(Rnxv3Obs, p, id=f"v304/{p.name}") for p in _rinex_files(V304_DIR)
    ]
    cases += [
        pytest.param(Rnxv3StrippedObs, p, id=f"v305/{p.name}")
        for p in _rinex_files(V305_DIR)
    ]
    extra = os.environ.get("CANVOD_PARITY_DATA_DIR")
    if extra:
        cases += [
            pytest.param(Rnxv3Obs, p, id=f"extra/{p.name}")
            for p in _rinex_files(Path(extra))
        ]
    return cases


def _both(obs: Rnxv3Obs) -> tuple[xr.Dataset, xr.Dataset]:
    validated = obs._create_dataset(None, "validated")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnvalidatedParserWarning)
        fast = obs._create_dataset(None, "unvalidated_fast")
    return validated, fast


@pytest.mark.parametrize(("reader_cls", "fpath"), _valid_cases())
def test_parsers_identical_on_valid_files(reader_cls, fpath):
    obs = reader_cls(fpath=fpath, completeness_mode="off")
    rejected: list[int] = []
    n_valid = sum(1 for _ in obs._iter_validated_epochs(rejected))
    assert not rejected, f"valid test file has rejected epochs at {rejected}"
    assert n_valid > 0

    validated, fast = _both(obs)
    # "Created" is the build time of each dataset, not file content.
    for ds in (validated, fast):
        ds.attrs.pop("Created", None)
    xr.testing.assert_identical(validated, fast)


@pytest.mark.parametrize(
    "fpath", [pytest.param(p, id=p.name) for p in _rinex_files(INVALID_DIR)]
)
def test_validated_keeps_only_valid_epochs(fpath):
    """Corrupted files: the dataset holds exactly the validated epochs."""
    # Skip after the except blocks, not inside them: inside, pytest keeps
    # the caught exception and its frames until the test run ends.
    try:
        obs = Rnxv3Obs(fpath=fpath, completeness_mode="off")
    except Exception:
        obs = None
    if obs is None:
        pytest.skip("header rejected")
    try:
        validated = obs._create_dataset(None, "validated")
    except ValueError:
        validated = None
    if validated is None:
        pytest.skip("invalid calendar epoch, the file is rejected as a whole")
    records = list(obs.iter_epochs())
    expected = np.array(
        [obs.epochrecordinfo_dt_to_numpy_dt(r) for r in records],
        dtype="datetime64[ns]",
    )
    np.testing.assert_array_equal(validated["epoch"].values, expected)


@needs_invalid
@pytest.mark.parametrize(
    ("name", "n_epochs"),
    [
        ("truncated_mid_epoch.25o", 0),
        ("satellite_count_mismatch.25o", 1),
        ("invalid_satellite_id.25o", 1),
        ("mixed_valid_corrupt.25o", 2),
    ],
)
def test_validated_drops_corrupted_epochs(name, n_epochs):
    """The fast parser keeps these corrupted epochs; the validated one does not."""
    obs = Rnxv3Obs(fpath=INVALID_DIR / name, completeness_mode="off")
    validated, fast = _both(obs)
    assert validated.sizes["epoch"] == n_epochs
    assert fast.sizes["epoch"] > n_epochs


@needs_invalid
def test_rejected_epochs_are_reported():
    obs = Rnxv3Obs(
        fpath=INVALID_DIR / "satellite_count_mismatch.25o", completeness_mode="off"
    )
    rejected: list[int] = []
    list(obs._iter_validated_epochs(rejected))
    assert len(rejected) == 1


@needs_v304
def test_fast_parser_warns_on_every_use():
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    for _ in range(2):
        with pytest.warns(UnvalidatedParserWarning, match="DANGEROUS"):
            obs.to_ds(keep_data_vars=["SNR"], parser="unvalidated_fast")


@needs_v304
def test_validated_parser_does_not_warn():
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnvalidatedParserWarning)
        obs.to_ds(keep_data_vars=["SNR"], parser="validated")


@needs_v304
def test_unknown_parser_is_rejected():
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    with pytest.raises(ValueError, match="parser must be"):
        obs.to_ds(keep_data_vars=["SNR"], parser="fast")


def test_config_default_is_validated():
    from canvod.config.models.processing_params import ProcessingParams

    assert ProcessingParams().rinex_v3_parser == "validated"


@pytest.mark.parametrize(
    ("seconds", "expected_ns"),
    [
        (0.0, 0),
        (0.1, 100_000_000),
        (59.9999999, 59_999_999_900),
        (30.0000001, 30_000_000_100),
    ],
)
def test_epoch_seconds_keep_100ns_resolution(seconds, expected_ns):
    ts = _epoch_datetime64(2025, 1, 1, 0, 0, seconds)
    assert (ts - np.datetime64("2025-01-01T00:00", "ns")) == np.timedelta64(
        expected_ns, "ns"
    )


@pytest.mark.parametrize("seconds", [60.0, -0.5])
def test_epoch_seconds_out_of_range_raise(seconds):
    with pytest.raises(ValueError, match="second must be"):
        _epoch_datetime64(2025, 1, 1, 0, 0, seconds)


@needs_invalid
@pytest.mark.parametrize(
    ("name", "rejected_lines", "n_kept"),
    [
        ("huge_satellite_count.25o", [61], 1),
        ("invalid_satellite_id.25o", [61], 1),
        ("misaligned_observations.25o", [61], 1),
        ("mixed_valid_corrupt.25o", [97], 2),
        ("negative_seconds.25o", [61], 1),
        ("non_numeric_observations.25o", [61], 0),
        ("satellite_count_mismatch.25o", [61], 1),
        ("truncated_mid_epoch.25o", [61], 0),
        ("zero_satellites.25o", [61], 1),
    ],
)
def test_rejected_epochs_by_line(name, rejected_lines, n_kept):
    """The epochs the validated parser rejects, by 1-based line number."""
    obs = Rnxv3Obs(fpath=INVALID_DIR / name, completeness_mode="off")
    rejected: list[int] = []
    n_found = sum(1 for _ in obs._iter_validated_epochs(rejected))
    assert [i + 1 for i in rejected] == rejected_lines
    assert n_found == n_kept
    assert obs._create_dataset(None, "validated").sizes["epoch"] == n_kept


@needs_invalid
def test_unreadable_field_rejects_its_epoch():
    """A field that is not blank but holds no readable value rejects the epoch."""
    obs = Rnxv3Obs(
        fpath=INVALID_DIR / "non_numeric_observations.25o", completeness_mode="off"
    )
    with pytest.raises(InvalidEpochError, match="Unreadable observation field"):
        obs.process_satellite_data(obs._lines[61])


@needs_v304
@pytest.mark.parametrize(
    "field",
    [
        "  23456789.123 7",  # standard form
        "  23456789.12345",  # LLI and SSI digits
        "        45.250  ",  # no flags
        "      -123.456 1",  # negative value
        "                ",  # blank
        "  23456789.123X7",  # LLI not a digit
        "  23456789.123 ²",  # SSI a non-ASCII digit
        "999999.999 9  99",  # decimal point not in column 10
        "         12345  ",  # no decimal point
        "  1234_5678.1 7 ",  # underscore
        "  ABCDEFGHIJKL 7",  # no value
    ],
)
def test_field_reading_matches_flexible_parser(field):
    """The direct read of a field gives the result of parse_observation_slice."""
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    expected = obs.parse_observation_slice(field)
    if expected[0] is None and field.strip():
        with pytest.raises(InvalidEpochError):
            obs._read_observation_field(field)
    else:
        assert obs._read_observation_field(field) == expected
