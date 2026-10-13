"""Tests for ``canvodpy.demo_data()``: download, check and unpack demo data.

The archives are small zips built in a temporary folder and served as
``file://`` URLs, so no test needs the network.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import canvodpy.demo as demo_module
import pytest
from canvodpy.demo import DemoArchive

from canvodpy import demo_data

CANOPY_RNX = "rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
REFERENCE_RNX = "rinex_v3_04/01_Rosalia/01_reference/01_GNSS/01_raw/25001/ROSR01TUW_R_20250010000_15M_05S_AA.rnx"
CANOPY_SBF = "sbf/01_Rosalia/02_canopy/25001/ROSA01TUW_R_20250010000_15M_05S_AA.sbf"


def _zip(path: Path, members: dict[str, bytes]) -> str:
    """Write a zip with these members and return its md5."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.fixture
def archives(tmp_path, monkeypatch) -> Path:
    """Replace the published archives with local ones; return their folder."""
    served = tmp_path / "served"
    served.mkdir()
    specs = [
        ("rinex", "rinex-canopy.zip", {CANOPY_RNX: b"canopy"}),
        ("rinex", "rinex-reference.zip", {REFERENCE_RNX: b"reference"}),
        ("sbf", "sbf-canopy.zip", {CANOPY_SBF: b"sbf"}),
    ]
    local = []
    for file_type, name, members in specs:
        md5 = _zip(served / name, members)
        local.append(
            DemoArchive(
                name=name,
                file_type=file_type,
                url=(served / name).as_uri(),
                md5=md5,
                members=(),
            )
        )
    monkeypatch.setattr(demo_module, "ARCHIVES", tuple(local))
    return served


def test_rinex_unpacks_both_receivers_in_the_test_data_layout(archives, tmp_path):
    root = demo_data("rinex", cache_dir=tmp_path / "cache")

    assert (root / CANOPY_RNX).read_bytes() == b"canopy"
    assert (root / REFERENCE_RNX).read_bytes() == b"reference"


def test_only_the_requested_file_type_is_downloaded(archives, tmp_path):
    root = demo_data("rinex", cache_dir=tmp_path / "cache")

    assert not (root / CANOPY_SBF).exists()


def test_cached_data_needs_no_download(archives, tmp_path):
    cache = tmp_path / "cache"
    first = demo_data("sbf", cache_dir=cache)
    (archives / "sbf-canopy.zip").unlink()

    second = demo_data("sbf", cache_dir=cache)

    assert second == first
    assert (second / CANOPY_SBF).read_bytes() == b"sbf"


def test_wrong_checksum_is_refused_and_nothing_is_unpacked(
    archives, tmp_path, monkeypatch
):
    bad = DemoArchive(
        name="sbf-canopy.zip",
        file_type="sbf",
        url=(archives / "sbf-canopy.zip").as_uri(),
        md5="0" * 32,
        members=(),
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (bad,))
    cache = tmp_path / "cache"

    with pytest.raises(RuntimeError, match=r"sbf-canopy\.zip.*md5"):
        demo_data("sbf", cache_dir=cache)

    assert not list(cache.rglob("*.sbf"))
    assert not list(cache.rglob("*.zip"))


def test_unknown_file_type_names_the_known_ones(archives, tmp_path):
    with pytest.raises(ValueError, match=r"'nmea'.*'rinex'.*'sbf'"):
        demo_data("nmea", cache_dir=tmp_path / "cache")  # ty: ignore[invalid-argument-type]


def test_unpublished_archive_says_so(archives, tmp_path, monkeypatch):
    unpublished = DemoArchive(
        name="aux.zip", file_type="aux", url=None, md5="0" * 32, members=()
    )
    monkeypatch.setattr(demo_module, "ARCHIVES", (unpublished,))

    with pytest.raises(RuntimeError, match="not published yet"):
        demo_data("aux", cache_dir=tmp_path / "cache")
