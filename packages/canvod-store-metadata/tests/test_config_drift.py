"""Each commit records the settings it was made with (ADR 0014).

Settings that change between runs show as different config hashes in the
commit metadata of successive snapshots; nothing is merged into a history.
"""

from __future__ import annotations

import icechunk
import zarr

from canvod.store_metadata import (
    collect_config_snapshot,
    commit_with_rebase,
    read_metadata,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)


def _create_store(path):
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")
    return path


def _make_metadata(config_snapshot) -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="test-gnss",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../gnss-observations/org.middle-earth.test-gnss/org.middle-earth.test-gnss.json",
            title="Test Store",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(name="Test", email="test@example.com", institution="TestU"),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z"
        ),
        spatial=SpatialExtent(site=SiteInfo(name="TestSite")),
        config=config_snapshot,
    )


def _commit_with(store_path, config) -> str:
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store_path)))
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="a").require_group("canopy_01")
    return commit_with_rebase(session, "ingest", store_path=store_path, config=config)


def _config_hash_of(store_path, snapshot_id) -> str:
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store_path)))
    snapshot = next(iter(repo.ancestry(snapshot_id=snapshot_id)))
    return snapshot.metadata["config"]["config_hash"]


class TestSettingsPerCommit:
    def test_unchanged_settings_give_the_same_hash(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        config = {"processing": {"agency": "COD"}}
        write_metadata(store_path, _make_metadata(collect_config_snapshot(config)))

        _commit_with(store_path, config)

        meta = read_metadata(store_path)
        assert meta.config.config_hash == collect_config_snapshot(config).config_hash

    def test_changed_settings_show_in_the_next_commit_only(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        old_config = {"processing": {"agency": "COD"}}
        write_metadata(store_path, _make_metadata(collect_config_snapshot(old_config)))
        first = _commit_with(store_path, old_config)

        new_config = {"processing": {"agency": "GFZ"}}
        second = _commit_with(store_path, new_config)

        assert _config_hash_of(store_path, first) == (
            collect_config_snapshot(old_config).config_hash
        )
        assert _config_hash_of(store_path, second) == (
            collect_config_snapshot(new_config).config_hash
        )
        assert read_metadata(store_path).config.processing == {"agency": "GFZ"}
