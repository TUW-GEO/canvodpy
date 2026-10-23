"""The made-up settings of ``canvod.utils.testing`` load as settings."""

from pathlib import Path

from canvod.config import load_config
from canvod.utils import testing


def test_made_up_settings_load(tmp_path: Path) -> None:
    path = testing.write_settings(tmp_path / "config")

    config = load_config(config_dir=path.parent)

    assert config.processing.metadata.author == testing.PERSON_NAME
    assert config.processing.metadata.naming_authority == testing.NAMING_AUTHORITY
    assert testing.SITE_KEY in config.sites.sites
    assert config.processing.storage.stores_root_dir == tmp_path / "config" / "stores"
