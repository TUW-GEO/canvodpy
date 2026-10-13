"""Metadata fields follow the rules of their standards (#251)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import icechunk
import pytest
import zarr
from canvod.utils import testing
from pydantic import ValidationError

from canvod.store_metadata import (
    amend_metadata,
    open_repository,
    read_metadata,
    validate_all,
    write_metadata,
)
from canvod.store_metadata.io import _set_field
from canvod.store_metadata.schema import MetadataRuleWarning, StoreMetadata
from canvod.store_metadata.snapshot import SNAPSHOT_SUMMARY_ATTR
from canvod.store_metadata.testing import (
    give_test_metadata,
    made_up_metadata,
    write_unchecked,
)

_ORCID = testing.PERSON_ORCID
_ROR = testing.INSTITUTION_ROR

#: Field, a value breaking its rule, words of the rule the error names.
_BREAKS = [
    ("creator.orcid", "0000-0000-0000-1232", "ORCID"),
    ("creator.orcid", "Treebeard", "ORCID"),
    ("creator.institution_ror", "TU Wien", "ROR"),
    ("identity.persistent_identifier", "10.abc/fangorn", "DOI"),
    ("identity.persistent_identifier", "https://doi.org/fangorn", "DOI"),
    ("creator.type", "Ent", "Personal"),
    ("publisher.type", "Kingdom", "Institutional"),
    ("identity.store_type", "palantir_store", "gnss_store"),
    ("spatial.geospatial_lat", 91.0, "-90 to 90"),
    ("spatial.geospatial_lon", -181.0, "-180 to 180"),
    ("spatial.geospatial_lat_max", 90.5, "-90 to 90"),
    ("spatial.bbox", [16.0, 48.0, 16.1], "W, S, E, N"),
    ("spatial.bbox", [16.1, 48.0, 16.0, 48.1], "W <= E"),
    ("spatial.bbox", [16.0, 48.1, 16.1, 48.0], "S <= N"),
    ("temporal.time_coverage_duration", "86400 s", "ISO 8601"),
    ("temporal.time_coverage_resolution", "PT2.592e+06S", "ISO 8601"),
    ("publisher.license_uri", "the inklings' licence", "URL"),
    ("publisher.url", "inklings.org", "URL"),
    ("creator.website", "ftp://fangorn.org", "URL"),
]

#: Field and a value following its rule.
_FOLLOWS = [
    ("creator.orcid", _ORCID),
    ("creator.orcid", testing.OTHER_ORCID),
    ("creator.orcid", f"https://orcid.org/{_ORCID}"),
    ("creator.institution_ror", _ROR),
    ("creator.institution_ror", f"https://ror.org/{_ROR}"),
    ("identity.persistent_identifier", "10.5281/zenodo.1234567"),
    ("identity.persistent_identifier", "https://doi.org/10.5281/zenodo.1234567"),
    ("identity.persistent_identifier", "hdl:20.500.12345/fangorn"),
    ("creator.type", "Organizational"),
    ("publisher.type", "institution"),
    ("identity.store_type", "vod_store"),
    ("spatial.geospatial_lat", -90.0),
    ("spatial.geospatial_lon", 180.0),
    ("spatial.bbox", [16.0, 48.0, 16.0, 48.0]),
    ("temporal.time_coverage_duration", "P30DT1H"),
    ("temporal.time_coverage_resolution", "PT0.5S"),
    ("publisher.url", "https://inklings.org"),
    ("creator.website", "http://fangorn.org/ents"),
]


def _with(field: str, value: Any) -> dict[str, Any]:
    """The made-up metadata as data, with ``field`` set to ``value``."""
    data = made_up_metadata().model_dump(mode="json")
    _set_field(data, field, value)
    return data


class TestNewMetadata:
    @pytest.mark.parametrize(("field", "value", "rule"), _BREAKS)
    def test_a_value_breaking_the_rule_fails_naming_field_and_rule(
        self, field, value, rule
    ):
        with pytest.raises(ValidationError) as error:
            StoreMetadata.model_validate(_with(field, value))

        message = str(error.value)
        assert field.rsplit(".", 1)[-1] in message
        assert repr(value) in message
        assert rule in message

    @pytest.mark.parametrize(("field", "value"), _FOLLOWS)
    def test_a_value_following_the_rule_is_accepted(self, field, value):
        StoreMetadata.model_validate(_with(field, value))

    def test_the_test_helpers_metadata_follows_every_rule(self):
        for store_type in ("gnss_store", "vod_store"):
            StoreMetadata.model_validate(
                made_up_metadata(store_type).model_dump(mode="json")
            )

    def test_a_store_is_not_created_with_a_bad_orcid(self, tmp_path):
        meta = made_up_metadata()
        meta.creator.orcid = "Treebeard"  # assignment is not validated
        path = tmp_path / "store"
        open_repository(path, create=True)

        with pytest.raises(ValueError, match=r"creator\.orcid.*ORCID"):
            write_metadata(path, meta)

        assert not open_repository(path).get_metadata()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return give_test_metadata(tmp_path / "store")


@pytest.fixture
def store_with_bad_orcid(store: Path) -> Path:
    """A store whose ORCID breaks the rule, as an older canvodpy could write."""
    write_unchecked(store, {"creator.orcid": "Treebeard"})
    return store


#: Repository fields among ``_BREAKS``, one per rule; a test can write
#: them into a store without the model.
_STORED_BREAKS = [
    ("creator.orcid", "Treebeard"),
    ("creator.institution_ror", "TU Wien"),
    ("identity.persistent_identifier", "10.abc/fangorn"),
    ("creator.type", "Ent"),
    ("publisher.url", "inklings.org"),
    ("spatial.geospatial_lat", 91.0),
]


def _break_computed(store: Path, field: str, value: Any) -> None:
    """Write ``value`` into the computed part of the metadata, unchecked."""
    repo = icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(store))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="r+")
    summary = dict(root.attrs[SNAPSHOT_SUMMARY_ATTR])
    _set_field(summary, field, value)
    root.attrs[SNAPSHOT_SUMMARY_ATTR] = summary
    session.commit("a computed value an older canvodpy wrote")


class TestExistingStore:
    @pytest.mark.parametrize(("field", "value"), _STORED_BREAKS)
    def test_a_store_breaking_any_rule_opens_and_amend_fixes_it(
        self, store, field, value, recwarn
    ):
        good = made_up_metadata().model_dump(mode="json")
        for part in field.split("."):
            good = good[part]
        write_unchecked(store, {field: value})

        with pytest.warns(MetadataRuleWarning, match=field.replace(".", r"\.")):
            meta = read_metadata(store)
        assert field in " ".join(validate_all(meta, recommended=False)["rules"])

        amend_metadata(store, {field: good}, reason="the right value", who="NFB")
        recwarn.clear()
        read_metadata(store)
        assert not [w for w in recwarn if w.category is MetadataRuleWarning]

    def test_a_bad_computed_value_warns_that_the_next_commit_fixes_it(self, store):
        _break_computed(store, "temporal.time_coverage_duration", "PT2.592e+06S")

        with pytest.warns(MetadataRuleWarning, match="computes it again"):
            meta = read_metadata(store)

        assert meta.temporal.time_coverage_duration == "PT2.592e+06S"

    def test_a_store_breaking_a_rule_still_opens_with_a_warning(
        self, store_with_bad_orcid
    ):
        with pytest.warns(MetadataRuleWarning, match=r"creator\.orcid"):
            meta = read_metadata(store_with_bad_orcid)

        assert meta.creator.orcid == "Treebeard"

    def test_validate_all_reports_the_broken_rule(self, store_with_bad_orcid):
        with pytest.warns(MetadataRuleWarning):
            meta = read_metadata(store_with_bad_orcid)

        failures = validate_all(meta, recommended=False)

        assert any("creator.orcid" in issue for issue in failures["rules"])

    def test_amend_fixes_the_value(self, store_with_bad_orcid, recwarn):
        amend_metadata(
            store_with_bad_orcid,
            {"creator.orcid": _ORCID},
            reason="the real ORCID",
            who="NFB",
        )
        recwarn.clear()

        meta = read_metadata(store_with_bad_orcid)

        assert meta.creator.orcid == _ORCID
        assert not [w for w in recwarn if w.category is MetadataRuleWarning]

    def test_amending_to_a_bad_value_fails_and_changes_nothing(self, store):
        with pytest.raises(ValueError, match=r"creator\.institution_ror.*ROR"):
            amend_metadata(
                store, {"creator.institution_ror": "TU Wien"}, reason="r", who="NFB"
            )

        assert read_metadata(store).creator.institution_ror is None
