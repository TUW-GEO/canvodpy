"""A run compares its preprocessing with the stores before it processes data."""

from types import SimpleNamespace

import pytest

from canvod.config.models import PreprocessingConfig, PreprocessingMismatchError

CONFIG = PreprocessingConfig.model_validate(
    {
        "temporal_aggregation": {
            "freq": "1min",
            "method": "mean",
            "integer_method": "first",
        },
        "grid_assignment": {"grid_type": "equal_area", "angular_resolution": 5.0},
    }
)
PLANNED = [
    {
        "op": "temporal_aggregate",
        "settings": {"freq": "1min", "method": "mean", "integer_method": "first"},
    },
    {
        "op": "grid_assign",
        "settings": {"grid_type": "equal_area", "angular_resolution": 5.0},
    },
]


class _Store:
    """Records the checks; refuses ``refuse``."""

    def __init__(self, refuse: str | None = None) -> None:
        self.checked: list[tuple[str, list]] = []
        self.refuse = refuse

    def check_settings_match(self, group_name, settings):
        self.checked.append((group_name, settings))
        if group_name == self.refuse:
            raise PreprocessingMismatchError(f"refused {group_name}")


def _settings(monkeypatch, module):
    config = SimpleNamespace(processing=SimpleNamespace(preprocessing=CONFIG))
    monkeypatch.setattr(module, "load_config", lambda: config)


def test_orchestrator_refuses_other_preprocessing_before_reading(site_settings):
    """Preprocessing is part of the content settings (ADR 0019, #349)."""
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    from canvod.config import load_config
    from canvod.store import GnssResearchSite
    from canvod.store_metadata import ContentSettingsError, ensure_store_metadata
    from canvod.utils import testing

    config = load_config()
    site = GnssResearchSite(testing.SITE_KEY)
    ensure_store_metadata(
        site.gnss_store_path,
        config=config,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=["canopy_01"],
    )
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.site = site
    orchestrator._config = config
    orchestrator._check_content_settings_before_run()

    other = config.model_copy(deep=True)
    other.processing.preprocessing = CONFIG
    orchestrator._config = other
    with pytest.raises(ContentSettingsError, match=r"processing\.preprocessing"):
        orchestrator._check_content_settings_before_run()


def test_vod_computer_checks_each_analysis_group(monkeypatch):
    from canvodpy.vod_computer import VodComputer

    import canvod.config

    _settings(monkeypatch, canvod.config)
    monkeypatch.setattr("canvod.store_metadata.store_exists", lambda _: True)
    store = _Store(refuse="tau_omega/canopy_01_vs_reference_01")
    site = SimpleNamespace(
        name="fangorn", vod_store_path=None, _site=SimpleNamespace(vod_store=store)
    )
    computer = VodComputer(site, calculator="tau_omega")
    with pytest.raises(PreprocessingMismatchError):
        computer.check_preprocessing(["canopy_01_vs_reference_01"])
    assert store.checked == [("tau_omega/canopy_01_vs_reference_01", PLANNED)]
