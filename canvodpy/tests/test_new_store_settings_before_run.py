"""A first run refuses before processing when a new store's settings are missing."""

import re
from types import SimpleNamespace

import pytest


def _config(store_description: str | None = None) -> SimpleNamespace:
    """Settings with the site's store description left out by default."""
    return SimpleNamespace(
        processing=SimpleNamespace(
            metadata=SimpleNamespace(
                publisher="Test Institute",
                license="CC-BY-4.0",
                naming_authority="at.ac.tuwien",
                store_description=None,
            )
        ),
        sites=SimpleNamespace(
            sites={"fangorn": SimpleNamespace(store_description=store_description)}
        ),
    )


# ---------------------------------------------------------------------------
# The orchestrator (Site.pipeline(), process_day) refuses a first GNSS store
# ---------------------------------------------------------------------------


def test_pipeline_refuses_a_new_gnss_store_with_a_missing_description(
    monkeypatch, tmp_path
):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    store_path = tmp_path / "stores" / "fangorn-gnss"
    config = _config()  # site store_description missing
    monkeypatch.setattr("canvodpy.orchestrator.pipeline.store_exists", lambda _: False)

    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.site = SimpleNamespace(
        site_name="fangorn",
        _site_config=SimpleNamespace(store_description=None),
        gnss_store_path=store_path,
    )
    orchestrator._config = config

    with pytest.raises(ValueError, match=re.escape("sites.fangorn.store_description")):
        orchestrator._check_new_store_settings()
    assert not store_path.exists()


def test_pipeline_names_every_missing_setting_at_once(monkeypatch, tmp_path):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    config = SimpleNamespace(
        processing=SimpleNamespace(
            metadata=SimpleNamespace(
                publisher=None,
                license=None,
                naming_authority=None,
                store_description=None,
            )
        )
    )
    monkeypatch.setattr("canvodpy.orchestrator.pipeline.store_exists", lambda _: False)

    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.site = SimpleNamespace(
        site_name="fangorn",
        _site_config=SimpleNamespace(store_description=None),
        gnss_store_path=tmp_path / "stores" / "fangorn-gnss",
    )
    orchestrator._config = config

    with pytest.raises(ValueError) as err:
        orchestrator._check_new_store_settings()
    message = str(err.value)
    for name in (
        "sites.fangorn.store_description",
        "processing.metadata.publisher",
        "processing.metadata.license",
        "processing.metadata.naming_authority",
    ):
        assert name in message


def test_pipeline_does_not_check_an_existing_store(monkeypatch, tmp_path):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    config = _config()  # description missing, but the store exists
    monkeypatch.setattr("canvodpy.orchestrator.pipeline.store_exists", lambda _: True)

    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.site = SimpleNamespace(
        site_name="fangorn",
        _site_config=SimpleNamespace(store_description=None),
        gnss_store_path=tmp_path / "stores" / "fangorn-gnss",
    )
    orchestrator._config = config

    orchestrator._check_new_store_settings()  # must not raise


# ---------------------------------------------------------------------------
# The CLI refuses a first VOD store, unless --no-vod
# ---------------------------------------------------------------------------


def test_run_refuses_a_new_vod_store_with_a_missing_description(monkeypatch, tmp_path):
    from canvodpy.cli.run import _refuse_new_vod_store_missing_settings

    config = _config()
    monkeypatch.setattr("canvodpy.cli.run.store_exists", lambda _: False)
    site = SimpleNamespace(name="fangorn", vod_store_path=tmp_path / "stores" / "vod")

    with pytest.raises(ValueError, match=re.escape("sites.fangorn.store_description")):
        _refuse_new_vod_store_missing_settings(
            site, config, {"canopy_01_vs_reference_01": object()}
        )


def test_run_keeps_a_new_vod_store_unchecked_under_no_vod(monkeypatch, tmp_path):
    from canvodpy.cli.run import _refuse_new_vod_store_missing_settings

    config = _config()
    site = SimpleNamespace(name="fangorn", vod_store_path=tmp_path / "stores" / "vod")

    # --no-vod gives an empty vod_analyses, so the VOD store is not checked,
    # even though it does not exist and its settings are missing.
    _refuse_new_vod_store_missing_settings(site, config, {})


def test_run_keeps_an_existing_vod_store_unchecked(monkeypatch, tmp_path):
    from canvodpy.cli.run import _refuse_new_vod_store_missing_settings

    config = _config()
    monkeypatch.setattr("canvodpy.cli.run.store_exists", lambda _: True)
    site = SimpleNamespace(name="fangorn", vod_store_path=tmp_path / "stores" / "vod")

    _refuse_new_vod_store_missing_settings(
        site, config, {"canopy_01_vs_reference_01": object()}
    )
