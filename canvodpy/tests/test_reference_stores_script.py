"""Packing the reference stores and unpacking the zips (spec #318, #325)."""

import importlib.util
import sys
from compression import zstd
from pathlib import Path

import pytest

from canvod.utils import testing

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "reference_stores_script", ROOT / "scripts" / "reference_stores.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _build(tmp_path: Path, content: bytes = b"chunk") -> Path:
    """A build of every profile, one small store per profile."""
    build = tmp_path / "build"
    for profile in script.profiles():
        store = build / profile.name / "stores" / testing.CANOPY_SITE / "gnss"
        (store / "chunks").mkdir(parents=True)
        (store / "chunks" / "c0").write_bytes(zstd.compress(content))
        (store / "config.yaml").write_text(f"site: {testing.SITE_ID}\n")
    return build


def test_a_build_packs_to_the_same_sha256_twice(tmp_path):
    build = _build(tmp_path)

    script.pack(build, tmp_path / "a")
    script.pack(build, tmp_path / "b")

    first = (tmp_path / "a" / script.SUMS_FILE).read_text()
    assert first == (tmp_path / "b" / script.SUMS_FILE).read_text()
    assert f"default/{testing.CANOPY_SITE}-gnss.zip" in first


def test_a_store_with_a_local_path_in_a_zstd_frame_is_refused(tmp_path):
    build = tmp_path / "build"
    _build(tmp_path, content=str(build.resolve() / "stores").encode())

    with pytest.raises(SystemExit, match="holds a local path"):
        script.pack(build, tmp_path / "zips")


def test_a_file_whose_zstd_frame_does_not_decompress_is_named(tmp_path):
    build = _build(tmp_path)
    broken = build / "default" / "stores" / testing.CANOPY_SITE / "gnss" / "broken"
    broken.write_bytes(script.ZSTD_MAGIC + b"not a frame")

    with pytest.raises(SystemExit, match="broken could not be decompressed"):
        script.pack(build, tmp_path / "zips")


def test_zips_with_a_wrong_sha256_are_refused(tmp_path):
    zips = tmp_path / "zips"
    script.pack(_build(tmp_path), zips)
    sums = zips / script.SUMS_FILE
    sums.write_text(
        "".join(
            f"{'0' * 64}  {line.split()[1]}\n" for line in sums.read_text().splitlines()
        )
    )

    with pytest.raises(RuntimeError, match="sha256"):
        script.reference_folder(zips, tmp_path / "work")


def test_zips_unpack_into_a_build_folder(tmp_path):
    zips = tmp_path / "zips"
    script.pack(_build(tmp_path), zips)

    folder = script.reference_folder(zips, tmp_path / "work")

    script.require_profiles(folder)
    store = folder / "default" / "stores" / testing.CANOPY_SITE / "gnss"
    assert (store / "config.yaml").read_text() == f"site: {testing.SITE_ID}\n"
