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
    ACDD_RECOMMENDED,
    COVERAGE_CONTENT_TYPES,
    root_attributes,
    validate_acdd,
    validate_all,
    validate_datacite,
    validate_fair,
    validate_stac,
    validate_zarr_conventions,
)


def _make_complete_metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="rosalia-gnss",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="at.ac.tuwien",
            stac_link=(
                "../../gnss-observations/at.ac.tuwien.rosalia-gnss/"
                "at.ac.tuwien.rosalia-gnss.json"
            ),
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

    def test_complete_metadata_has_no_acdd_failures(self):
        meta = _make_complete_metadata()
        assert validate_acdd(meta, recommended=False) == []

    def test_complete_metadata_passes_the_zarr_conventions(self):
        assert validate_zarr_conventions(_make_complete_metadata()) == []

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
        assert set(result) == {"zarr_conventions", "acdd", "datacite", "stac", "fair"}

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


class TestPassRule:
    """A store in the current form passes; recommendations are only listed."""

    def test_complete_metadata_has_no_failures(self):
        result = validate_all(_make_complete_metadata(), recommended=False)
        assert result == {
            "zarr_conventions": [],
            "acdd": [],
            "datacite": [],
            "stac": [],
            "fair": [],
        }

    def test_a_missing_summary_fails_acdd_and_names_its_field(self):
        meta = _make_complete_metadata()
        meta.identity.description = None

        issues = validate_acdd(meta, recommended=False)

        assert issues == [
            "ACDD 1.3 highly recommended attribute `summary` is missing "
            "(from identity.description)"
        ]

    def test_recommendations_are_listed_and_marked(self):
        issues = validate_acdd(_make_complete_metadata())

        assert "[recommended] ACDD 1.3 recommended attribute `history` is missing" in (
            issues
        )
        assert all(i.startswith("[recommended]") for i in issues)

    def test_fair_advice_only_with_recommendations(self):
        meta = _make_complete_metadata()
        assert validate_all(meta)["fair"]
        assert validate_all(meta, recommended=False)["fair"] == []

    def test_metadata_from_before_the_migration_is_reported(self):
        meta = _make_complete_metadata()
        meta.identity.uuid = None

        result = validate_all(meta, recommended=False)

        assert "migrate-metadata" in result["acdd"][0]
        assert "migrate-metadata" in result["zarr_conventions"][0]

    def test_the_root_attributes_are_what_a_commit_writes(self):
        attrs = root_attributes(_make_complete_metadata())
        assert attrs["Conventions"] == "CF-1.11, ACDD-1.3"
        assert attrs["summary"] == "GNSS observations from Rosalia research site"
        assert attrs["license"]["spdx"] == "CC-BY-4.0"

    def test_the_acdd_lists_are_complete(self):
        # ACDD 1.3 lists 32 recommended global attributes and eight values
        # of coverage_content_type.
        assert len(ACDD_RECOMMENDED) == len(set(ACDD_RECOMMENDED)) == 32
        assert len(COVERAGE_CONTENT_TYPES) == 8
