"""A run that downloads its own orbits and clocks stores what a linked run stores (#455).

Every other run test links the orbit and clock files of the test data, so
CI never depends on the download servers. This one starts with an empty aux
directory and lets the run download them. It runs with ``just test-network``,
never in GitHub CI: without ``CANVOD_NETWORK_TESTS=1`` it is skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from canvod.store import MyIcechunkStore, compare_stores
from canvod.utils import testing

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("CANVOD_NETWORK_TESTS") != "1",
        reason="network test: run with just test-network",
    ),
]

DAY = "2025001"


def test_a_run_downloads_its_products_and_stores_the_same(rosalia_site, tmp_path):
    from canvodpy import Site

    config, test_site = rosalia_site
    site = config.sites.sites[testing.SITE_KEY]
    site.receivers = dict(test_site._site_config.receivers)
    site.vod_analyses = dict(test_site._site_config.vod_analyses)
    storage = config.processing.storage
    # Clocks too, so both downloads are covered (the settings leave them off).
    config.processing.aux_data.fetch_clock = True
    config.processing.credentials.nasa_earthdata_acc_mail = (
        os.environ.get("CANVOD_CDDIS_MAIL") or None
    )

    def run(name: str, aux_dir: Path) -> tuple[Path, Path]:
        storage.stores_root_dir = tmp_path / name
        storage.aux_data_dir = aux_dir
        with Site(testing.SITE_KEY).pipeline() as pipeline:
            list(pipeline.run(DAY, DAY))
        return (
            Path(storage.get_gnss_store_path(testing.SITE_KEY)),
            Path(storage.get_vod_store_path(testing.SITE_KEY)),
        )

    linked = run("linked", tmp_path / "aux")
    downloaded = run("downloaded", tmp_path / "aux_empty")

    assert any((tmp_path / "aux_empty").rglob("*ORB.SP3"))
    assert any((tmp_path / "aux_empty").rglob("*CLK.CLK"))
    for reference, new in zip(linked, downloaded, strict=True):
        result = compare_stores(MyIcechunkStore(reference), MyIcechunkStore(new))
        assert result.matches, result.to_text()
