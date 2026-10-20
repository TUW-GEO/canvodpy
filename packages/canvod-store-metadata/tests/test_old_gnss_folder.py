"""A run stops when the site still has the GNSS store's old folder (#456).

Before v1.0.0 the GNSS store's folder was ``rinex``. A run that writes to
``gnss/`` while ``rinex/`` holds a store would start a second GNSS store
next to the old one; it stops before writing and names the migration.
"""

from pathlib import Path

import pytest
from canvod.utils import testing
from test_vod_content_settings import GNSS_NAMES
from test_writers import _settings

from canvod.store_metadata import ensure_store_metadata, store_exists
from canvod.store_metadata.testing import create_test_store


def _start(path: Path, settings) -> dict:
    return ensure_store_metadata(
        path,
        config=settings,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=GNSS_NAMES,
    )


def test_a_run_next_to_a_rinex_store_stops_and_names_the_migration(tmp_path):
    site = tmp_path / testing.SITE_KEY
    create_test_store(site / "rinex")

    with pytest.raises(ValueError, match=f"canvodpy store migrate {testing.SITE_KEY}"):
        _start(site / "gnss", _settings(tmp_path))

    assert not store_exists(site / "gnss")


def test_a_run_with_both_folders_stops(tmp_path):
    site = tmp_path / testing.SITE_KEY
    settings = _settings(tmp_path)
    _start(site / "gnss", settings)
    create_test_store(site / "rinex")

    with pytest.raises(ValueError, match="rinex"):
        _start(site / "gnss", settings)


def test_a_folder_named_rinex_without_a_store_is_no_obstacle(tmp_path):
    site = tmp_path / testing.SITE_KEY
    (site / "rinex").mkdir(parents=True)

    _start(site / "gnss", _settings(tmp_path))
