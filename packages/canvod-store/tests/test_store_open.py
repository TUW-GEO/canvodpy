"""Constructing a store opens it and never creates it (#236)."""

from __future__ import annotations

import re

import pytest
from canvod.store_metadata.testing import give_test_metadata

from canvod.store import (
    MyIcechunkStore,
    create_gnss_store,
    open_gnss_store,
    open_vod_store,
)


@pytest.mark.parametrize(
    "open_store", [MyIcechunkStore, open_gnss_store, open_vod_store]
)
def test_a_missing_store_is_refused_and_nothing_is_created(tmp_path, open_store):
    path = tmp_path / "fangorn" / "gnss"

    with pytest.raises(FileNotFoundError, match=re.escape(str(path))) as error:
        open_store(path)

    assert "a run creates a store" in str(error.value)
    assert not path.exists()


def test_an_existing_store_opens(tmp_path):
    path = give_test_metadata(tmp_path / "fangorn" / "gnss")

    assert open_gnss_store(path).store_path == path


def test_create_gnss_store_is_deprecated_and_only_opens(tmp_path):
    path = tmp_path / "fangorn" / "gnss"

    with (
        pytest.warns(FutureWarning, match="open_gnss_store"),
        pytest.raises(FileNotFoundError),
    ):
        create_gnss_store(path)

    assert not path.exists()
