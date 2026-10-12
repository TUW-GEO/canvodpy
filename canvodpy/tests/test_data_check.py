"""Tests for the receiver data check behind ``canvodpy config validate``."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from canvodpy.orchestrator.data_check import (
    check_receiver_data,
    file_type,
    group_by_file_type,
)
from canvodpy.orchestrator.discovery import clear_discovery_cache

DAY1 = "FANA01INK_R_20250010000_15M_05S_AA.rnx"
DAY1_LATE = "FANA01INK_R_20250010015_15M_05S_AA.rnx"
DAY2 = "FANA01INK_R_20250020000_15M_05S_AA.rnx"


@pytest.fixture(autouse=True)
def _fresh_index():
    clear_discovery_cache()
    yield
    clear_discovery_cache()


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def _check(tmp_path: Path, sampling_s: float | None = None, **cfg):
    cfg = {"directory": "rx", "reader_format": "rinex3", **cfg}
    with mock.patch(
        "canvodpy.orchestrator.data_check.data_sampling_seconds",
        return_value=sampling_s,
    ) as read:
        report = check_receiver_data(
            "canopy_01",
            cfg,
            tmp_path,
            "fangorn",
            check_sampling=sampling_s is not None,
        )
    return report, read


def test_counts_what_a_run_reads(tmp_path: Path) -> None:
    _touch(tmp_path / "rx" / "25001", DAY1, DAY1_LATE)
    _touch(tmp_path / "rx" / "25002", DAY2)
    report, _ = _check(tmp_path)
    assert report.errors == []
    assert report.days == ["2025001", "2025002"]
    assert report.files == 3
    assert report.identity == "FANA01INK"
    assert report.unrecognized == []


def test_missing_directory_is_an_error(tmp_path: Path) -> None:
    report, _ = _check(tmp_path)
    assert report.errors == [f"Directory not found: {tmp_path / 'rx'}"]


def test_empty_directory_is_a_warning(tmp_path: Path) -> None:
    (tmp_path / "rx").mkdir()
    report, _ = _check(tmp_path)
    assert report.errors == []
    assert report.warnings == [f"{tmp_path / 'rx'} holds no files."]


def test_files_but_none_recognized_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", "rref001a00.25o", "rref001a15.25o")
    report, _ = _check(tmp_path)
    assert len(report.errors) == 1
    assert "holds 2 file(s), but none of them is recognized" in report.errors[0]


def test_unrecognized_and_other_format_files_are_reported(tmp_path: Path) -> None:
    sbf = DAY1.replace(".rnx", ".sbf")
    _touch(tmp_path / "rx", DAY1, "notes.txt", sbf)
    report, _ = _check(tmp_path)
    assert report.errors == []
    assert report.files == 1
    assert {p.name for p in report.unrecognized} == {"notes.txt", sbf}
    assert "2 file(s)" in report.warnings[0]


def test_compressed_files_are_reported_apart(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1, DAY2 + ".gz", "notes.txt")
    report, _ = _check(tmp_path)
    assert report.errors == []
    assert report.files == 1
    assert [p.name for p in report.compressed] == [DAY2 + ".gz"]
    assert [p.name for p in report.unrecognized] == ["notes.txt"]
    assert any(
        "1 compressed file(s)" in w and "does not decompress" in w
        for w in report.warnings
    )


def test_only_compressed_files_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1 + ".gz", DAY2 + ".gz")
    report, _ = _check(tmp_path)
    assert len(report.errors) == 1
    assert "2 compressed file(s)" in report.errors[0]
    assert "Nothing would be processed" in report.errors[0]
    assert report.warnings == []


def test_discovery_errors_are_reported(tmp_path: Path) -> None:
    _touch(tmp_path / "rx" / "a", DAY1)
    _touch(tmp_path / "rx" / "b", DAY1)
    report, _ = _check(tmp_path)
    assert "same canonical name" in report.errors[0]


def test_auto_reader_format_is_resolved(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1.replace(".rnx", ".sbf"))
    report, _ = _check(tmp_path, reader_format="auto")
    assert report.reader_format == "sbf"


def test_matching_sampling_passes(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1, DAY1_LATE, DAY2)
    report, read = _check(tmp_path, sampling_s=5.0)
    assert report.errors == []
    assert report.sampling_checked == [5.0, 5.0]
    # The first file of the first and of the last day
    assert [c.args[0].name for c in read.call_args_list] == [DAY1, DAY2]


def test_sampling_mismatch_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1)
    report, _ = _check(tmp_path, sampling_s=1.0)
    assert report.errors == [
        f"{tmp_path / 'rx' / DAY1} is named with sampling 05S by its file "
        f"name, but its data are sampled every 1 s."
    ]


def test_unreadable_file_is_a_warning(tmp_path: Path) -> None:
    _touch(tmp_path / "rx", DAY1)
    with mock.patch(
        "canvodpy.orchestrator.data_check.data_sampling_seconds",
        side_effect=ValueError("broken"),
    ):
        report = check_receiver_data(
            "canopy_01",
            {"directory": "rx", "reader_format": "rinex3"},
            tmp_path,
            "fangorn",
        )
    assert report.errors == []
    assert "Could not read" in report.warnings[0]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("rref129p45.24_", ".##_"),
        ("rref129p45.25p", ".##p"),
        ("rref0000.001", ".###"),
        ("FANA01INK_R_20250010000_15M_05S_AA.rnx.gz", ".rnx.gz"),
        ("README", "(no extension)"),
    ],
)
def test_file_type_ignores_digits(name: str, kind: str) -> None:
    assert file_type(Path(name)) == kind


def test_unprocessed_files_are_grouped_by_type() -> None:
    paths = [Path(n) for n in ("a.24_", "b.25_", "c.24p", "d.txt", "e.25_")]
    assert group_by_file_type(paths) == [
        (".##_", 3, Path("a.24_")),
        (".##p", 1, Path("c.24p")),
        (".txt", 1, Path("d.txt")),
    ]
