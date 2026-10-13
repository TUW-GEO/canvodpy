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


def test_orchestrator_checks_every_group_it_writes(monkeypatch):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    store = _Store()
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    monkeypatch.setattr("canvodpy.orchestrator.pipeline.store_exists", lambda _: True)
    orchestrator.site = SimpleNamespace(gnss_store=store, gnss_store_path=None)
    orchestrator._config = SimpleNamespace(
        processing=SimpleNamespace(preprocessing=CONFIG)
    )
    dates = [
        ("2025001", {"canopy_01": (), "reference_01_canopy_01": ()}),
        ("2025002", {"canopy_01": ()}),
    ]
    orchestrator._check_preprocessing_before_run(dates)
    assert store.checked == [
        ("canopy_01", PLANNED),
        ("reference_01_canopy_01", PLANNED),
    ]

    store.refuse = "reference_01_canopy_01"
    with pytest.raises(PreprocessingMismatchError, match="reference_01_canopy_01"):
        orchestrator._check_preprocessing_before_run(dates)


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
