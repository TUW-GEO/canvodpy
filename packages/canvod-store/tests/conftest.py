"""Pytest configuration and shared fixtures for canvod-store tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import xarray as xr
from _helpers import (
    FIXTURES_DIR,
    GROUP,
    RINEX_CANOPY_DIR,
    RINEX_REFERENCE_DIR,
    _array_checksum,
    make_synthetic_dataset,
    new_gnss_store,
)

from canvod.config import loader
from canvod.utils import testing

__all__ = [
    "FIXTURES_DIR",
    "GROUP",
    "RINEX_CANOPY_DIR",
    "RINEX_REFERENCE_DIR",
    "_array_checksum",
    "make_synthetic_dataset",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture(scope="session")
def synthetic_day() -> list[xr.Dataset]:
    """Return 4 synthetic 15-min datasets covering the first hour of a day."""
    return [make_synthetic_dataset(slot=i) for i in range(4)]


@pytest.fixture
def tmp_store(tmp_path):
    """Return a fresh MyIcechunkStore in a temporary directory."""
    return new_gnss_store(tmp_path / "test_store")


@pytest.fixture(scope="session")
def day0_snapshot() -> dict[str, Any]:
    """Load the frozen day 0 snapshot (committed, built by ``build_day0_store.py``)."""
    import json

    return json.loads((FIXTURES_DIR / "day0_snapshot.json").read_text())
