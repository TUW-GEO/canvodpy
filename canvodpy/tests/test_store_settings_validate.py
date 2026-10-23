"""``config validate`` reports the settings a new store is missing."""

from pathlib import Path
from types import SimpleNamespace

from canvodpy.orchestrator.data_check import missing_store_settings_errors


def _validate_config() -> SimpleNamespace:
    """Settings whose site store description is missing."""
    return SimpleNamespace(
        processing=SimpleNamespace(
            storage=SimpleNamespace(
                get_gnss_store_path=lambda site: Path(f"/tmp/gnss-{site}"),
                get_vod_store_path=lambda site: Path(f"/tmp/vod-{site}"),
            ),
            metadata=SimpleNamespace(
                publisher="Test Institute",
                license="CC-BY-4.0",
                naming_authority="org.middle-earth",
                store_description=None,
            ),
        )
    )


def test_validate_reports_missing_store_settings(monkeypatch):
    """No store yet and no description: validate names the setting."""
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: False)
    config = _validate_config()
    site_cfg = SimpleNamespace(store_description=None)

    errors = missing_store_settings_errors("fangorn", site_cfg, config)

    assert any("sites.fangorn.store_description" in e for e in errors)


def test_validate_reports_nothing_for_an_existing_store(monkeypatch):
    """An existing store is never refused for these settings."""
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: True)
    config = _validate_config()
    site_cfg = SimpleNamespace(store_description=None)

    assert missing_store_settings_errors("fangorn", site_cfg, config) == []


def test_validate_reports_a_store_that_does_not_exist_even_otherwise_full(
    monkeypatch,
):
    """Only the description is missing, but neither store: one error, both paths."""
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: False)
    config = _validate_config()
    site_cfg = SimpleNamespace(store_description=None)

    errors = missing_store_settings_errors("fangorn", site_cfg, config)

    assert len(errors) == 1  # both stores are new: one error names them both
    (error,) = errors
    assert str(Path("/tmp/gnss-fangorn")) in error
    assert str(Path("/tmp/vod-fangorn")) in error
    assert error.count("sites.fangorn.store_description") == 1


def test_validate_reports_one_error_when_both_stores_are_new(monkeypatch):
    """Both stores new: one error, both paths, each missing setting named once."""
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: False)
    config = _validate_config()
    config.processing.metadata.publisher = None  # a second missing setting
    site_cfg = SimpleNamespace(store_description=None)

    (error,) = missing_store_settings_errors("fangorn", site_cfg, config)

    assert str(Path("/tmp/gnss-fangorn")) in error
    assert str(Path("/tmp/vod-fangorn")) in error
    for name in (
        "sites.fangorn.store_description",
        "processing.metadata.publisher",
    ):
        assert error.count(name) == 1
