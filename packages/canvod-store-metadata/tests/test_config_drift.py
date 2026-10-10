"""Tests for config-drift detection on repeat ingests.

Exercises the same read -> re-snapshot -> compare -> merge-history pattern
used by processor.py's STEP 5b, at the canvod-store-metadata level (a full
orchestrator-level test would need a real pipeline run).
"""

from __future__ import annotations

from datetime import UTC, datetime

import icechunk
import zarr

from canvod.store_metadata import (
    collect_config_snapshot,
    read_metadata,
    update_metadata,
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
            id="test/gnss_store",
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


def _simulate_repeat_ingest(store_path, branch, config):
    """Mirror processor.py's STEP 5b else-branch exactly."""
    now = datetime.now(UTC).isoformat()
    existing_meta = read_metadata(store_path, branch=branch)
    new_snapshot = collect_config_snapshot(config)

    history_entries = [f"{now}: Ingest canopy_01 2025001: written=1"]
    updates: dict[str, object] = {"temporal.updated": now}

    drifted = new_snapshot.config_hash != existing_meta.config.config_hash
    if drifted:
        old_hash = (existing_meta.config.config_hash or "unknown")[:12]
        new_hash = (new_snapshot.config_hash or "unknown")[:12]
        history_entries.append(f"{now}: Config changed ({old_hash} -> {new_hash})")
        updates["config"] = new_snapshot.model_dump(mode="json")

    updates["summaries.history"] = [
        *existing_meta.summaries.history,
        *history_entries,
    ]

    update_metadata(store_path, updates, branch=branch)
    return drifted


class TestConfigDrift:
    def test_unchanged_config_does_not_touch_config_section(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        config = {"processing": {"agency": "COD"}}
        initial_snapshot = collect_config_snapshot(config)
        write_metadata(store_path, _make_metadata(initial_snapshot), branch="main")

        drifted = _simulate_repeat_ingest(store_path, "main", config)

        assert drifted is False
        meta = read_metadata(store_path, branch="main")
        assert meta.config.config_hash == initial_snapshot.config_hash
        assert len(meta.summaries.history) == 1
        assert "Ingest canopy_01" in meta.summaries.history[0]

    def test_changed_config_updates_snapshot_and_records_drift(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        old_config = {"processing": {"agency": "COD"}}
        write_metadata(
            store_path,
            _make_metadata(collect_config_snapshot(old_config)),
            branch="main",
        )

        new_config = {"processing": {"agency": "GFZ"}}
        drifted = _simulate_repeat_ingest(store_path, "main", new_config)

        assert drifted is True
        meta = read_metadata(store_path, branch="main")
        assert (
            meta.config.config_hash == collect_config_snapshot(new_config).config_hash
        )
        assert meta.config.processing == {"agency": "GFZ"}
        assert len(meta.summaries.history) == 2
        assert "Config changed" in meta.summaries.history[1]

    def test_history_accumulates_across_multiple_ingests_not_replaced(self, tmp_path):
        """Regression test: update_metadata() replaces list fields wholesale —
        the caller (processor.py, mirrored here) must merge history itself."""
        store_path = _create_store(tmp_path / "store")
        config = {"processing": {"agency": "COD"}}
        write_metadata(
            store_path, _make_metadata(collect_config_snapshot(config)), branch="main"
        )

        _simulate_repeat_ingest(store_path, "main", config)
        _simulate_repeat_ingest(store_path, "main", config)
        _simulate_repeat_ingest(store_path, "main", config)

        meta = read_metadata(store_path, branch="main")
        assert len(meta.summaries.history) == 3
