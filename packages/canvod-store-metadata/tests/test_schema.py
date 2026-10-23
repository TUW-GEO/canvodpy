"""Test schema model serialization and round-trip."""

import pytest

from canvod.store_metadata.schema import (
    Creator,
    Environment,
    Publisher,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)


def _make_minimal_metadata() -> StoreMetadata:
    """Create a minimal valid StoreMetadata."""
    return StoreMetadata(
        identity=StoreIdentity(
            id="test/gnss_store",
            title="Test GNSS Store",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(
            name="Test User",
            email="test@example.com",
            institution="Test University",
        ),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="TestSite"),
        ),
    )


class TestStoreMetadata:
    def test_minimal_creation(self):
        meta = _make_minimal_metadata()
        assert meta.identity.id == "test/gnss_store"
        assert meta.metadata_version == "1.0.0"

    def test_round_trip_via_root_attrs(self):
        meta = _make_minimal_metadata()
        attrs = meta.to_root_attrs()
        with pytest.warns(FutureWarning, match="read_metadata"):
            restored = StoreMetadata.from_root_attrs(attrs)
        assert restored.written_before_migration
        assert restored.model_copy(update={"written_before_migration": False}) == meta

    def test_to_root_attrs_structure(self):
        meta = _make_minimal_metadata()
        attrs = meta.to_root_attrs()
        assert "canvod_metadata" in attrs
        data = attrs["canvod_metadata"]
        assert data["identity"]["id"] == "test/gnss_store"
        assert data["creator"]["name"] == "Test User"

    def test_defaults_applied(self):
        meta = _make_minimal_metadata()
        assert meta.publisher == Publisher()
        assert meta.environment == Environment()
        assert meta.summaries.history == []
        assert meta.instruments.platform == "ground-based GNSS"

    def test_json_serialization(self):
        meta = _make_minimal_metadata()
        json_str = meta.model_dump_json()
        restored = StoreMetadata.model_validate_json(json_str)
        assert restored == meta

    def test_from_root_attrs_missing_key(self):
        with pytest.raises(KeyError):
            StoreMetadata.from_root_attrs({})
