"""Shared fixtures for canvod-store-metadata tests."""

from collections.abc import Iterator

import pytest
from canvod.config import loader
from canvod.utils import testing


@pytest.fixture(autouse=True)
def _made_up_settings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Code that loads the settings itself reads the made-up ones.

    Never the user's own ``config/canvod-settings.yaml`` (CI has none).
    A test that needs other settings sets ``CANVOD_CONFIG_DIR`` itself.
    The cache is cleared because tests change the settings object.
    """
    folder = tmp_path_factory.getbasetemp() / "made-up-settings"
    if not folder.exists():
        testing.write_settings(folder)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    monkeypatch.delenv("CANVOD_CONFIG_FILE", raising=False)
    loader._load_config_cached.cache_clear()
    yield
    loader._load_config_cached.cache_clear()
