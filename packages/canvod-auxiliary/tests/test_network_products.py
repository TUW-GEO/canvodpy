"""The product registry against the real FTP servers (#455).

The other registry tests use fake listers and a fake downloader, so a server
that moves a directory, an agency that renames its files or a product that
is no longer published only shows in a user's run. These tests reach the
servers. They run with ``just test-network`` (before a release and after a
registry change), never in GitHub CI: without ``CANVOD_NETWORK_TESTS=1``
they are skipped.

NASA CDDIS is checked only when ``CANVOD_CDDIS_MAIL`` holds a NASA Earthdata
e-mail; ``just test-network`` takes it from the settings.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from canvod.utils.tools import YYYYDOY

from canvod.auxiliary.clock.reader import ClkFile
from canvod.auxiliary.core.downloader import FtpDownloader
from canvod.auxiliary.ephemeris.reader import Sp3File
from canvod.auxiliary.products.check import check_registry, ftp_lister
from canvod.auxiliary.products.registry_config import get_registry

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("CANVOD_NETWORK_TESTS") != "1",
        reason="network test: run with just test-network",
    ),
]

#: The test data's day: every registry product has published its files.
DAY = "2025001"
CDDIS_MAIL = os.environ.get("CANVOD_CDDIS_MAIL") or None

TEST_DATA_AUX = Path(__file__).parents[2] / (
    "canvod-readers/tests/test_data/valid/aux_data"
)

_REGISTRY = get_registry()
_PRODUCTS = sorted(_REGISTRY.list_products())


@pytest.mark.parametrize(
    ("agency", "product_type"), _PRODUCTS, ids=[f"{a}/{p}" for a, p in _PRODUCTS]
)
def test_product_files_are_on_a_server(agency: str, product_type: str) -> None:
    spec = _REGISTRY.get_product_spec(agency, product_type)
    (result,) = check_registry(
        [DAY], ftp_lister(CDDIS_MAIL), with_auth=bool(CDDIS_MAIL), products=[spec]
    )
    if result.skipped:
        pytest.skip(f"{result.product} is only on servers with login (no CDDIS mail)")
    present = ", ".join(result.present) or "no SP3/CLK file of this product"
    assert result.ok, f"{result.product} {DAY} not found; on the servers: {present}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "server",
    [s.url for s in _REGISTRY.get_product_spec("COD", "final").ftp_servers],
)
def test_cod_final_download_matches_the_test_data(server: str, tmp_path) -> None:
    spec = _REGISTRY.get_product_spec("COD", "final")
    auth = next(s.requires_auth for s in spec.ftp_servers if s.url == server)
    if auth and not CDDIS_MAIL:
        pytest.skip(f"{server} needs a login (no CDDIS mail)")
    week = YYYYDOY.from_str(DAY).gps_week
    downloader = FtpDownloader(alt_servers=[], user_email=CDDIS_MAIL)

    for reader, folder, names in (
        (Sp3File, "01_SP3", spec.sp3_filenames(DAY)),
        (ClkFile, "02_CLK", spec.clk_filenames(DAY)),
    ):
        local = [n for n in names if (TEST_DATA_AUX / folder / n).exists()]
        assert local, f"no COD final {folder} file of {DAY} in {TEST_DATA_AUX}"
        name = local[0]
        path = spec.ftp_path_pattern.format(gps_week=week, file=f"{name}.gz")
        try:
            downloaded = downloader.download(f"{server}{path}", tmp_path / name)
        except Exception as error:
            pytest.fail(
                f"{server}{path} not downloaded ({error}); the server may no "
                f"longer keep {DAY}: then move DAY and the test data on"
            )

        assert _sha256(downloaded) == _sha256(TEST_DATA_AUX / folder / name)
        assert reader.from_file(downloaded).data.sizes["epoch"] > 0
