"""Tests that ``canvodpy run`` says what it is doing while finding files."""

from __future__ import annotations

import functools
import time
from pathlib import Path

import canvodpy.orchestrator.discovery as discovery_module
import pytest
import yaml
from canvodpy.cli.app import main_app
from canvodpy.cli.run import _discovery_callbacks
from canvodpy.orchestrator.discovery import clear_discovery_cache
from typer.testing import CliRunner

import canvod.config.loader as loader_module

runner = CliRunner()


def _write_site(tmp_path: Path) -> Path:
    """A small site with a canopy and a reference receiver of ``.sbf`` files."""
    config_dir = tmp_path / "config"
    data_root = tmp_path / "data"
    canopy_dir = data_root / "02_canopy"
    ref_dir = data_root / "01_reference"
    config_dir.mkdir(parents=True)
    canopy_dir.mkdir(parents=True)
    ref_dir.mkdir(parents=True)
    (canopy_dir / "FANA01INK_R_20250010000_15M_05S_AA.sbf").write_text("")
    (ref_dir / "FANR01INK_R_20250010000_15M_05S_AA.sbf").write_text("")
    metadata = {
        "author": "Test Person",
        "email": "t@example.com",
        "institution": "TU Wien",
        "publisher": "TU Wien",
        "naming_authority": "at.tuwien",
        "initials": "TP",
        "license": "CC-BY-4.0",
    }
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": metadata,
                    "storage": {
                        "stores_root_dir": str(tmp_path / "stores"),
                        "aux_data_dir": str(tmp_path / "aux"),
                    },
                    "logging": {"log_dir": str(tmp_path / "logs")},
                },
                "sites": {
                    "fangorn": {
                        "gnss_site_data_root": str(data_root),
                        "receivers": {
                            "canopy_01": {
                                "type": "canopy",
                                "directory": "02_canopy",
                                "reader_format": "sbf",
                            },
                            "reference_01": {
                                "type": "reference",
                                "directory": "01_reference",
                                "reader_format": "sbf",
                                "paired_canopies": ["canopy_01"],
                            },
                        },
                    }
                },
            }
        )
    )
    return config_dir


@pytest.fixture(autouse=True)
def _fresh_config():
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


def test_run_dry_run_says_what_it_is_finding(tmp_path: Path) -> None:
    """A dry-run prints, before each receiver, the folder it scans, and after
    it, the files and days found."""
    config_dir = _write_site(tmp_path)
    result = runner.invoke(
        main_app,
        [
            "run",
            "--dry-run",
            "--site",
            "fangorn",
            "--start",
            "2025001",
            "--end",
            "2025001",
        ],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )
    assert result.exit_code == 0, result.output
    # One before and one after line per receiver.
    assert "Finding files of receiver canopy_01 in" in result.output
    assert "can take minutes on a network drive" in result.output
    assert "Found 1 file on 1 day for receiver canopy_01" in result.output
    assert "Finding files of receiver reference_01 in" in result.output
    assert "Found 1 file on 1 day for receiver reference_01" in result.output


def test_discovery_callbacks_singular_and_plural() -> None:
    """The helper pluralizes the count words for one file or one day."""
    lines: list[str] = []
    on_start, on_end = _discovery_callbacks(lines.append)
    folder = Path("/data/canopy")
    on_start("canopy_01", folder)
    on_end("canopy_01", 1, 1, 0.5)
    on_end("canopy_01", 2, 1, 0.5)
    on_end("canopy_01", 1, 3, 0.5)
    on_end("canopy_01", 96, 120, 0.5)

    # The expected line is built from the same Path, so it holds on Windows,
    # where the path prints with backslashes.
    assert lines[0] == (
        f"  Finding files of receiver canopy_01 in {folder} "
        "(can take minutes on a network drive)..."
    )
    assert lines[1] == "  Found 1 file on 1 day for receiver canopy_01 (0.5 s)."
    assert lines[2] == "  Found 2 files on 1 day for receiver canopy_01 (0.5 s)."
    assert lines[3] == "  Found 1 file on 3 days for receiver canopy_01 (0.5 s)."
    assert lines[4] == "  Found 96 files on 120 days for receiver canopy_01 (0.5 s)."


def test_discovery_messages_bracket_the_real_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through a dry-run, the 'Finding files of receiver X' line of each
    receiver precedes its 'Found ...' line, and the reported seconds cover
    the real scan, not a cache hit.

    The seam all directory scans go through is monkeypatched to sleep, so the
    scan in the pipeline constructor is the slow part and the messages bracket
    it, as they would on a network drive.
    """
    config_dir = _write_site(tmp_path)
    original = discovery_module._scan_directory
    clear_discovery_cache()

    # Cached like the real scan, so a scan before the "Finding files" line
    # would make the reported seconds a cache hit and fail the test.
    @functools.lru_cache(maxsize=64)
    def slow_scan(directory: Path, recipe: Path | None):
        time.sleep(0.5)
        return original.__wrapped__(directory, recipe)

    monkeypatch.setattr(discovery_module, "_scan_directory", slow_scan)

    result = runner.invoke(
        main_app,
        [
            "run",
            "--dry-run",
            "--site",
            "fangorn",
            "--start",
            "2025001",
            "--end",
            "2025001",
        ],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for name in ("canopy_01", "reference_01"):
        start_idx = next(
            i
            for i, line in enumerate(lines)
            if f"Finding files of receiver {name} in" in line
        )
        found_idx = next(
            i for i, line in enumerate(lines) if f"for receiver {name} (" in line
        )
        assert start_idx < found_idx, "\n".join(lines[start_idx : found_idx + 1])
        seconds = float(lines[found_idx].split("(")[-1].split(" s")[0])
        assert seconds >= 0.5, lines[found_idx]
