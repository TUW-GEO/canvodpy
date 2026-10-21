"""Packing the reference stores and unpacking the zips (spec #318, #325)."""

import getpass
import importlib.util
import socket
import sys
from compression import zstd
from pathlib import Path

import icechunk
import pytest
import zarr

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


def _commit(store: Path, metadata: dict) -> None:
    """A commit to ``store`` with ``metadata``; creates the store if needed."""
    storage = icechunk.local_filesystem_storage(str(store))
    repo = icechunk.Repository.open_or_create(storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="a").attrs["n"] = len(
        list(repo.ancestry(branch="main"))
    )
    session.commit("write", metadata=metadata)


def _build(tmp_path: Path, content: bytes = b"chunk") -> Path:
    """A build of every profile, one small store per profile."""
    build = tmp_path / "build"
    for profile in script.profiles():
        store = build / profile.name / "stores" / testing.CANOPY_SITE / "gnss"
        _commit(store, {"environment": {"os": None, "uv_lock_hash": "0" * 64}})
        (store / "extra").mkdir()
        (store / "extra" / "c0").write_bytes(zstd.compress(content))
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


def _gnss(build: Path) -> Path:
    return build / "default" / "stores" / testing.CANOPY_SITE / "gnss"


def test_a_store_whose_commits_record_the_computer_is_refused(tmp_path):
    build = _build(tmp_path)
    _commit(_gnss(build), {"environment": {"os": "Linux", "cpu_count": 8}})
    _commit(_gnss(build), {"environment": {"os": None}})

    with pytest.raises(SystemExit, match=r"records the computer \(os, cpu_count\)"):
        script.pack(build, tmp_path / "zips")


def test_a_store_that_names_this_computer_is_refused(tmp_path):
    build = _build(tmp_path)
    _commit(_gnss(build), {"run": {"host": socket.gethostname()}})

    with pytest.raises(SystemExit, match="names this computer"):
        script.pack(build, tmp_path / "zips")


def test_a_store_that_names_the_user_in_a_commit_is_refused(tmp_path):
    build = _build(tmp_path)
    _commit(_gnss(build), {"run": {"by": getpass.getuser()}})

    with pytest.raises(SystemExit, match=r"commit \w+ names '"):
        script.pack(build, tmp_path / "zips")


def test_a_commit_on_another_branch_is_searched_too(tmp_path):
    build = _build(tmp_path)
    storage = icechunk.local_filesystem_storage(str(_gnss(build)))
    repo = icechunk.Repository.open(storage)
    repo.create_branch("side", repo.lookup_branch("main"))
    session = repo.writable_session("side")
    zarr.open_group(session.store, mode="a").attrs["side"] = True
    session.commit("side", metadata={"environment": {"memory_gb": 16.0}})

    with pytest.raises(SystemExit, match=r"records the computer \(memory_gb\)"):
        script.pack(build, tmp_path / "zips")


def test_a_site_settings_file_gives_position_publisher_and_references(tmp_path):
    from canvod.config import load_config

    settings_dir, sites, extra = script.read_runs(script.PROFILES / "default")
    site = next(iter(sites))
    position = {"latitude": 47.7, "longitude": 16.3, "altitude_m": 666.7}

    path = script.output_settings(tmp_path, site, None, None, extra, position)
    config = load_config(config_dir=settings_dir, config_file=path)

    site_config = config.sites.sites[site]
    assert (site_config.latitude, site_config.longitude, site_config.altitude_m) == (
        47.7,
        16.3,
        666.7,
    )
    assert config.processing.metadata.website == testing.WEBSITE
    assert config.processing.metadata.publisher_url == testing.WEBSITE
    references = config.processing.references
    assert references.access_url == (
        "https://huggingface.co/datasets/nfb2021/canvodpy-reference-stores"
    )
    assert references.related_stores == [f"{site}-gnss", f"{site}-vod"]


@pytest.mark.skipif(
    not (script.TEST_DATA / "rinex_v2_11").is_dir(), reason="needs the test data"
)
def test_a_site_without_a_position_in_its_files_gets_the_test_position(tmp_path):
    settings_dir, sites, _ = script.read_runs(script.PROFILES / "default")
    import yaml

    settings = yaml.safe_load((settings_dir / "canvod-settings.yaml").read_text())
    site = "moflux_rinex_v2_11"
    root = script.ROOT / settings["sites"][site]["gnss_site_data_root"]
    copy = script.copy_with_position(root, tmp_path / site)

    position = script.site_position(settings["sites"][site], copy, sites[site]["start"])

    assert position == {
        "latitude": testing.LATITUDE,
        "longitude": testing.LONGITUDE,
        "altitude_m": testing.ALTITUDE_M,
    }
