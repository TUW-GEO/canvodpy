"""A run interpolates the orbits as ``sp3_interpolation`` says; its store keeps it.

On the RINEX test data with the broadcast orbits of its navigation files,
which go through the same orbit interpolation as the agency products.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_broadcast_rinex_run import NAV, _run, _settings

from canvod.config import loader as config_loader_module
from canvod.store import MyIcechunkStore
from canvod.store.prepare import ORBIT_INTERPOLATION_COLUMN
from canvod.store_metadata.log_book import read_log_book

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not NAV.exists(),
        reason="Integration test requires the test data (git submodule)",
    ),
]


@pytest.fixture(autouse=True)
def _fresh_config():
    yield
    config_loader_module._load_config_cached.cache_clear()


def _set_sp3_interpolation(tmp_path: Path, method: str) -> None:
    path = tmp_path / "settings" / "canvod-settings.yaml"
    settings = json.loads(path.read_text())
    settings["processing"].setdefault("aux_data", {})["sp3_interpolation"] = method
    path.write_text(json.dumps(settings))
    config_loader_module._load_config_cached.cache_clear()


def test_a_hermite_run_records_hermite_and_its_store_refuses_lagrange(
    tmp_path, monkeypatch
) -> None:
    stores = _settings(tmp_path, monkeypatch)
    _set_sp3_interpolation(tmp_path, "hermite")

    result = _run()

    assert result.exit_code == 0, result.output
    gnss = MyIcechunkStore(stores / "gnss", store_type="gnss_store")
    with gnss.readonly_session() as session:
        rows = read_log_book(session.store, "canopy_01")
    recorded = [json.loads(v) for v in rows[ORBIT_INTERPOLATION_COLUMN].to_list()]
    assert recorded
    assert all(r == {"method": "hermite"} for r in recorded)

    _set_sp3_interpolation(tmp_path, "lagrange")
    result = _run()

    output = " ".join(result.output.split())
    assert "processing.aux_data.sp3_interpolation" in output
    assert '"hermite", this run "lagrange"' in output
