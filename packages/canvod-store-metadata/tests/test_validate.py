"""Test metadata validation against standards."""

from canvod.store_metadata.schema import (
    Creator,
    Publisher,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)
from canvod.store_metadata.validate import (
    validate_acdd,
    validate_all,
    validate_datacite,
    validate_fair,
    validate_stac,
)


def _make_complete_metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="Rosalia/gnss_store",
            title="Rosalia GNSS Store",
            description="GNSS observations from Rosalia research site",
            store_type="gnss_store",
            source_format="rinex3",
            keywords=["GNSS", "VOD"],
        ),
        creator=Creator(
            name="Test User",
            email="test@example.com",
            institution="TU Wien",
        ),
        publisher=Publisher(
            name="TU Wien",
            license="CC-BY-4.0",
            license_uri="https://creativecommons.org/licenses/by/4.0/",
        ),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            collected_start="2025-01-01T00:00:00Z",
            collected_end="2025-12-31T23:59:55Z",
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="Rosalia", description="Forest site", country="AT"),
            geospatial_lat=47.7,
            geospatial_lon=16.3,
            geospatial_alt_m=400.0,
            bbox=[16.3, 47.7, 16.3, 47.7],
            extent_temporal_interval=[["2025-01-01T00:00:00Z", "2025-12-31T23:59:55Z"]],
        ),
    )


class TestValidation:
    def test_complete_metadata_passes_datacite(self):
        meta = _make_complete_metadata()
        issues = validate_datacite(meta)
        assert issues == []

    def test_complete_metadata_passes_acdd(self):
        meta = _make_complete_metadata()
        issues = validate_acdd(meta)
        assert issues == []

    def test_complete_metadata_passes_stac(self):
        meta = _make_complete_metadata()
        issues = validate_stac(meta)
        assert issues == []

    def test_minimal_metadata_has_datacite_issues(self):
        meta = StoreMetadata(
            identity=StoreIdentity(
                id="test/store",
                title="Test",
                store_type="gnss_store",
                source_format="rinex3",
            ),
            creator=Creator(
                name="Test",
                email="test@example.com",
                institution="TestU",
            ),
            temporal=TemporalExtent(
                created="2026-01-01T00:00:00Z",
                updated="2026-01-01T00:00:00Z",
            ),
            spatial=SpatialExtent(site=SiteInfo(name="Test")),
        )
        issues = validate_datacite(meta)
        assert any("publisher" in i for i in issues)

    def test_validate_all_returns_all_standards(self):
        meta = _make_complete_metadata()
        result = validate_all(meta)
        assert "fair" in result
        assert "datacite" in result
        assert "acdd" in result
        assert "stac" in result

    def test_fair_complete_metadata_reports_expected_issues(self):
        meta = _make_complete_metadata()
        issues = validate_fair(meta)
        # Complete metadata should still flag missing DOI, access URL, etc.
        tags = [i.split("]")[0] + "]" for i in issues]
        assert "[F1]" in tags  # no persistent_identifier
        assert "[A1]" in tags  # no access_url
        assert "[R1.2]" in tags  # no uv_lock_hash

    def test_fair_fully_satisfied(self):
        from canvod.store_metadata.schema import (
            Environment,
            ProcessingProvenance,
            References,
        )

        meta = _make_complete_metadata()
        meta.identity.persistent_identifier = "10.5281/zenodo.1234567"
        meta.references = References(
            access_url="https://example.com/store",
            related_stores=["Rosalia/sbf_store"],
            publications=[],
        )
        meta.processing = ProcessingProvenance(
            software={"canvodpy": "0.1.0"},
        )
        meta.environment = Environment(uv_lock_hash="a" * 64)
        issues = validate_fair(meta)
        assert issues == []
