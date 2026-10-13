"""Tests for threading IcechunkConfig's repo-info rewrite knobs
(num_updates_per_repo_info_file, repo_update_retries) into the real
icechunk.RepositoryConfig object built by MyIcechunkStore.__init__.

Both knobs were previously left entirely at icechunk's hardcoded internal
defaults -- never exposed as config at all, although they matter for
performance. They must remain fully inert (icechunk's own defaults, i.e. None
on RepositoryConfig) when unset, matching this project's established opt-in-knob
convention (see zarr_async_concurrency).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from canvod.config.models import IcechunkConfig
from canvod.store_metadata.testing import create_test_store

from canvod.store import MyIcechunkStore


def _fake_cfg(ic_cfg: IcechunkConfig) -> SimpleNamespace:
    return SimpleNamespace(
        processing=SimpleNamespace(
            icechunk=ic_cfg,
            storage=SimpleNamespace(
                gnss_store_strategy="skip",
            ),
            logging=SimpleNamespace(log_path_depth=3),
        )
    )


def test_default_config_leaves_repo_info_knobs_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "canvod.config.load_config", lambda: _fake_cfg(IcechunkConfig())
    )
    store = MyIcechunkStore(create_test_store(tmp_path / "site" / "gnss_store"))
    assert store.config.num_updates_per_repo_info_file is None
    assert store.config.repo_update_retries is None


def test_num_updates_per_repo_info_file_is_threaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ic_cfg = IcechunkConfig(num_updates_per_repo_info_file=50)
    monkeypatch.setattr("canvod.config.load_config", lambda: _fake_cfg(ic_cfg))
    store = MyIcechunkStore(create_test_store(tmp_path / "site" / "gnss_store"))
    assert store.config.num_updates_per_repo_info_file == 50


def test_repo_update_retries_partial_settings_are_threaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only one of the three retry fields set -- the other two must stay None
    # on the constructed StorageRetriesSettings (icechunk's own per-field
    # default), not silently coerced to some other value.
    ic_cfg = IcechunkConfig(repo_update_max_tries=5)
    monkeypatch.setattr("canvod.config.load_config", lambda: _fake_cfg(ic_cfg))
    store = MyIcechunkStore(create_test_store(tmp_path / "site" / "gnss_store"))

    retries = store.config.repo_update_retries
    assert retries is not None
    assert retries.default.max_tries == 5
    assert retries.default.initial_backoff_ms is None
    assert retries.default.max_backoff_ms is None


def test_repo_update_retries_full_settings_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ic_cfg = IcechunkConfig(
        repo_update_max_tries=5,
        repo_update_initial_backoff_ms=100,
        repo_update_max_backoff_ms=5_000,
    )
    monkeypatch.setattr("canvod.config.load_config", lambda: _fake_cfg(ic_cfg))
    store = MyIcechunkStore(create_test_store(tmp_path / "site" / "gnss_store"))

    retries = store.config.repo_update_retries
    assert retries is not None
    assert retries.default.max_tries == 5
    assert retries.default.initial_backoff_ms == 100
    assert retries.default.max_backoff_ms == 5_000
