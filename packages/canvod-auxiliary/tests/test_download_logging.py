"""Downloads report through structlog, not print (the run's console stays clean)."""

from pathlib import Path

import pytest
from structlog.testing import capture_logs

from canvod.auxiliary.core import downloader as downloader_module
from canvod.auxiliary.core.downloader import FtpDownloader


@pytest.fixture(autouse=True)
def _fresh_server_hint():
    downloader_module._log_server_choice.cache_clear()
    yield
    downloader_module._log_server_choice.cache_clear()


def test_creating_downloaders_prints_nothing_and_logs_the_hint_once(capsys):
    with capture_logs() as logs:
        FtpDownloader()
        FtpDownloader()

    assert capsys.readouterr().out == ""
    hints = [e for e in logs if e["event"] == "aux_servers"]
    assert len(hints) == 1
    assert hints[0]["log_level"] == "info"


def test_failed_downloads_print_nothing_and_warn(capsys, monkeypatch, tmp_path: Path):
    def refuse(url, destination):
        raise FileNotFoundError(f"550 {url} not found")

    ftp = FtpDownloader(alt_servers=["ftp://alt.example.org"])
    monkeypatch.setattr(ftp, "_try_download_url", refuse)

    with capture_logs() as logs, pytest.raises(RuntimeError):
        ftp.download("ftp://gssc.esa.int/gnss/products/x.sp3.gz", tmp_path / "x.sp3")

    assert capsys.readouterr().out == ""
    warned = {e["event"] for e in logs if e["log_level"] == "warning"}
    assert {"primary_download_failed", "fallback_download_failed"} <= warned
