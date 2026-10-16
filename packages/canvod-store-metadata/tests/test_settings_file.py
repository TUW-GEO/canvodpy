"""Build a settings mapping from a store (canvodpy config init --from-store).

`settings.py` builds the ``canvod-settings.yaml`` mapping that reproduces a
store: its content settings unchanged, the site and receivers from its
repository metadata, and ``TODO`` for the machine values. These tests make a
store with a run's settings (as `test_content_settings.py` does) and check
the mapping.
"""

from __future__ import annotations

import copy
import itertools
from pathlib import Path

import pytest
import yaml
from canvod.config import load_config
from canvod.utils import testing
from test_writers import _settings

from canvod.store_metadata import (
    ensure_store_metadata,
    read_repository_metadata,
    settings_from_store,
)
from canvod.store_metadata.content import differences, run_content_settings

SITE = testing.SITE_KEY
CONTENT_NAMES = ["canopy_01", "reference_01_canopy_01"]


def _create_store(tmp_path: Path, *, root: str = "root", name: str = "rinex") -> Path:
    """A GNSS store at ``tmp_path/<root>/<site>/<name>`` with content settings."""
    store = tmp_path / root / SITE / name
    ensure_store_metadata(
        store,
        config=_settings(tmp_path),
        site_name=SITE,
        store_type="gnss_store",
        source_format="rinex3",
        names=CONTENT_NAMES,
    )
    return store


def _fill_todo(settings, tmp_path: Path):
    """Every ``TODO`` becomes a folder (a path), so the settings load."""
    counter = itertools.count()

    def walk(node):
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if node == "TODO":
            return str(tmp_path / f"todo_{next(counter)}")
        return node

    return walk(copy.deepcopy(settings))


def test_settings_reproduce_the_stores_content_settings(tmp_path):
    store = _create_store(tmp_path)
    settings = _fill_todo(settings_from_store(store), tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    metadata = settings["processing"]["metadata"]
    metadata["author"] = "Test Author"
    metadata["email"] = "a@example.com"
    metadata["institution"] = "Test Institution"
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(settings, sort_keys=False)
    )
    config = load_config(config_dir=config_dir)

    stored = read_repository_metadata(store)["content_settings"]
    assert differences(stored, run_content_settings(config, SITE), SITE) == []


def test_settings_hold_no_path_or_credential_of_the_creating_machine(tmp_path):
    store = _create_store(tmp_path)
    settings = settings_from_store(store)
    text = yaml.safe_dump(settings, sort_keys=False)

    # A path to the creating run's working folders must not be copied; the
    # machine values are placeholders. ``stores_root_dir`` holds the store's
    # own root, so it is the one path in the output.
    folder = tmp_path / "settings"
    for name in ("data", "logs", "aux", "stores"):
        assert str(folder / name) not in text
    assert "TODO" in text
    # Credentials are never written; an S3 store's AWS_* ones are only echoed.
    assert "credentials" not in text
    assert "nasa_earthdata" not in text


def test_a_store_without_content_settings_names_the_migrate_command(tmp_path):
    from canvod.store_metadata.testing import give_test_metadata

    store = give_test_metadata(tmp_path / "old")

    from canvod.store_metadata import MissingContentSettingsError

    with pytest.raises(MissingContentSettingsError, match="migrate-metadata"):
        settings_from_store(store)


def test_the_store_root_and_name_come_from_the_store_argument(tmp_path):
    store = _create_store(tmp_path)
    settings = settings_from_store(store)

    storage = settings["processing"]["storage"]
    assert storage["stores_root_dir"] == str(tmp_path / "root")
    assert storage["gnss_store_name"] == "rinex"
    # The receivers' free fields come from the repository metadata.
    receivers = settings["sites"][SITE]["receivers"]
    assert receivers["reference_01"]["directory"] == "TODO"
    assert receivers["reference_01"]["reader_format"] == "auto"
    assert receivers["reference_01"]["paired_canopies"] == ["canopy_01"]
