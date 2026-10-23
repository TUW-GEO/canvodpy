"""Pytest configuration and shared fixtures for canvod-store tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import xarray as xr
from _helpers import (
    _FIXTURES_DIR,
    DAY0_STORE_PATH,
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
    "DAY0_STORE_PATH",
    "GROUP",
    "RINEX_CANOPY_DIR",
    "RINEX_REFERENCE_DIR",
    "_FIXTURES_DIR",
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
def day0_store_path() -> Path:
    """Return the path to the frozen day 0 regression store.

    Skip the test if the fixture hasn't been built yet — run
    ``python packages/canvod-store/tests/build_day0_store.py`` first.
    """
    if not DAY0_STORE_PATH.exists():
        pytest.skip(
            f"Day 0 store not found at {DAY0_STORE_PATH}. "
            "Run `python packages/canvod-store/tests/build_day0_store.py` first."
        )
    return DAY0_STORE_PATH


@pytest.fixture(scope="session")
def day0_snapshot(day0_store_path) -> dict[str, Any]:
    """Load the day 0 snapshot metadata from the fixture directory."""
    import json

    snapshot_file = _FIXTURES_DIR / "day0_snapshot.json"
    if not snapshot_file.exists():
        pytest.skip("Day 0 snapshot JSON not found.")
    return json.loads(snapshot_file.read_text())
