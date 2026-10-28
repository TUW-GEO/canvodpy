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
from types import SimpleNamespace

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


def _create_store(tmp_path: Path, *, root: str = "root", name: str = "gnss") -> Path:
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


def test_settings_from_a_store_from_before_precise_say_precise(tmp_path):
    """A store created with ``final`` (v1.0.0) gives ``precise`` (ADR 0023)."""
    config = _settings(tmp_path)
    # Assigning skips the settings check: the store records the old name.
    config.processing.params.ephemeris_source = "final"  # ty: ignore[invalid-assignment]
    store = tmp_path / "root" / SITE / "gnss"
    ensure_store_metadata(
        store,
        config=config,
        site_name=SITE,
        store_type="gnss_store",
        source_format="rinex3",
        names=CONTENT_NAMES,
    )
    stored = read_repository_metadata(store)["content_settings"]["settings"]
    assert stored["processing"]["params"]["ephemeris_source"] == "final"

    settings = settings_from_store(store)

    assert settings["processing"]["params"]["ephemeris_source"] == "precise"


def test_settings_from_a_broadcast_store_load_and_match_it(tmp_path):
    """A broadcast store records no product (#574); its settings still load."""
    config = _settings(tmp_path)
    config.processing.params.ephemeris_source = "broadcast"
    store = tmp_path / "root" / SITE / "gnss"
    ensure_store_metadata(
        store,
        config=config,
        site_name=SITE,
        store_type="gnss_store",
        source_format="rinex3",
        names=CONTENT_NAMES,
    )
    settings = _fill_todo(settings_from_store(store), tmp_path)

    assert "agency" not in settings["processing"].get("aux_data", {})
    assert "product_type" not in settings["processing"].get("aux_data", {})
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    metadata = settings["processing"]["metadata"]
    metadata["author"] = "J. R. R. Tolkien"
    metadata["email"] = "jrrt@example.com"
    metadata["institution"] = "Fangorn"
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(settings, sort_keys=False)
    )
    loaded = load_config(config_dir=config_dir)

    stored = read_repository_metadata(store)["content_settings"]
    assert differences(stored, run_content_settings(loaded, SITE), SITE) == []


_RECIPE = (
    "name: rx\nsite: FAN\nagency: INK\nreceiver_number: 1\n"
    "glob: '*.rnx'\nfields:\n  - skip: 3\n"
)


def _store_with_recipe(tmp_path: Path, recipe: str) -> Path:
    """A GNSS store whose canopy receiver has the naming recipe ``recipe``."""
    config = _settings(tmp_path)
    config.sites.sites[SITE].receivers["canopy_01"].recipe = recipe
    store = tmp_path / "root" / SITE / "gnss"
    ensure_store_metadata(
        store,
        config=config,
        site_name=SITE,
        store_type="gnss_store",
        source_format="rinex3",
        names=CONTENT_NAMES,
    )
    return store


def test_the_store_records_the_sha256_of_a_local_recipe(tmp_path, monkeypatch):
    pytest.importorskip("canvod.filemap.recipe_files")
    import hashlib

    path = tmp_path / "config" / "recipes" / SITE / "rx.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(_RECIPE.encode())
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path / "config"))
    store = _store_with_recipe(tmp_path, "rx")

    receiver = read_repository_metadata(store)["instruments"]["receivers"]["canopy_01"]
    assert receiver["recipe"] == "rx"
    assert receiver["recipe_sha256"] == hashlib.sha256(_RECIPE.encode()).hexdigest()


def test_show_prints_the_sha256_of_the_recipe(tmp_path, monkeypatch):
    pytest.importorskip("canvod.filemap.recipe_files")
    import hashlib

    from canvod.store_metadata import format_metadata, read_metadata

    path = tmp_path / "config" / "recipes" / SITE / "rx.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(_RECIPE.encode())
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path / "config"))
    store = _store_with_recipe(tmp_path, "rx")

    text = format_metadata(read_metadata(store), section="instruments")
    assert f"recipe_sha256: {hashlib.sha256(_RECIPE.encode()).hexdigest()}" in text


def test_a_store_keeps_only_the_file_name_of_a_recipe_url(tmp_path, monkeypatch):
    from canvod.store_metadata import collectors

    # No download: the recipe's sha256 is made up.
    monkeypatch.setattr(collectors, "recipe_sha256_of", lambda site, recipe: "0" * 64)
    url = f"https://raw.githubusercontent.com/acc/recipes/main/{SITE}/rx.yaml"
    store = _store_with_recipe(tmp_path, url)

    receiver = read_repository_metadata(store)["instruments"]["receivers"]["canopy_01"]
    assert receiver["recipe"] == "rx.yaml"
    assert receiver["recipe_sha256"] == "0" * 64
    # The run owner gives the URL again.
    settings = settings_from_store(store)
    assert settings["sites"][SITE]["receivers"]["canopy_01"]["recipe"] == "TODO"


def test_a_store_is_not_created_without_the_sha256_of_its_recipe(tmp_path):
    with pytest.raises(ValueError, match="Found no naming recipe 'rx'"):
        _store_with_recipe(tmp_path, "rx")

    assert not (tmp_path / "root" / SITE / "gnss").exists()


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

    store = give_test_metadata(tmp_path / "gnss")

    from canvod.store_metadata import MissingContentSettingsError

    with pytest.raises(MissingContentSettingsError, match="migrate-metadata"):
        settings_from_store(store)


def test_the_store_root_and_name_come_from_the_store_argument(tmp_path):
    store = _create_store(tmp_path)
    settings = settings_from_store(store)

    storage = settings["processing"]["storage"]
    assert storage["stores_root_dir"] == str(tmp_path / "root")
    assert storage["gnss_store_name"] == "gnss"
    # The receivers' free fields come from the repository metadata.
    receivers = settings["sites"][SITE]["receivers"]
    assert receivers["reference_01"]["directory"] == "TODO"
    assert receivers["reference_01"]["reader_format"] == "auto"
    assert receivers["reference_01"]["paired_canopies"] == ["canopy_01"]


def test_a_suffixed_store_gives_settings_that_point_back_to_it(tmp_path):
    store = _create_store(tmp_path, name="gnss-test")
    settings = settings_from_store(store)

    assert settings["processing"]["storage"]["gnss_store_name"] == "gnss-test"


def test_a_local_store_not_at_the_site_layout_is_refused(tmp_path):
    """The parent folder must be the site the store records (#356 review)."""
    store = tmp_path / "copy" / "gnss"
    ensure_store_metadata(
        store,
        config=_settings(tmp_path),
        site_name=SITE,
        store_type="gnss_store",
        source_format="rinex3",
        names=CONTENT_NAMES,
    )

    with pytest.raises(ValueError, match=r"<stores_root_dir>/<site>/<store_name>") as e:
        settings_from_store(store)
    assert repr(SITE) in str(e.value)


@pytest.mark.parametrize(
    "store",
    ["s3://b/rinex", "s3://fangorn/rinex"],
)
def test_an_s3_url_not_at_the_site_layout_is_refused(store):
    """An S3 store with no bucket before the site part is refused (#356)."""
    from canvod.store_metadata.settings_file import _store_root_and_name

    with pytest.raises(ValueError, match=r"<stores_root_dir>/<site>/<store_name>"):
        _store_root_and_name(store, SITE)


def test_a_store_that_recorded_a_whole_recipe_url_still_matches(tmp_path, monkeypatch):
    from canvod.store_metadata import collectors
    from canvod.store_metadata.io import check_recipes

    monkeypatch.setattr(collectors, "recipe_sha256_of", lambda site, recipe: "0" * 64)
    url = f"https://raw.githubusercontent.com/acc/recipes/main/{SITE}/rx.yaml"
    store = _store_with_recipe(tmp_path, url)
    repository = read_repository_metadata(store)
    # What a store made before this change holds.
    repository["instruments"]["receivers"]["canopy_01"]["recipe"] = url

    site_config = SimpleNamespace(receivers={"canopy_01": SimpleNamespace(recipe=url)})
    check_recipes(repository, site_config, SITE, store_path=store)
