"""A run refuses a naming recipe that differs from the store's (#78)."""

import hashlib
from types import SimpleNamespace

import pytest
from canvod.utils import testing

from canvod.store_metadata import check_recipes

pytest.importorskip("canvod.filemap.recipe_files")

_RECIPE = b"name: fan\n"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A configuration folder with the recipe ``fan`` of Fangorn."""
    recipe = tmp_path / "recipes" / testing.CANOPY_SITE / "fan.yaml"
    recipe.parent.mkdir(parents=True)
    recipe.write_bytes(_RECIPE)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _repository(**receiver) -> dict:
    return {
        "identity": {"store_type": "gnss_store"},
        "spatial": {"site": {"name": testing.CANOPY_SITE}},
        "instruments": {
            "receivers": {"canopy_01": {"type": "canopy", "directory": "c", **receiver}}
        },
    }


def _site(recipe: str | None = "fan") -> SimpleNamespace:
    return SimpleNamespace(
        receivers={"canopy_01": SimpleNamespace(type="canopy", recipe=recipe)}
    )


def _check(repository: dict, site: SimpleNamespace) -> None:
    check_recipes(repository, site, testing.CANOPY_SITE, store_path="store")


def test_the_recipe_the_store_was_made_with_is_accepted(config_dir):
    sha = hashlib.sha256(_RECIPE).hexdigest()

    _check(_repository(recipe="fan", recipe_sha256=sha), _site())


def test_a_changed_recipe_is_refused_naming_the_amend_command(config_dir):
    old = hashlib.sha256(b"name: fan\nold: true\n").hexdigest()

    with pytest.raises(ValueError, match="recipe") as err:
        _check(_repository(recipe="fan", recipe_sha256=old), _site())

    message = str(err.value)
    assert "canopy_01" in message
    assert old[:12] in message
    assert hashlib.sha256(_RECIPE).hexdigest()[:12] in message
    assert (
        f"canvodpy store amend {testing.CANOPY_SITE} --store gnss "
        "--update-recipe canopy_01"
    ) in message


def test_a_store_without_the_sha256_of_its_recipe_is_refused(config_dir):
    with pytest.raises(ValueError, match="--update-recipe canopy_01"):
        _check(_repository(recipe="fan"), _site())


def test_a_recipe_the_store_does_not_name_is_refused(config_dir):
    with pytest.raises(ValueError, match="--update-recipe canopy_01"):
        _check(_repository(), _site())


def test_receivers_without_a_recipe_are_accepted(config_dir):
    _check(_repository(), _site(recipe=None))
