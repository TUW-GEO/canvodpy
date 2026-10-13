"""A store works with the settings it is given (#211)."""

from __future__ import annotations

import canvod.config.loader as config_loader
import icechunk
import pytest
from canvod.config import load_config
from canvod.store_metadata import collect_config_snapshot, write_metadata
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)
from canvod.store_metadata.testing import create_test_store

from canvod.store import MyIcechunkStore


@pytest.fixture
def settings():
    """The settings, changed so they differ from what a load would give."""
    config = load_config().model_copy(deep=True)
    config.processing.icechunk.chunk_strategies.gnss_store.epoch = 7
    return config


@pytest.fixture
def no_settings_loading(monkeypatch):
    """Fail any attempt to load settings from a folder."""

    def refuse(*args, **kwargs):
        msg = "settings were loaded instead of passed"
        raise AssertionError(msg)

    monkeypatch.setattr(config_loader, "_load_config_cached", refuse)


def test_the_store_uses_the_settings_it_is_given(
    tmp_path, settings, no_settings_loading
):
    store = MyIcechunkStore(create_test_store(tmp_path / "store"), config=settings)

    assert store.chunk_strategy["epoch"] == 7


def test_commits_record_the_settings_the_store_was_given(
    tmp_path, settings, no_settings_loading
):
    path = tmp_path / "store"
    icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))
    write_metadata(
        path,
        StoreMetadata(
            identity=StoreIdentity(
                id="test-gnss",
                uuid="00000000-0000-4000-8000-000000000001",
                naming_authority="org.middle-earth",
                stac_link="../../gnss-observations/x/x.json",
                title="Test",
                store_type="gnss_store",
                source_format="rinex3",
            ),
            creator=Creator(name="T", email="t@example.org", institution="U"),
            temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
            spatial=SpatialExtent(site=SiteInfo(name="Test")),
            config=collect_config_snapshot(settings),
        ),
    )
    store = MyIcechunkStore(path, config=settings)

    store.set_root_attrs({"source_format": "rinex3"})

    tip = store.repo.lookup_branch("main")
    commit = next(iter(store.repo.ancestry(snapshot_id=tip)))
    assert commit.metadata["config"]["config_hash"] == (
        collect_config_snapshot(settings).config_hash
    )
