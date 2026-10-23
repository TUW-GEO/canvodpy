"""Downloads report through structlog, not print (the run's console stays clean)."""

from pathlib import Path

import pytest
import structlog
from structlog.testing import capture_logs

from canvod.auxiliary.core import downloader as downloader_module
from canvod.auxiliary.core.downloader import FtpDownloader


@pytest.fixture(autouse=True)
def _fresh_server_hint():
    downloader_module._log_server_choice.cache_clear()
    yield
    downloader_module._log_server_choice.cache_clear()


@pytest.fixture
def logs(monkeypatch):
    """What the downloader logs while the test runs.

    A run configures structlog with cached loggers, so an earlier test can
    leave the module's logger bound to processors capture_logs does not
    reach. A logger made inside the capture logs into it.
    """
    with capture_logs() as entries:
        monkeypatch.setattr(
            downloader_module, "log", structlog.get_logger(downloader_module.__name__)
        )
        yield entries


def test_creating_downloaders_prints_nothing_and_logs_the_hint_once(capsys, logs):
    FtpDownloader()
    FtpDownloader()

    assert capsys.readouterr().out == ""
    hints = [e for e in logs if e["event"] == "aux_servers"]
    assert len(hints) == 1
    assert hints[0]["log_level"] == "info"


def test_failed_downloads_print_nothing_and_warn(
    capsys, monkeypatch, tmp_path: Path, logs
):
    def refuse(url, destination):
        raise FileNotFoundError(f"550 {url} not found")

    ftp = FtpDownloader(alt_servers=["ftp://alt.example.org"])
    monkeypatch.setattr(ftp, "_try_download_url", refuse)

    with pytest.raises(RuntimeError):
        ftp.download("ftp://gssc.esa.int/gnss/products/x.sp3.gz", tmp_path / "x.sp3")

    assert capsys.readouterr().out == ""
    warned = {e["event"] for e in logs if e["log_level"] == "warning"}
    assert {"primary_download_failed", "fallback_download_failed"} <= warned
