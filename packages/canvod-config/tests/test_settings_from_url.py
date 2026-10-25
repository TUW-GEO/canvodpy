"""Settings read from a URL (canvod.config.remote).

Downloads go to testing.RemoteFileServer, never to the network.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from canvod.config import load_config, remote
from canvod.config.loader import get_default_config_dir
from canvod.config.remote import resolve_config_dir, settings_url
from canvod.utils import remote_file, testing
from canvod.utils.remote_file import RemoteFetchError, RemoteURLError

BASE = (
    f"https://raw.githubusercontent.com/the-inklings/red-book/{testing.COMMIT}/config"
)
SETTINGS_URL = f"{BASE}/canvod-settings.yaml"
TAG_URL = SETTINGS_URL.replace(testing.COMMIT, "refs/tags/v1")
BRANCH_URL = SETTINGS_URL.replace(testing.COMMIT, "main")
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
    """A new run: nothing fetched, folders in tmp_path, no token or config
    folder from the environment."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    _new_run(monkeypatch)
    for name in (
        *remote_file.TOKEN_VARIABLES,
        "CANVOD_CONFIG_DIR",
        "CANVOD_CONFIG_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def _new_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # Set (empty) through monkeypatch, so run_folder()'s value is undone.
    monkeypatch.setenv("CANVODPY_RUN_FOLDER", "")
    monkeypatch.setattr(remote_file, "_FOLDER", None)
    monkeypatch.setattr(remote_file, "_MADE_HERE", False)
    monkeypatch.setattr(remote, "_FOLDERS", {})


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    srv = testing.RemoteFileServer()
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", srv.origin)
    yield srv
    srv.close()


def test_settings_from_a_url_load(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path))

    folder = resolve_config_dir(SETTINGS_URL)

    config = load_config(config_dir=folder)
    assert config.processing.metadata.author == testing.PERSON_NAME
    assert testing.SITE_KEY in config.sites.sites


def test_a_recipe_name_is_read_at_the_same_link(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL, RECIPE)

    folder = resolve_config_dir(SETTINGS_URL)

    recipe = folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    assert recipe.read_bytes() == RECIPE


@pytest.mark.parametrize(
    ("url", "ref"), [(TAG_URL, "refs/tags/v1"), (BRANCH_URL, "main")]
)
def test_a_tag_or_branch_link_reads_the_recipe_there(server, tmp_path, url, ref):
    server.serve(url, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL.replace(testing.COMMIT, ref), RECIPE)

    folder = resolve_config_dir(url)

    assert (
        folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    ).is_file()


def test_a_missing_recipe_names_the_receiver_and_the_url(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path, "entmoot"))

    with pytest.raises(RemoteFetchError) as excinfo:
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

    with pytest.raises(RemoteURLError, match="recipe name"):
        resolve_config_dir(SETTINGS_URL)


def test_the_url_is_known_to_the_run_only(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path))

    folder = resolve_config_dir(SETTINGS_URL)

    assert settings_url(folder) == SETTINGS_URL
    assert SETTINGS_URL not in "".join(
        p.read_text() for p in folder.rglob("*") if p.is_file()
    )


def test_a_local_folder_has_no_url(tmp_path):
    assert settings_url(testing.write_settings(tmp_path / "config").parent) is None


def test_a_run_fetches_once(server, tmp_path):
    server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    server.serve(RECIPE_URL, RECIPE)

    first = resolve_config_dir(SETTINGS_URL)

    assert resolve_config_dir(SETTINGS_URL) == first
    assert len(server.requests) == 2


def test_every_run_fetches_the_settings_and_recipes_again(
    server, tmp_path, monkeypatch
):
    server.serve(BRANCH_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    recipe_url = RECIPE_URL.replace(testing.COMMIT, "main")
    server.serve(recipe_url, RECIPE)
    resolve_config_dir(BRANCH_URL)
    changed = RECIPE + b"# the branch moved on\n"
    server.serve(recipe_url, changed)
    _new_run(monkeypatch)

    folder = resolve_config_dir(BRANCH_URL)

    recipe = folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    assert recipe.read_bytes() == changed
    assert len(server.requests) == 4


def test_a_second_run_in_the_same_process_fetches_again(server, tmp_path):
    # A notebook that runs twice: the recipe changed on the branch between.
    server.serve(BRANCH_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
    recipe_url = RECIPE_URL.replace(testing.COMMIT, "main")
    server.serve(recipe_url, RECIPE)
    first = resolve_config_dir(BRANCH_URL)
    changed = RECIPE + b"# changed on the branch\n"
    server.serve(recipe_url, changed)

    remote_file.new_run()
    folder = resolve_config_dir(BRANCH_URL)

    assert folder != first
    recipe = folder / "recipes" / testing.SITE_KEY / f"{testing.SITE_KEY}_canopy.yaml"
    assert recipe.read_bytes() == changed
    assert settings_url(folder) == BRANCH_URL
    # The earlier run's folder is removed, and with it what was known of it.
    assert not first.exists()
    assert settings_url(first) is None
    assert list(remote._FOLDERS.values()) == [folder]


def test_a_run_without_network_names_the_url(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", "http://127.0.0.1:9")

    with pytest.raises(RemoteFetchError, match="needs network access") as excinfo:
        resolve_config_dir(SETTINGS_URL)

    assert SETTINGS_URL in str(excinfo.value)


def test_a_settings_file_that_is_not_a_mapping_is_refused(server):
    server.serve(SETTINGS_URL, b"- just\n- a list\n")

    with pytest.raises(RemoteFetchError, match="not a settings file"):
        resolve_config_dir(SETTINGS_URL)


def test_config_dir_variable_may_be_a_url(server, tmp_path, monkeypatch):
    server.serve(SETTINGS_URL, _settings(tmp_path))
    monkeypatch.setenv("CANVOD_CONFIG_DIR", SETTINGS_URL)

    folder = get_default_config_dir()

    assert settings_url(folder) == SETTINGS_URL
    assert load_config().processing.metadata.author == testing.PERSON_NAME


def _overlay(tmp_path: Path, recipe: str) -> Path:
    """An overlay that gives the canopy receiver the recipe ``recipe``."""
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        json.dumps(
            {
                "sites": {
                    testing.SITE_KEY: {"receivers": {"canopy_01": {"recipe": recipe}}}
                }
            }
        )
    )
    return overlay


class TestOverlayRecipes:
    """An overlay's recipes come from the settings' link too (#539)."""

    def test_a_recipe_only_the_overlay_names_is_fetched(self, server, tmp_path):
        server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
        server.serve(RECIPE_URL, RECIPE)
        older = f"{testing.SITE_KEY}_canopy_01s"
        older_recipe = f"name: {older}\n".encode()
        server.serve(f"{BASE}/recipes/{testing.SITE_KEY}/{older}.yaml", older_recipe)
        folder = resolve_config_dir(SETTINGS_URL)

        config = load_config(config_dir=folder, config_file=_overlay(tmp_path, older))

        receiver = config.sites.sites[testing.SITE_KEY].receivers["canopy_01"]
        assert receiver.recipe == older
        path = folder / "recipes" / testing.SITE_KEY / f"{older}.yaml"
        assert path.read_bytes() == older_recipe

    def test_a_missing_overlay_recipe_names_the_overlay_and_the_url(
        self, server, tmp_path
    ):
        server.serve(SETTINGS_URL, _settings(tmp_path))
        folder = resolve_config_dir(SETTINGS_URL)
        overlay = _overlay(tmp_path, "entmoot")

        with pytest.raises(RemoteFetchError) as excinfo:
            load_config(config_dir=folder, config_file=overlay)

        message = str(excinfo.value)
        assert "'entmoot'" in message
        assert "canopy_01" in message
        assert str(overlay) in message
        assert f"{BASE}/recipes/{testing.SITE_KEY}/entmoot.yaml" in message

    def test_an_overlay_on_a_local_folder_fetches_nothing(self, server, tmp_path):
        local = tmp_path / "local"
        local.mkdir()
        (local / "canvod-settings.yaml").write_bytes(_settings(tmp_path))
        overlay = _overlay(tmp_path, f"{testing.SITE_KEY}_canopy")

        config = load_config(config_dir=local, config_file=overlay)

        receiver = config.sites.sites[testing.SITE_KEY].receivers["canopy_01"]
        assert receiver.recipe == f"{testing.SITE_KEY}_canopy"
        assert not (local / "recipes").exists()

    def test_a_copy_that_fails_leaves_no_half_written_recipe(
        self, server, tmp_path, monkeypatch
    ):
        """Another run of the process may read the folder while a recipe is
        copied into it: it sees the whole recipe or none."""
        server.serve(SETTINGS_URL, _settings(tmp_path, f"{testing.SITE_KEY}_canopy"))
        server.serve(RECIPE_URL, RECIPE)
        older = f"{testing.SITE_KEY}_canopy_01s"
        server.serve(
            f"{BASE}/recipes/{testing.SITE_KEY}/{older}.yaml",
            f"name: {older}\n".encode(),
        )
        folder = resolve_config_dir(SETTINGS_URL)

        def half_copy(src, dst, *args, **kwargs):
            Path(dst).write_bytes(Path(src).read_bytes()[:3])
            raise OSError("disk full")

        monkeypatch.setattr(remote.shutil, "copyfile", half_copy)
        with pytest.raises(RemoteFetchError, match="disk full"):
            load_config(config_dir=folder, config_file=_overlay(tmp_path, older))

        recipes = folder / "recipes" / testing.SITE_KEY
        assert sorted(p.name for p in recipes.iterdir()) == [
            f"{testing.SITE_KEY}_canopy.yaml"
        ]
