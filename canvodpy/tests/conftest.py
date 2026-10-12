"""Pytest configuration for canvodpy tests."""

import json
import os
from pathlib import Path

import pytest

from canvod.config import loader as config_loader_module
from canvod.config.models import ReceiverConfig, VodAnalysisConfig
from canvod.config.models.references import ReferencesConfig
from canvod.utils import testing

_CONFIG_ENV = ("CANVOD_CONFIG_DIR", "CANVOD_CONFIG_FILE")


@pytest.fixture(autouse=True)
def _restore_config_env():
    """Undo ``CANVOD_CONFIG_*`` changes made by CLI options during a test.

    ``--config-dir`` and ``--config`` set these variables in the process
    that runs the command, which for ``CliRunner`` is the test process.
    """
    saved = {name: os.environ.get(name) for name in _CONFIG_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# ── One day of the Rosalia test data through the pipeline ─────────────────

# Check if config files and store paths are available
CONFIG_DIR = Path.cwd() / "config"
HAS_CONFIG = (CONFIG_DIR / "canvod-settings.yaml").exists()

# Reference test data inside the test-data submodule
_TEST_DATA = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
)
_ROSALIA_DATA = _TEST_DATA / "valid" / "rinex_v3_04" / "01_Rosalia"
HAS_TEST_DATA = _ROSALIA_DATA.exists()

# Receiver layout matching the test data directory structure
_TEST_RECEIVERS = {
    "reference_01": ReceiverConfig(
        type="reference",
        directory="01_reference/01_GNSS/01_raw",
        paired_canopies="all",
        description="Test reference receiver",
    ),
    "canopy_01": ReceiverConfig(
        type="canopy",
        directory="02_canopy/01_GNSS/01_raw",
        description="Test canopy receiver",
    ),
}

_TEST_VOD_ANALYSES = {
    "canopy_01_vs_reference_01": VodAnalysisConfig(
        canopy_receiver="canopy_01",
        reference_receiver="reference_01",
    ),
}


@pytest.fixture
def rosalia_one_day(tmp_path, monkeypatch):
    """Run the pipeline on one day of the Rosalia test data.

    Uses self-contained test data and receiver config so the run is
    independent of the user's local ``config/canvod-settings.yaml`` (which
    must exist, though: the settings are loaded from it and then patched).
    Returns the patched settings and the number of days processed.
    """
    if not (HAS_CONFIG and HAS_TEST_DATA):
        pytest.skip("Integration test requires config files and test data")
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    import canvod.config as config_pkg
    import canvod.config.loader as config_loader
    from canvod.config.models import SiteConfig
    from canvod.store import GnssResearchSite

    # GnssResearchSite.__init__ calls load_config() and looks up
    # sites.sites[site_name] to build the store + site config — fully
    # monkeypatch both so this test never depends on the real local
    # config/canvod-settings.yaml having the test site defined (or
    # existing at all). Mutate the already-validated config object directly
    # (models are frozen=False) rather than an env var override —
    # CANVOD__PROCESSING__STORAGE__... env vars replace the whole nested
    # `storage`/`sites` dict rather than merging into it (pydantic-settings'
    # BaseSettings source-merging), which would drop other sections.
    #
    # Patch _load_config_cached, not the public load_config name: every
    # module that does `from canvod.config import load_config` (processor.py,
    # pipeline.py, canvod-store/manager.py, ...) holds its own reference to
    # the original function object, so monkeypatching config_pkg.load_config
    # only affects call sites that do `canvod.config.load_config(...)` via
    # attribute lookup -- not the `from ... import load_config` ones. But
    # load_config() itself always delegates to _load_config_cached via a
    # module-global lookup inside loader.py, so patching that one name is
    # what all of them actually funnel through, regardless of which local
    # binding a given module holds. (Found 2026-07-23: this gap let a real
    # local config/canvod-settings.yaml with an external-drive
    # aux_data_dir leak into this "self-contained" test's aux-pipeline
    # setup and fail with PermissionError when the drive wasn't mounted.)
    patched_config = config_pkg.load_config()
    patched_config.processing.storage.stores_root_dir = tmp_path / "stores"
    patched_config.processing.storage.aux_data_dir = tmp_path / "aux"
    patched_config.processing.storage.shared_aux_cache_dir = None
    patched_config.processing.logging.log_dir = tmp_path / "logs"
    # The store metadata name the made-up person and site, never the local
    # settings' own; new stores need a naming authority (ADR 0015).
    patched_config.processing.metadata.author = testing.PERSON_NAME
    patched_config.processing.metadata.email = testing.PERSON_EMAIL
    patched_config.processing.metadata.institution = testing.INSTITUTION
    for field in (
        "orcid",
        "institution_ror",
        "department",
        "research_group",
        "website",
        "publisher_url",
        "store_description",
    ):
        setattr(patched_config.processing.metadata, field, None)
    patched_config.processing.references = ReferencesConfig()
    patched_config.processing.metadata.naming_authority = testing.NAMING_AUTHORITY
    patched_config.processing.metadata.publisher = testing.PUBLISHER
    patched_config.processing.metadata.license = "CC-BY-4.0"
    patched_config.sites.sites[testing.SITE_KEY] = SiteConfig(
        gnss_site_data_root=str(_ROSALIA_DATA),
        store_description="One day of GNSS observations from the test data.",
        latitude=testing.LATITUDE,
        longitude=testing.LONGITUDE,
        receivers={
            "canopy_01": ReceiverConfig(type="canopy", directory="placeholder"),
        },
    )
    monkeypatch.setattr(
        config_loader, "_load_config_cached", lambda *a, **kw: patched_config
    )

    site = GnssResearchSite(site_name=testing.SITE_KEY)

    # Override site config to use self-contained test data
    site._site_config.gnss_site_data_root = str(_ROSALIA_DATA)
    site._site_config.receivers = dict(_TEST_RECEIVERS)
    site._site_config.vod_analyses = dict(_TEST_VOD_ANALYSES)

    counter = 0
    with PipelineOrchestrator(site=site, dry_run=False) as orchestrator:
        for date_key, _datasets, _receiver_times in orchestrator.process_by_date(
            keep_vars=patched_config.processing.params.keep_gnss_observables,
            start_from=None,
            end_at=None,
        ):
            counter += 1
            if counter >= 1:
                break

    return patched_config, counter


@pytest.fixture
def site_settings(tmp_path, monkeypatch):
    """The made-up settings, with a reference receiver and a VOD analysis.

    For code that loads the settings itself and creates the site's stores.
    Returns the folder of the stores.
    """
    folder = tmp_path / "settings"
    path = testing.write_settings(folder)
    settings = json.loads(path.read_text())
    site = settings["sites"][testing.SITE_KEY]
    site["store_description"] = "GNSS-T observations below an Ent canopy"
    site["receivers"]["reference_01"] = {
        "type": "reference",
        "directory": "01_reference",
        "paired_canopies": ["canopy_01"],
    }
    site["vod_analyses"] = {
        "canopy_01_vs_reference_01": {
            "canopy_receiver": "canopy_01",
            "reference_receiver": "reference_01",
        }
    }
    path.write_text(json.dumps(settings))
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    config_loader_module._load_config_cached.cache_clear()
    yield folder / "stores"
    config_loader_module._load_config_cached.cache_clear()
