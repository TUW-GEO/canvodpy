"""A store takes its site name from its own metadata (#239)."""

from __future__ import annotations

import pytest
from canvod.store_metadata import open_repository
from canvod.store_metadata.testing import give_test_metadata
from canvod.utils import testing

from canvod.store import MyIcechunkStore


def test_the_site_name_comes_from_the_metadata_not_the_directory(tmp_path):
    path = give_test_metadata(tmp_path / "moved-elsewhere" / "gnss")

    store = MyIcechunkStore(path)

    assert store.site_name == testing.SITE_KEY


def test_the_site_name_is_read_only(tmp_path):
    store = MyIcechunkStore(give_test_metadata(tmp_path / "fangorn" / "gnss"))

    with pytest.raises(AttributeError):
        store.site_name = "isengard"  # ty: ignore[invalid-assignment]


@pytest.fixture
def store_without_metadata(tmp_path):
    path = tmp_path / "fangorn" / "gnss"
    open_repository(path, create=True)
    return MyIcechunkStore(path)


def test_a_store_without_metadata_names_the_command_that_fixes_it(
    store_without_metadata,
):
    with pytest.raises(ValueError, match="migrate-metadata") as error:
        _ = store_without_metadata.site_name

    assert str(store_without_metadata.store_path) in str(error.value)


def test_the_display_of_a_store_without_metadata_shows_the_hint(
    store_without_metadata,
):
    html = store_without_metadata._repr_html_()

    assert "migrate-metadata" in html
