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
        ("bitflip_numeric.25o", [61], 1),
        ("extra_long_sat_line.25o", [61], 1),
        ("huge_satellite_count.25o", [61], 1),
        ("invalid_satellite_id.25o", [61], 1),
        ("misaligned_observations.25o", [61], 1),
        ("mixed_valid_corrupt.25o", [97], 2),
        ("negative_seconds.25o", [61], 1),
        ("non_numeric_observations.25o", [61], 0),
        ("null_bytes.25o", [61], 1),
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
def test_malformed_field_rejects_its_epoch():
    """A field that is neither blank nor in the standard form rejects the epoch."""
    obs = Rnxv3Obs(
        fpath=INVALID_DIR / "non_numeric_observations.25o", completeness_mode="off"
    )
    with pytest.raises(InvalidEpochError, match="Malformed observation field"):
        obs.process_satellite_data(obs._lines[61])


@needs_v304
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("  23456789.123 7", (23456789.123, None, 7)),
        ("  23456789.12345", (23456789.123, 4, 5)),
        ("        45.250  ", (45.25, None, None)),
        ("      -123.456 1", (-123.456, None, 1)),
        ("         -.456  ", (-0.456, None, None)),
        ("                ", (None, None, None)),
    ],
)
def test_standard_field_is_read(field, expected):
    """A field in the standard form gives its value and flags; blank is missing."""
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    assert obs._read_observation_field(field) == expected


@needs_v304
@pytest.mark.parametrize(
    "field",
    [
        "  23456789.123X7",  # LLI not a digit
        "  23456789.123 \u00b2",  # SSI a non-ASCII digit
        "999999.999 9  99",  # decimal point not in column 10
        "         12345  ",  # no decimal point
        "  1234_5678.1 7 ",  # underscore
        "  2282\u00b2963.723  ",  # non-ASCII digit in the value
        "  ABCDEFGHIJKL 7",  # no value
        "  23456789.123\x00 ",  # null byte
        "            .1 7",  # one decimal instead of three
        "              7 ",  # flags without a value
    ],
)
def test_malformed_field_raises(field):
    """A field neither blank nor in the standard form raises InvalidEpochError."""
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    with pytest.raises(InvalidEpochError, match="Malformed observation field"):
        obs._read_observation_field(field)


@needs_v304
def test_flexible_field_parser_is_deprecated():
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    with pytest.warns(FutureWarning, match="left over from development.*to_ds"):
        obs.parse_observation_slice("  23456789.123 7")


@needs_invalid
@pytest.mark.parametrize(
    "name", ["bitflip_numeric.25o", "extra_long_sat_line.25o", "null_bytes.25o"]
)
def test_to_ds_drops_the_epoch_of_a_malformed_field(name):
    """Only the clean epoch reaches the dataset; no guessed value does."""
    obs = Rnxv3Obs(fpath=INVALID_DIR / name, completeness_mode="off")
    ds = obs.to_ds()
    assert ds.sizes["epoch"] == 1
    assert ds["epoch"].values[0] == np.datetime64("2025-01-01T00:00:05", "ns")


@needs_invalid
@pytest.mark.parametrize(
    ("keep_data_vars", "n_kept"),
    [
        (["SNR"], 2),
        (["Phase"], 2),
        (["Doppler"], 2),
        (["LLI"], 2),
        (["Pseudorange"], 1),
        (["SSI"], 1),
        (["SNR", "Pseudorange"], 1),
    ],
)
def test_to_ds_reads_only_the_fields_of_kept_variables(keep_data_vars, n_kept):
    """A damaged code field rejects its epoch only if a kept variable needs it.

    The damage in bitflip_numeric.25o sits in a C1C field (line 63): it is
    read for Pseudorange and for SSI (code SSI when no phase), not for SNR,
    Phase, Doppler or LLI.
    """
    obs = Rnxv3Obs(fpath=INVALID_DIR / "bitflip_numeric.25o", completeness_mode="off")
    ds = obs.to_ds(keep_data_vars=keep_data_vars)
    assert ds.sizes["epoch"] == n_kept


@needs_invalid
@pytest.mark.parametrize(
    "name", ["bitflip_numeric.25o", "extra_long_sat_line.25o", "null_bytes.25o"]
)
def test_snr_only_keeps_the_epoch_of_a_damaged_non_snr_field(name):
    """The all-variables read rejects the epoch, the SNR-only read keeps it."""
    obs = Rnxv3Obs(fpath=INVALID_DIR / name, completeness_mode="off")
    assert obs.to_ds().sizes["epoch"] == 1

    ds = obs.to_ds(keep_data_vars=["SNR"])

    assert list(ds["epoch"].values) == [
        np.datetime64("2025-01-01T00:00:00", "ns"),
        np.datetime64("2025-01-01T00:00:05", "ns"),
    ]
    assert list(ds.data_vars) == ["SNR"]


@needs_invalid
def test_snr_only_keeps_the_snr_value_of_the_damaged_line():
    """bitflip_numeric.25o line 63: G32 S1C is 41.809, next to the damaged C1C."""
    obs = Rnxv3Obs(fpath=INVALID_DIR / "bitflip_numeric.25o", completeness_mode="off")
    ds = obs.to_ds(keep_data_vars=["SNR"])
    value = ds["SNR"].sel(epoch=np.datetime64("2025-01-01T00:00:00"), sid="G32|L1|C")
    assert float(value) == pytest.approx(41.809)


@needs_invalid
def test_snr_only_rejects_an_epoch_with_a_damaged_snr_field():
    """misaligned_observations.25o shifts the S fields too, so SNR still rejects."""
    obs = Rnxv3Obs(
        fpath=INVALID_DIR / "misaligned_observations.25o", completeness_mode="off"
    )
    assert obs.to_ds(keep_data_vars=["SNR"]).sizes["epoch"] == 1


@needs_invalid
@pytest.mark.parametrize(
    "name", ["bitflip_numeric.25o", "extra_long_sat_line.25o", "null_bytes.25o"]
)
def test_iter_epochs_still_checks_every_field(name):
    obs = Rnxv3Obs(fpath=INVALID_DIR / name, completeness_mode="off")
    assert len(list(obs.iter_epochs())) == 1


@needs_v304
@pytest.mark.parametrize(
    "keep_data_vars",
    [
        ["SNR", "Pseudorange", "Phase", "Doppler", "LLI", "SSI"],
        ["LLI", "SSI"],
        ["LLI"],
        ["SSI"],
        ["SNR", "Doppler"],
    ],
)
def test_kept_variables_have_the_values_of_the_full_read(keep_data_vars):
    """On a valid file every kept variable equals that of the all-variables read.

    LLI and SSI kept without Phase or Pseudorange still come from the phase
    and code fields, with the phase's SSI ranked first.
    """
    obs = Rnxv3Obs(fpath=V304_FILE, completeness_mode="off")
    full = obs.to_ds()
    subset = obs.to_ds(keep_data_vars=keep_data_vars)
    for ds in (full, subset):
        ds.attrs.pop("Created", None)
    xr.testing.assert_identical(subset, full[keep_data_vars])
