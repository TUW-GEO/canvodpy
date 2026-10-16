"""Content settings: set by whoever creates a store, matched by every run (#349).

ADR 0019. Through the steps every writer takes: ``ensure_store_metadata``
when a run starts and ``commit_with_rebase`` at the tip.
"""

from pathlib import Path

import pytest
import zarr
from canvod.utils import testing
from test_writers import _settings

from canvod.store_metadata import (
    commit_with_rebase,
    ensure_store_metadata,
    open_repository,
    read_repository_metadata,
)
from canvod.store_metadata.content import (
    ContentSettingsError,
    MissingContentSettingsError,
)
from canvod.store_metadata.testing import give_test_metadata

NAMES = ["canopy_01", "reference_01_canopy_01"]


def _start(path: Path, config) -> dict:
    """The step every run takes before it reads a file."""
    return ensure_store_metadata(
        path,
        config=config,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=NAMES,
    )


def _commit(path: Path, config) -> str:
    """A commit of data, as a run makes it."""
    session = open_repository(path).writable_session("main")
    zarr.open_group(session.store, mode="a").require_group("canopy_01")
    return commit_with_rebase(session, "data", store_path=path, config=config)


@pytest.fixture
def settings(tmp_path):
    return _settings(tmp_path)


@pytest.fixture
def store(tmp_path, settings) -> Path:
    path = tmp_path / "gnss"
    _start(path, settings)
    return path


def test_a_new_store_records_its_content_settings(store, settings):
    content = read_repository_metadata(store)["content_settings"]

    assert content["format"] == 1
    assert content["origin"] == "created"
    params = content["settings"]["processing"]["params"]
    assert params["rinex_v3_parser"] == settings.processing.params.rinex_v3_parser
    assert content["settings"]["processing"]["aux_data"]["product_type"] == "final"
    receivers = content["settings"]["sites"][testing.SITE_KEY]["receivers"]
    assert receivers["reference_01"] == {
        "type": "reference",
        "reader_format": "auto",
        "paired_canopies": ["canopy_01"],
    }
    assert len(content["hash"]) == 64
    # Free settings are not content settings.
    assert "logging" not in content["settings"]["processing"]
    assert "resource_mode" not in params


def test_a_run_with_the_same_settings_writes(store, settings):
    _start(store, settings)
    _commit(store, settings)


def test_free_settings_may_differ(store, settings):
    other = settings.model_copy(deep=True)
    other.processing.params.days_per_batch = 7
    other.processing.params.max_memory_gb = 3.0
    other.processing.storage.gnss_store_strategy = "overwrite"
    other.processing.icechunk.max_concurrent_requests = 3
    other.processing.aux_data.ftp_timeout_s = 5

    _start(store, other)
    _commit(store, other)


def test_a_run_with_other_settings_stops_before_reading(store, settings):
    other = settings.model_copy(deep=True)
    other.processing.aux_data.product_type = "rapid"
    other.processing.params.store_delta_snr = True

    with pytest.raises(ContentSettingsError) as caught:
        _start(store, other)

    message = str(caught.value)
    assert 'processing.aux_data.product_type: store "final", this run "rapid"' in (
        message
    )
    assert "processing.params.store_delta_snr: store false, this run true" in message
    assert "when the store was created" in message
    assert "canvodpy config init --from-store" in message


def test_a_difference_at_the_tip_stops_the_commit(store, settings):
    """The run started before the other run created the store, or wrote first."""
    other = settings.model_copy(deep=True)
    other.processing.icechunk.compression_level = 9
    before = open_repository(store).lookup_branch("main")

    with pytest.raises(ContentSettingsError, match="compression_level"):
        _commit(store, other)

    assert open_repository(store).lookup_branch("main") == before


def test_a_receiver_setting_counts(store, settings):
    other = settings.model_copy(deep=True)
    other.sites.sites[testing.SITE_KEY].receivers["canopy_01"].reader_format = "sbf"

    with pytest.raises(
        ContentSettingsError, match=r"receivers\.canopy_01\.reader_format"
    ):
        _start(store, other)


def test_a_changed_sid_preset_counts(store, settings):
    other = settings.model_copy(deep=True)
    other.sids.mode = "custom"
    other.sids.custom_sids = ["G01|L1|C"]

    with pytest.raises(ContentSettingsError, match=r"sids \(resolved list\)"):
        _start(store, other)


def test_a_store_without_content_settings_is_refused(tmp_path, settings):
    path = give_test_metadata(tmp_path / "old", receivers={"canopy_01": "canopy"})

    with pytest.raises(MissingContentSettingsError, match="migrate-metadata"):
        ensure_store_metadata(
            path,
            config=settings,
            site_name=testing.SITE_KEY,
            store_type="gnss_store",
            source_format="rinex3",
            names=["canopy_01"],
        )


def test_content_settings_are_not_amendable(store):
    from canvod.store_metadata import amend_metadata

    with pytest.raises(ValueError, match="fixed field"):
        amend_metadata(
            store,
            {"content_settings.settings.sids.mode": "all"},
            reason="test",
            who="JRRT",
        )


class TestMigration:
    """``canvodpy store migrate-metadata`` for a store created before (#349)."""

    @pytest.fixture
    def old_store(self, tmp_path, settings) -> Path:
        """A store with repository metadata, data, but no content settings."""
        path = give_test_metadata(tmp_path / "old")
        _commit(path, settings)
        return path

    def test_missing_settings_are_listed_not_guessed(self, old_store):
        from canvod.store_metadata.migration import migrate_content_settings

        before = open_repository(old_store).lookup_branch("main")
        with pytest.raises(ValueError, match="not guessed") as caught:
            migrate_content_settings(old_store, who="JRRT")

        message = str(caught.value)
        key = f"sites.{testing.SITE_KEY}.receivers.reference_01.paired_canopies"
        assert f"  - {key}" in message
        assert f"--set {key}=VALUE" in message
        assert "canopy_01.paired_canopies" not in message
        assert open_repository(old_store).lookup_branch("main") == before
        assert not read_repository_metadata(old_store).get("content_settings")

    def test_the_first_commit_gives_the_content_settings(self, old_store, settings):
        from canvod.store_metadata.migration import migrate_content_settings

        key = f"sites.{testing.SITE_KEY}.receivers.reference_01.paired_canopies"
        migrate_content_settings(old_store, who="JRRT", values={key: ["canopy_01"]})

        content = read_repository_metadata(old_store)["content_settings"]
        assert content["origin"] == "migrated"
        assert content["set_by"] == "JRRT"
        assert content["values_given"] == [key]
        # The run whose settings wrote the data may write again.
        _start(old_store, settings)
        _commit(old_store, settings)

    def test_a_later_run_with_other_settings_is_refused(self, old_store, settings):
        from canvod.store_metadata.migration import migrate_content_settings

        key = f"sites.{testing.SITE_KEY}.receivers.reference_01.paired_canopies"
        migrate_content_settings(old_store, who="JRRT", values={key: ["canopy_01"]})
        other = settings.model_copy(deep=True)
        other.processing.aux_data.agency = "GFZ"

        with pytest.raises(ContentSettingsError, match="by migration on"):
            _start(old_store, other)

    def test_a_store_with_content_settings_is_not_migrated_again(self, store):
        from canvod.store_metadata.migration import migrate_content_settings

        with pytest.raises(ValueError, match="already has content settings"):
            migrate_content_settings(store, who="JRRT")


class TestAddingAReceiver:
    """A receiver added by amendment brings its content settings."""

    CANOPY_02 = {"type": "canopy", "reader_format": "auto", "paired_canopies": None}

    def _amend(self, store: Path, receiver_content=None) -> str:
        from canvod.store_metadata import amend_metadata

        return amend_metadata(
            store,
            {"instruments.receivers.canopy_02": {"type": "canopy", "directory": "c2"}},
            reason="second canopy receiver",
            who="JRRT",
            receiver_content=receiver_content,
        )

    def test_they_are_added_with_the_receiver(self, store, settings):
        self._amend(store, {"canopy_02": self.CANOPY_02})

        content = read_repository_metadata(store)["content_settings"]
        receivers = content["settings"]["sites"][testing.SITE_KEY]["receivers"]
        assert receivers["canopy_02"] == self.CANOPY_02
        # The next commit accepts the root copy, and a run whose settings
        # list the receiver with other settings is refused.
        _commit(store, settings)
        other = settings.model_copy(deep=True)
        from canvod.config.models import ReceiverConfig

        other.sites.sites[testing.SITE_KEY].receivers["canopy_02"] = ReceiverConfig(
            type="canopy", directory="c2", reader_format="sbf"
        )
        with pytest.raises(ContentSettingsError, match="canopy_02.reader_format"):
            _start(store, other)

    def test_a_receiver_without_them_is_refused(self, store):
        before = open_repository(store).lookup_branch("main")

        with pytest.raises(ValueError, match="adding receiver 'canopy_02' needs"):
            self._amend(store)

        assert open_repository(store).lookup_branch("main") == before


def test_the_metadata_view_shows_them(store):
    from canvod.store_metadata import format_metadata, read_metadata

    text = format_metadata(read_metadata(store), section="content")

    assert "Content Settings" in text
    assert "product_type: final" in text
    assert "Set by" in text
