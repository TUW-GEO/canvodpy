"""A run processes NMEA data: the receiver position comes from GGA (#451).

The hour of Hainich NMEA test data (u-blox, both receivers, 2026-001)
through ``canvodpy run`` with the final orbits and clocks of the test data,
so no download. Locally only: it reads the test data, which CI never checks
out.
"""

from __future__ import annotations

import json

import pytest
import zarr
from synthetic_days import TEST_DATA, link_aux
from typer.testing import CliRunner

from canvod.config import loader as config_loader_module
from canvod.store import MyIcechunkStore
from canvod.utils import testing

HAINICH = TEST_DATA / "nmea" / "02_Hainich"
DAY = "2026001"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not HAINICH.exists(),
        reason="Integration test requires the test data (git submodule)",
    ),
]


@pytest.fixture
def hainich_settings(tmp_path, monkeypatch):
    """Settings of the made-up site on the Hainich NMEA test data."""
    folder = tmp_path / "settings"
    path = testing.write_settings(folder)
    settings = json.loads(path.read_text())
    settings["processing"]["aux_data"] = {"agency": "COD", "product_type": "final"}
    settings["processing"]["params"] = {"ephemeris_source": "final"}
    settings["sites"][testing.SITE_KEY] = {
        "gnss_site_data_root": str(HAINICH),
        "store_description": "One hour of NMEA observations from the test data.",
        "receivers": {
            "reference_01": {
                "type": "reference",
                "directory": "01_reference",
                "reader_format": "nmea",
                "paired_canopies": "all",
            },
            "canopy_01": {
                "type": "canopy",
                "directory": "02_canopy",
                "reader_format": "nmea",
            },
        },
        "vod_analyses": {
            "canopy_01_vs_reference_01": {
                "canopy_receiver": "canopy_01",
                "reference_receiver": "reference_01",
            }
        },
    }
    path.write_text(json.dumps(settings))
    link_aux(folder / "aux")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    config_loader_module._load_config_cached.cache_clear()
    yield folder / "stores" / testing.SITE_KEY
    config_loader_module._load_config_cached.cache_clear()


def _data_groups(store: MyIcechunkStore) -> list[str]:
    """The groups that hold data (an ``epoch`` axis), nested ones included."""
    with store.readonly_session("main") as session:
        root = zarr.open_group(session.store, mode="r")
        return sorted(
            path
            for path, member in root.members(max_depth=None)
            if isinstance(member, zarr.Group) and "epoch" in member
        )


def test_a_run_of_nmea_data_writes_the_gnss_and_vod_stores(hainich_settings):
    from canvodpy.cli.app import main_app

    result = CliRunner().invoke(
        main_app, ["run", "--site", testing.SITE_KEY, "--start", DAY, "--end", DAY]
    )

    assert result.exit_code == 0, result.output
    gnss = MyIcechunkStore(hainich_settings / "rinex", store_type="gnss_store")
    vod = MyIcechunkStore(hainich_settings / "vod", store_type="vod_store")
    assert {"canopy_01", "reference_01_canopy_01"} <= set(_data_groups(gnss))
    assert _data_groups(vod)
    canopy = gnss.read_group("canopy_01", drop_empty=True)
    assert canopy.sizes["epoch"] > 0
    assert canopy["theta"].notnull().any()
