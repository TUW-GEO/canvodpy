"""Content settings of a VOD store: D1 keys + the GNSS content-settings hash (#355).

ADR 0019. A VOD store records the settings that shape its data (its chunks,
compression, the VOD output options) and the content-settings hash of the
GNSS store it was computed from, so a run that computes VOD from a different
GNSS store stops. Through the steps every writer takes.
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
    VOD_CONTENT_KEYS,
    ContentSettingsError,
    MissingContentSettingsError,
    _get,
)

ANALYSIS = "canopy_01_vs_reference_01"
NAMES = [ANALYSIS]
GNSS_NAMES = ["canopy_01", "reference_01_canopy_01"]


def _gnss(path: Path, settings) -> dict:
    """A GNSS store with content settings."""
    return ensure_store_metadata(
        path,
        config=settings,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=GNSS_NAMES,
    )


def _vod(path: Path, settings, gnss_repository: dict) -> dict:
    """A VOD store fed by the GNSS store whose metadata is ``gnss_repository``."""
    return ensure_store_metadata(
        path,
        config=settings,
        site_name=testing.SITE_KEY,
        store_type="vod_store",
        source_format="tau_omega",
        names=NAMES,
        gnss_repository=gnss_repository,
    )


@pytest.fixture
def settings(tmp_path):
    return _settings(tmp_path)


@pytest.fixture
def gnss(settings, tmp_path) -> dict:
    return _gnss(tmp_path / "gnss", settings)


@pytest.fixture
def vod(gnss, settings, tmp_path) -> Path:
    path = tmp_path / "vod"
    _vod(path, settings, gnss)
    return path


def test_a_new_vod_store_records_its_content_settings(vod, settings, gnss):
    content = read_repository_metadata(vod)["content_settings"]

    assert content["format"] == 1
    assert content["origin"] == "created"
    # Every D1 key is recorded; no SIDs or receivers of its own.
    for key in VOD_CONTENT_KEYS:
        assert _get(content["settings"], key) is not None, key
    assert "sids" not in content["settings"]
    assert "sites" not in content["settings"]
    assert len(content["hash"]) == 64
    # The GNSS store's content-settings hash is recorded.
    assert content["gnss_content_hash"] == gnss["content_settings"]["hash"]


def test_a_run_with_other_content_settings_stops_before_writing(vod, settings, gnss):
    other = settings.model_copy(deep=True)
    other.processing.icechunk.chunk_strategies.vod_store.epoch = 8640

    with pytest.raises(ContentSettingsError) as caught:
        _vod(vod, other, gnss)

    message = str(caught.value)
    assert "chunk_strategies.vod_store" in message
    assert "this run" in message


def test_a_vod_store_fed_by_other_gnss_settings_stops(vod, settings, gnss):
    """D3: a VOD run from a GNSS store with other content settings stops."""
    other = settings.model_copy(deep=True)
    other.processing.aux_data.agency = "GFZ"
    other_gnss = _gnss(Path(vod).parent / "other_gnss", other)
    assert other_gnss["content_settings"]["hash"] != gnss["content_settings"]["hash"]

    with pytest.raises(ContentSettingsError, match="gnss_content_hash"):
        _vod(vod, other, other_gnss)


def test_a_vod_store_fed_by_a_gnss_store_without_content_settings_is_refused(
    settings, tmp_path
):
    gnss = _gnss(tmp_path / "gnss", settings)
    gnss_without = dict(gnss)
    gnss_without.pop("content_settings")

    with pytest.raises(MissingContentSettingsError, match="migrate-metadata"):
        _vod(tmp_path / "vod", settings, gnss_without)


class TestMigration:
    """``canvodpy store migrate-metadata`` for a VOD store (#355)."""

    def test_a_vod_store_without_content_settings_is_migrated(self, settings, tmp_path):
        from canvod.store_metadata.migration import migrate_content_settings
        from canvod.store_metadata.testing import give_test_metadata

        path = give_test_metadata(tmp_path / "vod", store_type="vod_store")
        # A commit records the VOD run's settings.
        session = open_repository(path).writable_session("main")
        zarr.open_group(session.store, mode="a").require_group(ANALYSIS)
        commit_with_rebase(session, "data", store_path=path, config=settings)

        gnss_repo = _gnss(tmp_path / "gnss", settings)
        ghash = gnss_repo["content_settings"]["hash"]
        migrate_content_settings(path, who="JRRT", values={"gnss_content_hash": ghash})

        content = read_repository_metadata(path)["content_settings"]
        assert content["origin"] == "migrated"
        assert content["set_by"] == "JRRT"
        assert content["gnss_content_hash"] == ghash
        # The run whose GNSS store hash it records may write again.
        ensure_store_metadata(
            path,
            config=settings,
            site_name=testing.SITE_KEY,
            store_type="vod_store",
            source_format="tau_omega",
            names=NAMES,
            gnss_repository=gnss_repo,
        )

    def test_a_missing_gnss_hash_is_listed(self, settings, tmp_path):
        from canvod.store_metadata.migration import migrate_content_settings
        from canvod.store_metadata.testing import give_test_metadata

        path = give_test_metadata(tmp_path / "vod", store_type="vod_store")
        session = open_repository(path).writable_session("main")
        zarr.open_group(session.store, mode="a").require_group(ANALYSIS)
        commit_with_rebase(session, "data", store_path=path, config=settings)

        before = open_repository(path).lookup_branch("main")
        with pytest.raises(ValueError, match="not guessed") as caught:
            migrate_content_settings(path, who="JRRT")

        assert "gnss_content_hash" in str(caught.value)
        assert open_repository(path).lookup_branch("main") == before


def test_the_metadata_view_shows_the_vod_content_settings(vod):
    from canvod.store_metadata import format_metadata, read_metadata

    text = format_metadata(read_metadata(vod), section="content")

    assert "Content Settings" in text
    assert "vod_store" in text
    assert "Set by" in text
