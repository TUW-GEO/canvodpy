"""A first run refuses before processing when a new store's settings are missing.

Through the public entry points: ``Site.pipeline()`` (which Airflow's
``process_day`` also uses) and ``canvodpy run``. The test site leaves out
``sites.fangorn.store_description``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from canvodpy.cli.app import main_app
from canvodpy.orchestrator.discovery import clear_discovery_cache
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from test_run_discovery_messages import _write_site
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils.testing import SITE_KEY

runner = CliRunner()
MISSING = "sites.fangorn.store_description"


@pytest.fixture(autouse=True)
def _fresh():
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


@pytest.fixture
def site(tmp_path: Path, monkeypatch) -> Path:
    """The test site without a store description; returns the stores folder."""
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(_write_site(tmp_path)))
    return tmp_path / "stores"


@pytest.fixture
def batches(monkeypatch) -> list[object]:
    """Records every batch of days the orchestrator starts to read."""
    started: list[object] = []

    def record(self, dates, keep_vars, stop, **_):
        started.append(dates)
        yield from ()

    monkeypatch.setattr(PipelineOrchestrator, "_process_multi_day_batches", record)
    return started


def _without_store_metadata(config_dir: Path) -> None:
    """Remove every setting a new store needs from the test site."""
    path = config_dir / "canvod-settings.yaml"
    settings = yaml.safe_load(path.read_text())
    for key in ("publisher", "license", "naming_authority"):
        settings["processing"]["metadata"].pop(key)
    path.write_text(yaml.safe_dump(settings))


def _create_gnss_store(stores: Path) -> None:
    """An existing GNSS store: its metadata was written when it was created."""
    from canvod.store_metadata import open_repository

    open_repository(stores / SITE_KEY / "gnss", create=True)


def _run(*extra: str):
    return runner.invoke(
        main_app,
        ["run", "--site", SITE_KEY, "--start", "2025001", "--end", "2025001", *extra],
        env={"CANVOD_CONFIG_DIR": os.environ["CANVOD_CONFIG_DIR"]},
    )


# ---------------------------------------------------------------------------
# Site.pipeline() refuses a new GNSS store
# ---------------------------------------------------------------------------


def test_the_pipeline_refuses_before_reading_a_file(site, batches) -> None:
    from canvodpy.api import Site

    with pytest.raises(ValueError, match=MISSING):
        with Site(SITE_KEY).pipeline(n_workers=1) as pipeline:
            pipeline.process_date("2025001")

    assert batches == []
    assert not (site / SITE_KEY).exists()


def test_the_pipeline_names_every_missing_setting_at_once(site, batches) -> None:
    from canvodpy.api import Site

    _without_store_metadata(Path(os.environ["CANVOD_CONFIG_DIR"]))

    with pytest.raises(ValueError) as err:
        with Site(SITE_KEY).pipeline(n_workers=1) as pipeline:
            pipeline.process_date("2025001")

    for name in (
        MISSING,
        "processing.metadata.publisher",
        "processing.metadata.license",
        "processing.metadata.naming_authority",
    ):
        assert name in str(err.value)
    assert batches == []


def test_the_pipeline_does_not_check_an_existing_store(site, batches) -> None:
    from canvodpy.api import Site

    _create_gnss_store(site)

    with Site(SITE_KEY).pipeline(n_workers=1) as pipeline:
        pipeline.process_date("2025001")

    assert len(batches) == 1


# ---------------------------------------------------------------------------
# canvodpy run refuses a new GNSS or VOD store; --no-vod skips the VOD store
# ---------------------------------------------------------------------------


def test_run_refuses_a_new_gnss_store_before_reading_a_file(site, batches) -> None:
    result = _run("--no-vod")

    assert result.exit_code != 0
    assert MISSING in " ".join(result.output.split())
    assert batches == []
    assert not (site / SITE_KEY).exists()


def test_run_refuses_a_new_vod_store_before_reading_a_file(site, batches) -> None:
    _create_gnss_store(site)  # the VOD store is new

    result = _run()

    assert result.exit_code != 0
    assert "A new VOD store needs these settings" in " ".join(result.output.split())
    assert batches == []


def test_run_with_no_vod_does_not_check_the_vod_store(site, batches) -> None:
    _create_gnss_store(site)  # the VOD store is new

    result = _run("--no-vod")

    assert result.exit_code == 0, result.output
    assert len(batches) == 1
