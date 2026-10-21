"""A store can be read without a settings file; writing needs one.

Seam: ``open_gnss_store``/``open_vod_store`` with ``CANVOD_CONFIG_DIR``
pointing at a folder without a settings file, as for a scientist who
downloaded a store or got one from a colleague.
"""

from __future__ import annotations

import pytest
import yaml
from _helpers import make_synthetic_dataset, new_gnss_store, new_vod_store
from canvod.config import loader

from canvod.store import open_gnss_store, open_vod_store

GROUP = "canopy_01"


@pytest.fixture
def written_store(tmp_path):
    """A GNSS store with one group, written with the made-up settings."""
    store = new_gnss_store(tmp_path / "gnss")
    store.write_initial_group(make_synthetic_dataset(slot=0), GROUP)
    return store.store_path


@pytest.fixture
def no_settings_file(tmp_path, monkeypatch):
    """The settings folder holds no settings file."""
    folder = tmp_path / "no-settings"
    folder.mkdir()
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    loader._load_config_cached.cache_clear()
    return folder


def test_a_store_opens_and_reads_without_settings(written_store, no_settings_file):
    store = open_gnss_store(written_store)

    data = store.read_group(GROUP)

    assert data.sizes["epoch"] == 180
    assert store.get_history()
    assert GROUP in store.get_group_names()["main"]


def test_a_vod_store_opens_without_settings(tmp_path, no_settings_file):
    path = new_vod_store(tmp_path / "vod").store_path

    assert open_vod_store(path).store_path == path


def test_branches_are_created_and_deleted_without_settings(
    written_store, no_settings_file
):
    store = open_gnss_store(written_store)
    snapshot = store.get_history()[0]["snapshot_id"]

    store.create_branch("explore", snapshot)
    store.delete_branch("explore")

    assert "explore" not in store.repo.list_branches()


def test_writing_without_settings_is_refused_and_names_config_init(
    written_store, no_settings_file
):
    store = open_gnss_store(written_store)
    before = store.repo.lookup_branch("main")

    with pytest.raises(FileNotFoundError, match="canvodpy config init"):
        store.write_initial_group(make_synthetic_dataset(slot=0), "canopy_02")

    assert store.repo.lookup_branch("main") == before


def test_a_broken_settings_file_still_fails_the_open(written_store, no_settings_file):
    (no_settings_file / "canvod-settings.yaml").write_text("processing: [\n")

    with pytest.raises(yaml.YAMLError, match="canvod-settings.yaml"):
        open_gnss_store(written_store)
