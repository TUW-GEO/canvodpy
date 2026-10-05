"""Tests for the registry check and for trying several file names per product.

No network: the server listings and downloads are faked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from canvod.auxiliary.clock import ClkFile
from canvod.auxiliary.core.downloader import FileDownloader
from canvod.auxiliary.ephemeris import Sp3File
from canvod.auxiliary.products import get_product_spec
from canvod.auxiliary.products.check import check_registry

_ESA = "ftp://gssc.esa.int"
_NASA = "ftps://gdc.cddis.eosdis.nasa.gov"


def _lister(files: dict[str, set[str]]):
    calls = []

    def list_dir(server: str, path: str) -> set[str]:
        calls.append((server, path))
        return files.get(server, set())

    list_dir.calls = calls
    return list_dir


class TestCheckRegistry:
    def test_found_under_second_sampling(self):
        spec = get_product_spec("ESA", "rapid")
        lister = _lister(
            {
                _ESA: {
                    "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3.gz",
                    "ESA0OPSRAP_20250010000_01D_05M_CLK.CLK.gz",
                }
            }
        )
        [result] = check_registry(["2025001"], lister, False, [spec])

        assert result.ok
        assert result.sp3 == "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3"
        assert result.clk == "ESA0OPSRAP_20250010000_01D_05M_CLK.CLK"
        assert lister.calls == [(_ESA, "/gnss/products/2347/")]

    def test_missing_clock_fails_and_lists_what_is_there(self):
        spec = get_product_spec("COD", "final")
        lister = _lister({_ESA: {"COD0MGXFIN_20250010000_01D_05M_ORB.SP3.gz"}})
        [result] = check_registry(["2025001"], lister, False, [spec])

        assert not result.ok
        assert result.present == ["COD0MGXFIN_20250010000_01D_05M_ORB.SP3"]

    def test_product_without_clocks_needs_only_sp3(self):
        spec = get_product_spec("SIO", "final")
        lister = _lister({_ESA: {"SIO0OPSFIN_20250010000_01D_15M_ORB.SP3.gz"}})
        [result] = check_registry(["2025001"], lister, False, [spec])

        assert result.ok

    def test_nasa_only_product_skipped_without_account(self):
        spec = get_product_spec("IGS", "final")
        [result] = check_registry(["2025001"], _lister({}), False, [spec])

        assert result.skipped
        assert not result.ok

    def test_each_directory_listed_once(self):
        specs = [get_product_spec("COD", "final"), get_product_spec("GFZ", "final")]
        lister = _lister({})
        check_registry(["2025001"], lister, True, specs)

        assert sorted(lister.calls) == [
            (_ESA, "/gnss/products/2347/"),
            (_NASA, "/gnss/products/2347/"),
        ]


class _FakeDownloader(FileDownloader):
    """Downloader that has only the files in ``available``."""

    def __init__(self, available: set[str]) -> None:
        self.available = available
        self.urls: list[str] = []

    def download(self, url: str, destination: Path, file_info=None) -> Path:
        self.urls.append(url)
        if url.rsplit("/", 1)[-1].removesuffix(".gz") not in self.available:
            raise RuntimeError("550 not found")
        destination.write_text("data")
        return destination

    def _is_network_error(self, e: Exception) -> bool:
        return False


def _sp3(tmp_path: Path, downloader: _FakeDownloader) -> Sp3File:
    return Sp3File(
        date="2025001",
        agency="ESA",
        product_type="rapid",
        ftp_server=_ESA,
        local_dir=tmp_path,
        downloader=downloader,
    )


class TestCandidateFiles:
    def test_second_sampling_downloaded(self, tmp_path):
        downloader = _FakeDownloader({"ESA0OPSRAP_20250010000_01D_15M_ORB.SP3"})
        sp3 = _sp3(tmp_path, downloader)

        assert sp3.fpath == tmp_path / "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3"
        assert [u.rsplit("/", 1)[-1] for u in downloader.urls] == [
            "ESA0OPSRAP_20250010000_01D_05M_ORB.SP3.gz",
            "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3.gz",
        ]

    def test_local_copy_of_any_sampling_reused(self, tmp_path):
        (tmp_path / "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3").write_text("data")
        downloader = _FakeDownloader(set())
        sp3 = _sp3(tmp_path, downloader)

        assert sp3.fpath.name == "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3"
        assert downloader.urls == []

    def test_none_found_names_every_file_tried(self, tmp_path):
        with pytest.raises(RuntimeError) as exc:
            _sp3(tmp_path, _FakeDownloader(set()))
        assert "ESA0OPSRAP_20250010000_01D_05M_ORB.SP3" in str(exc.value)
        assert "ESA0OPSRAP_20250010000_01D_15M_ORB.SP3" in str(exc.value)

    def test_clock_of_product_without_clocks_refused(self, tmp_path):
        with pytest.raises(ValueError, match="publishes no clock files"):
            ClkFile(
                date="2025001",
                agency="SIO",
                product_type="final",
                ftp_server=_ESA,
                local_dir=tmp_path,
                downloader=_FakeDownloader(set()),
            )

    def test_generate_filename_deprecated(self, tmp_path):
        downloader = _FakeDownloader({"ESA0OPSRAP_20250010000_01D_05M_ORB.SP3"})
        sp3 = _sp3(tmp_path, downloader)
        with pytest.warns(FutureWarning, match="candidate_filenames"):
            name = sp3.generate_filename_based_on_type()
        assert name == Path("ESA0OPSRAP_20250010000_01D_05M_ORB.SP3")
