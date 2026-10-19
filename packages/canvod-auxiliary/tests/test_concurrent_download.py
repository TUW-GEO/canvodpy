"""Downloads of the same file at the same time leave one whole file (#462).

A run prepares several days in parallel, and adjacent days load each
other's orbit and clock files, so two threads can download one file at
once.
"""

import gzip
import threading
from pathlib import Path

from canvod.auxiliary.core import downloader as downloader_module
from canvod.auxiliary.core.downloader import FtpDownloader

CONTENT = b"".join(
    b"AS G%02d 2026 06 21 00 00  0.000000  1  0.1e-03\n" % (i % 32)
    for i in range(20000)
)
THREADS = 8


def _slow_server(monkeypatch, payload: bytes) -> None:
    """Serve ``payload`` in small pieces, all threads writing at the same time."""
    start = threading.Barrier(THREADS)

    def urlretrieve(url, filename, reporthook=None):
        start.wait()
        with open(filename, "wb") as f:
            for i in range(0, len(payload), 4096):
                f.write(payload[i : i + 4096])
                f.flush()
        return filename, None

    monkeypatch.setattr(downloader_module.request, "urlretrieve", urlretrieve)


def _download_at_once(destination: Path, url: str) -> list[BaseException]:
    errors: list[BaseException] = []

    def fetch() -> None:
        try:
            FtpDownloader().download(url, destination)
        except BaseException as e:  # noqa: BLE001 - collected for the assertion
            errors.append(e)

    threads = [threading.Thread(target=fetch) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_compressed_file_downloaded_by_several_threads_is_whole(monkeypatch, tmp_path):
    _slow_server(monkeypatch, gzip.compress(CONTENT))
    destination = tmp_path / "02_CLK" / "COD0MGXFIN_20261720000_01D_30S_CLK.CLK"

    errors = _download_at_once(
        destination, "ftp://gssc.esa.int/gnss/products/2424/" + destination.name + ".gz"
    )

    assert errors == []
    assert destination.read_bytes() == CONTENT
    assert list(destination.parent.iterdir()) == [destination]


def test_plain_file_downloaded_by_several_threads_is_whole(monkeypatch, tmp_path):
    _slow_server(monkeypatch, CONTENT)
    destination = tmp_path / "01_SP3" / "COD0MGXFIN_20261720000_01D_05M_ORB.SP3"

    errors = _download_at_once(
        destination, "ftp://gssc.esa.int/gnss/products/2424/" + destination.name
    )

    assert errors == []
    assert destination.read_bytes() == CONTENT
    assert list(destination.parent.iterdir()) == [destination]
