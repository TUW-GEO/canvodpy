"""Pytest configuration for canvodpy tests."""

import json
import os
from pathlib import Path

import pytest
import yaml
from synthetic_days import link_aux

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


@pytest.fixture(autouse=True)
def _isolated_run_pid_file(tmp_path, monkeypatch):
    """Point the run lock at a temporary file (#401).

    ``canvodpy run`` writes its PID to ``~/.cache/canvodpy/run.pid`` and
    ``canvodpy store maintain-due`` skips while that PID lives. With the
    real file, a run on this machine made the maintain-due tests fail, and
    a test run deleted the file of the live run on exit.
    """
    from canvodpy.orchestrator import resources

    monkeypatch.setattr(resources, "DEFAULT_RUN_PID_FILE", tmp_path / "run.pid")


# ── One day of the Rosalia test data through the pipeline ─────────────────

# The settings template of the repository: the Rosalia tests start from it,
# not from the local settings file, so they run the same on every machine
# and in CI.
_SETTINGS_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "config" / "canvod-settings.yaml.example"
)

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
def fangorn_site(tmp_path, monkeypatch):
    """The made-up site on the Rosalia test data, ready to run.

    Uses self-contained test data and receiver config, and settings loaded
    from the settings template (``config/canvod-settings.yaml.example``)
    with the made-up person filled in, so the run is independent of the
    user's local settings file. Returns the patched settings and the site's
    ``GnssResearchSite``.
    """
    if not HAS_TEST_DATA:
        pytest.skip("Integration test requires the test data (git submodule)")

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
    settings = yaml.safe_load(_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    settings["processing"]["metadata"].update(
        author=testing.PERSON_NAME,
        email=testing.PERSON_EMAIL,
        institution=testing.INSTITUTION,
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(settings), encoding="utf-8"
    )
    patched_config = config_pkg.load_config(config_dir=config_dir)
    patched_config.processing.storage.stores_root_dir = tmp_path / "stores"
    patched_config.processing.storage.aux_data_dir = tmp_path / "aux"
    # The orbit and clock files of the test data, so a run downloads none
    # (CI does not depend on the download servers).
    link_aux(tmp_path / "aux")
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
    return patched_config, site


@pytest.fixture
def fangorn_one_day(fangorn_site):
    """Run the pipeline on one day of the Rosalia test data.

    Returns the patched settings and the number of days processed.
    """
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    patched_config, site = fangorn_site
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
