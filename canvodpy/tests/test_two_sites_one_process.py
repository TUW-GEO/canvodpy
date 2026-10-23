"""Two Site objects in one process, with a recipe given as a link (#502)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from canvodpy.orchestrator.discovery import clear_discovery_cache
from test_discovery import _FANGORN_RECIPE
from test_run_discovery_messages import _write_site

import canvod.config.loader as loader_module
from canvod.utils import remote_file, testing

URL = (
    "https://raw.githubusercontent.com/acc/recipes/refs/heads/main/fangorn/ros_ref.yaml"
)


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("canvod.filemap.remote")
    config_dir = _write_site(tmp_path)
    settings_file = config_dir / "canvod-settings.yaml"
    settings = yaml.safe_load(settings_file.read_text())
    receivers = settings["sites"]["fangorn"]["receivers"]
    receivers["canopy_01"]["reader_format"] = "rinex3"
    receivers["reference_01"]["reader_format"] = "rinex3"
    receivers["reference_01"]["recipe"] = URL
    settings_file.write_text(yaml.safe_dump(settings))
    data = tmp_path / "data"
    for f in (data / "02_canopy").iterdir():
        f.unlink()
    for f in (data / "01_reference").iterdir():
        f.unlink()
    (data / "02_canopy" / "FANA01INK_R_20250010015_15M_05S_AA.rnx").write_text("")
    (data / "01_reference" / "25001").mkdir()
    (data / "01_reference" / "25001" / "rref001a15.25o").write_text("")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(remote_file, "_FOLDER", None)
    monkeypatch.setattr(remote_file, "_MADE_HERE", False)
    monkeypatch.setenv("CANVODPY_RUN_FOLDER", "")
    server = testing.RemoteFileServer()
    monkeypatch.setattr(remote_file, "_DOWNLOAD_ORIGIN", server.origin)
    server.serve(URL, _FANGORN_RECIPE.encode())
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield server
    server.close()
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


def _files(plan: dict) -> dict[str, int]:
    return {r["name"]: r["files"] for d in plan["dates"] for r in d["receivers"]}


def test_a_site_works_after_a_second_site_is_created(site):
    from canvodpy import Site

    a = Site("fangorn")
    with a.pipeline(dry_run=True) as pipeline:
        first = _files(pipeline.preview("2025001", "2025001"))
    first_folder = remote_file.run_folder()
    Site("fangorn")
    assert not first_folder.exists()
    with a.pipeline(dry_run=True) as pipeline:
        assert _files(pipeline.preview("2025001", "2025001")) == first
    assert first == {"canopy_01": 1, "reference_01_canopy_01": 1}


def test_a_pipeline_made_before_the_second_site(site):
    from canvodpy import Site

    a = Site("fangorn")
    with a.pipeline(dry_run=True) as pipeline:
        first = _files(pipeline.preview("2025001", "2025001"))
        Site("fangorn")
        assert _files(pipeline.preview("2025001", "2025001")) == first
    # The second Site starts a new run folder, so the recipe is fetched again.
    assert len(site.requests) == 2
