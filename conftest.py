"""Pytest configuration for canvodpy workspace."""

import logging
from collections.abc import Iterator

import pytest

from canvod.config import loader
from canvod.utils import testing

# ============================================================================
# Settings: made-up, never the user's own
# ============================================================================


@pytest.fixture(autouse=True)
def _made_up_settings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Code that loads the settings itself reads the made-up ones.

    Never the user's own ``config/canvod-settings.yaml`` (CI has none).
    A test that needs other settings sets ``CANVOD_CONFIG_DIR`` itself.
    The cache is cleared because tests change the settings object. The
    cached function is kept, because a test may replace it with a plain one
    that is still in place when this fixture ends.
    """
    folder = tmp_path_factory.getbasetemp() / "made-up-settings"
    if not folder.exists():
        testing.write_settings(folder)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    monkeypatch.delenv("CANVOD_CONFIG_FILE", raising=False)
    cached = loader._load_config_cached
    cached.cache_clear()
    yield
    cached.cache_clear()


# ============================================================================
# Dask Shutdown Noise Suppression
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def _suppress_dask_shutdown_noise():
    """Silence Dask nanny/worker loggers during pytest teardown.

    Dask's nanny runs background threads that may try to log after pytest has
    closed ``sys.stderr``, raising ``ValueError: I/O operation on closed file``.
    Disabling the ``distributed`` logger hierarchy in the teardown phase
    prevents this.
    """
    yield
    for name in ("distributed", "distributed.nanny", "distributed.worker"):
        logging.getLogger(name).disabled = True
