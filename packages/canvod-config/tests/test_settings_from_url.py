"""Settings read from a pinned URL (canvod.config.remote).

Downloads go to testing.PinnedFileServer, never to the network.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from canvod.config import load_config
from canvod.config.loader import get_default_config_dir
from canvod.config.remote import resolve_config_dir, settings_source
from canvod.utils import pinned, testing
from canvod.utils.pinned import PinnedFetchError, PinnedURLError

BASE = (
    f"https://raw.githubusercontent.com/the-inklings/red-book/{testing.COMMIT}/config"
)
SETTINGS_URL = f"{BASE}/canvod-settings.yaml"
TAG_URL = SETTINGS_URL.replace(testing.COMMIT, "refs/tags/v1")
RECIPE = f"name: {testing.SITE_KEY}_canopy\n".encode()
RECIPE_URL = f"{BASE}/recipes/{testing.SITE_KEY}/{testing.SITE_KEY}_canopy.yaml"


def _settings(tmp_path: Path, recipe: str | None = None) -> bytes:
    """The made-up settings, with ``recipe`` on the canopy receiver."""
    data = json.loads(testing.write_settings(tmp_path / "written").read_text())
    if recipe is not None:
        data["sites"][testing.SITE_KEY]["receivers"]["canopy_01"]["recipe"] = recipe
    return json.dumps(data, indent=2).encode()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cache in tmp_path, no token or config folder from the environment."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    for name in (*pinned.TOKEN_VARIABLES, "CANVOD_CONFIG_DIR", "CANVOD_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    srv = testing.PinnedFileServer()
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", srv.origin)
    yield srv
    srv.close()


def test_settings_from_a_url_load(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path))

    folder = resolve_config_dir(SETTINGS_URL)

    config = load_config(config_dir=folder)
    assert config.processing.metadata.author == testing.PERSON_NAME
    assert testing.SITE_KEY in config.sites.sites


def test_a_recipe_name_is_read_at_the_same_pin(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL, RECIPE)

    folder = resolve_config_dir(SETTINGS_URL)

    recipe = folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    assert recipe.read_bytes() == RECIPE


def test_a_tag_pin_reads_the_recipe_at_the_tag(server, tmp_path):
    server.serve(TAG_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL.replace(testing.COMMIT, "refs/tags/v1"), RECIPE)

    folder = resolve_config_dir(TAG_URL)

    assert (
        folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    ).is_file()


def test_a_missing_recipe_names_the_receiver_and_the_url(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path, "entmoot"))

    with pytest.raises(PinnedFetchError) as excinfo:
        resolve_config_dir(SETTINGS_URL)

    message = str(excinfo.value)
    assert "'entmoot'" in message
    assert "canopy_01" in message
    assert f"{BASE}/recipes/{testing.SITE_KEY}/entmoot.yaml" in message


def test_a_recipe_url_is_left_to_the_recipe_lookup(server, tmp_path):
    elsewhere = (
        "https://raw.githubusercontent.com/the-inklings/recipes/"
        + testing.COMMIT
        + "/x.yaml"
    )
    server.serve(SETTINGS_URL, _settings(tmp_path, elsewhere))

    folder = resolve_config_dir(SETTINGS_URL)

    assert not (folder / "recipes").exists()
    assert [path for path, _ in server.requests] == [
        SETTINGS_URL.removeprefix("https://raw.githubusercontent.com")
    ]


@pytest.mark.parametrize("name", ["../secrets", "a/b"])
def test_a_recipe_name_that_is_a_path_is_refused(server, tmp_path, name):
    server.serve(SETTINGS_URL, _settings(tmp_path, name))

    with pytest.raises(PinnedURLError, match="recipe name"):
        resolve_config_dir(SETTINGS_URL)


def test_the_source_is_recorded(server, tmp_path):
    body = _settings(tmp_path)
    server.serve(SETTINGS_URL, body)

    source = settings_source(resolve_config_dir(SETTINGS_URL))

    assert source is not None
    assert source.url == SETTINGS_URL
    assert source.commit == testing.COMMIT
    assert source.tag is None
    assert source.sha256 == hashlib.sha256(body).hexdigest()


def test_a_local_folder_has_no_source(tmp_path):
    assert settings_source(testing.write_settings(tmp_path / "config").parent) is None


def test_a_second_resolve_needs_no_network(server, tmp_path, monkeypatch):
    server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL, RECIPE)
    first = resolve_config_dir(SETTINGS_URL)
    server.close()
    monkeypatch.setattr(pinned, "_DOWNLOAD_ORIGIN", "http://127.0.0.1:9")

    assert resolve_config_dir(SETTINGS_URL) == first


def test_a_settings_file_that_is_not_a_mapping_is_refused(server):
    server.serve(SETTINGS_URL, b"- just\n- a list\n")

    with pytest.raises(PinnedFetchError, match="not a settings file"):
        resolve_config_dir(SETTINGS_URL)


def test_a_branch_url_is_refused():
    with pytest.raises(PinnedURLError, match="Settings file URL must be pinned"):
        resolve_config_dir(SETTINGS_URL.replace(testing.COMMIT, "main"))


def test_config_dir_variable_may_be_a_url(server, tmp_path, monkeypatch):
    server.serve(SETTINGS_URL, _settings(tmp_path))
    monkeypatch.setenv("CANVOD_CONFIG_DIR", SETTINGS_URL)

    folder = get_default_config_dir()

    assert settings_source(folder).url == SETTINGS_URL
    assert load_config().processing.metadata.author == testing.PERSON_NAME
