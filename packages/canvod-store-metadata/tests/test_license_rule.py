"""The license rule of the publisher (SPDX, #245)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from canvod.store_metadata import (
    amend_metadata,
    open_repository,
    read_metadata,
    validate_all,
    write_metadata,
)
from canvod.store_metadata.schema import MetadataRuleWarning, Publisher
from canvod.store_metadata.testing import (
    give_test_metadata,
    made_up_metadata,
    write_unchecked,
)

_TEXT = "https://the.inklings.org/data-licence"


class TestPublisher:
    @pytest.mark.parametrize(
        "publisher",
        [
            {"license": "CC-BY-4.0"},
            {"license": "other", "license_uri": _TEXT},
            {},
        ],
        ids=["spdx", "other-with-text", "none"],
    )
    def test_an_spdx_identifier_or_other_with_its_text_is_accepted(self, publisher):
        Publisher(**publisher)

    def test_a_license_outside_spdx_fails_naming_the_field_and_the_list(self):
        with pytest.raises(ValidationError, match=r"license.*spdx\.org/licenses"):
            Publisher(license="Apache 2")

    def test_a_wrongly_cased_identifier_fails_naming_the_right_one(self):
        with pytest.raises(ValidationError, match="'CC-BY-4.0'"):
            Publisher(license="cc-by-4.0")

    def test_other_without_the_license_text_fails(self):
        with pytest.raises(ValidationError, match="license_uri"):
            Publisher(license="other")


def test_a_store_is_not_created_with_a_license_breaking_the_rule(tmp_path):
    meta = made_up_metadata()
    meta.publisher.license = "Apache 2"  # assignment is not validated
    path = tmp_path / "store"
    open_repository(path, create=True)

    with pytest.raises(ValueError, match=r"publisher\.license.*SPDX"):
        write_metadata(path, meta)

    assert not open_repository(path).get_metadata()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return give_test_metadata(tmp_path / "store")


@pytest.fixture
def store_with_bad_license(store: Path) -> Path:
    """A store whose license breaks the rule, as an older canvodpy could write."""
    write_unchecked(store, {"publisher.license": "Apache 2"})
    return store


class TestExistingStore:
    def test_a_store_breaking_the_rule_still_opens_with_a_warning(
        self, store_with_bad_license
    ):
        with pytest.warns(MetadataRuleWarning, match=r"publisher\.license"):
            meta = read_metadata(store_with_bad_license)

        assert meta.publisher.license == "Apache 2"

    def test_validate_all_reports_the_broken_rule(self, store_with_bad_license):
        with pytest.warns(MetadataRuleWarning):
            meta = read_metadata(store_with_bad_license)

        failures = validate_all(meta, recommended=False)

        assert any("publisher.license" in issue for issue in failures["rules"])

    def test_a_valid_store_breaks_no_rule(self, store):
        assert validate_all(read_metadata(store), recommended=False)["rules"] == []


class TestAmend:
    def test_amending_the_license_to_a_bad_value_fails_and_changes_nothing(self, store):
        with pytest.raises(ValueError, match=r"publisher\.license.*spdx"):
            amend_metadata(
                store, {"publisher.license": "Apache 2"}, reason="r", who="NFB"
            )

        assert read_metadata(store).publisher.license == "CC-BY-4.0"

    def test_amending_another_field_keeps_the_bad_license_with_a_warning(
        self, store_with_bad_license
    ):
        with pytest.warns(MetadataRuleWarning, match=r"publisher\.license"):
            amend_metadata(
                store_with_bad_license,
                {"identity.title": "Fangorn"},
                reason="new title",
                who="NFB",
            )

        with pytest.warns(MetadataRuleWarning):
            meta = read_metadata(store_with_bad_license)
        assert meta.identity.title == "Fangorn"

    def test_amend_fixes_the_license(self, store_with_bad_license, recwarn):
        amend_metadata(
            store_with_bad_license,
            {"publisher.license": "CC-BY-4.0"},
            reason="SPDX identifier",
            who="NFB",
        )
        recwarn.clear()

        meta = read_metadata(store_with_bad_license)

        assert meta.publisher.license == "CC-BY-4.0"
        assert not [w for w in recwarn if w.category is MetadataRuleWarning]
