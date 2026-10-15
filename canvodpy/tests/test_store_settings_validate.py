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
                naming_authority="at.ac.tuwien",
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
    """Only the description is missing, but no store: one error, the site one."""
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: False)
    config = _validate_config()
    site_cfg = SimpleNamespace(store_description=None)

    errors = missing_store_settings_errors("fangorn", site_cfg, config)

    assert len(errors) == 2  # GNSS store and VOD store, neither exists
    for error in errors:
        assert "sites.fangorn.store_description" in error
