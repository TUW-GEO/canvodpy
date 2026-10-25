"""Tests for the deprecated zarr async chunk-write concurrency cap (#188).

``MyIcechunkStore._to_icechunk_throttled`` capped Zarr v3's per-array
chunk-write burst (zarr.config's "async.concurrency", default 10) when
IcechunkConfig.zarr_async_concurrency was set. It covered only the
store's own write methods, so it is deprecated: the store writes through
``_to_icechunk`` and the setting has no effect. The deprecated method
keeps its behavior until v2.0.0.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import xarray as xr
import zarr
from canvod.config.models import IcechunkConfig
from canvod.store_metadata.testing import create_test_store

from canvod.store import open_vod_store

pytestmark = pytest.mark.filterwarnings(
    "ignore:`_to_icechunk_throttled` is left over:FutureWarning"
)


@pytest.mark.filterwarnings("default")
def test_throttled_write_is_deprecated(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))

    with mock.patch("canvod.store.store.to_icechunk", lambda *a, **k: None):
        with store.writable_session() as session:
            with pytest.warns(FutureWarning, match="Use `_to_icechunk` instead"):
                store._to_icechunk_throttled(xr.Dataset(), session, group="x", mode="w")


def test_store_writes_ignore_the_configured_cap(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store._zarr_async_concurrency = 2
    before = zarr.config.get("async.concurrency")
    observed: dict[str, int] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = zarr.config.get("async.concurrency")

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk(xr.Dataset(), session, group="x", mode="w")

    assert observed["during"] == before


def test_default_config_does_not_throttle(tmp_path: Path) -> None:
    # No user config file present in the test environment, so the store
    # falls back to IcechunkConfig()'s own default -- must be None, so
    # deployments that never opt in pay zero concurrency-capping cost.
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    assert IcechunkConfig().zarr_async_concurrency is None
    assert store._zarr_async_concurrency is None


def test_unthrottled_write_does_not_touch_zarr_config(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    before = zarr.config.get("async.concurrency")
    observed: dict[str, int] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = zarr.config.get("async.concurrency")

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk_throttled(xr.Dataset(), session, group="x", mode="w")

    assert observed["during"] == before  # untouched, no scoping applied


def test_configured_concurrency_scopes_the_write(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store._zarr_async_concurrency = 2
    observed: dict[str, int] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = zarr.config.get("async.concurrency")

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk_throttled(xr.Dataset(), session, group="x", mode="w")

    assert observed["during"] == 2


def test_scoping_preserves_sibling_async_config_keys(tmp_path: Path) -> None:
    # zarr.config.set({"async": {"concurrency": N}}) replaces the whole
    # "async" subdict rather than merging -- a naive implementation drops
    # sibling keys (e.g. "timeout") for the scope of the block, which
    # crashed a production run with KeyError: 'timeout' when zarr-internal
    # code read it back mid-write.
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store._zarr_async_concurrency = 2
    before_async_cfg = dict(zarr.config.get("async"))
    assert "timeout" in before_async_cfg  # sanity: this key must exist to matter
    observed: dict[str, dict] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = dict(zarr.config.get("async"))

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk_throttled(xr.Dataset(), session, group="x", mode="w")

    assert observed["during"]["concurrency"] == 2
    assert observed["during"]["timeout"] == before_async_cfg["timeout"]


def test_concurrency_cap_reverts_after_the_call(tmp_path: Path) -> None:
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    before = zarr.config.get("async.concurrency")
    store._zarr_async_concurrency = 1

    with mock.patch("canvod.store.store.to_icechunk", lambda *a, **k: None):
        with store.writable_session() as session:
            store._to_icechunk_throttled(xr.Dataset(), session, group="x", mode="w")

    assert zarr.config.get("async.concurrency") == before


def test_throttle_kwarg_overrides_config_on(tmp_path: Path) -> None:
    # config says no throttling, but caller explicitly forces it on
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store._zarr_async_concurrency = 3
    observed: dict[str, int] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = zarr.config.get("async.concurrency")

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk_throttled(
                xr.Dataset(), session, throttle=True, group="x", mode="w"
            )

    assert observed["during"] == 3


def test_throttle_kwarg_overrides_config_off(tmp_path: Path) -> None:
    # config has a cap configured, but caller explicitly forces it off
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    store._zarr_async_concurrency = 2
    before = zarr.config.get("async.concurrency")
    observed: dict[str, int] = {}

    def fake_to_icechunk(dataset, session, **kwargs) -> None:
        observed["during"] = zarr.config.get("async.concurrency")

    with mock.patch("canvod.store.store.to_icechunk", fake_to_icechunk):
        with store.writable_session() as session:
            store._to_icechunk_throttled(
                xr.Dataset(), session, throttle=False, group="x", mode="w"
            )

    assert observed["during"] == before


def test_throttle_true_without_configured_cap_raises(tmp_path: Path) -> None:
    # forcing throttle=True with no cap configured is a caller error, not a
    # silent no-op or an untested None passed into zarr.config.set
    store = open_vod_store(create_test_store(tmp_path / "site" / "vod_store"))
    assert store._zarr_async_concurrency is None

    with mock.patch("canvod.store.store.to_icechunk", lambda *a, **k: None):
        with store.writable_session() as session:
            with pytest.raises(ValueError, match="zarr_async_concurrency"):
                store._to_icechunk_throttled(
                    xr.Dataset(), session, throttle=True, group="x", mode="w"
                )
