"""File downloaders for auxiliary GNSS data."""

import gzip
import shutil
import time
from abc import ABC, abstractmethod
from ftplib import FTP_TLS, error_perm
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request
from urllib.parse import urlparse

import structlog
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

log = structlog.get_logger(__name__)


def _download_progress() -> Progress:
    """Create a Rich progress bar configured for file downloads."""
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )


class FileDownloader(ABC):
    """Protocol defining the interface for file downloading implementations."""

    @abstractmethod
    def download(
        self,
        url: str,
        destination: Path,
        file_info: dict[str, Any] | None = None,
    ) -> Path:
        """Download a file from a URL to a destination.

        Parameters
        ----------
        url : str
            Source URL.
        destination : Path
            Local path to save the file.
        file_info : dict[str, Any], optional
            Optional context for downloaders (e.g., agency, GPS week).

        Returns
        -------
        Path
            Path to the downloaded file.
        """
        pass

    def _is_network_error(self, exception: Exception) -> bool:
        """Whether an exception is network-connectivity related."""
        return False


class FtpDownloader(FileDownloader):
    """FTP downloader with progress bar and fallback servers.

    Parameters
    ----------
    alt_servers : list[str], optional
        List of alternative FTP server URLs.
    user_email : str, optional
        Email for authenticated FTP servers (NASA CDDIS).
    """

    NASA_FTP = "ftp://gdc.cddis.eosdis.nasa.gov"
    ESA_FTP = "ftp://gssc.esa.int"

    def __init__(
        self,
        alt_servers: list[str] | None = None,
        user_email: str | None = None,
        timeout_s: int = 30,
    ):
        """Initialize downloader with optional alternate servers."""
        self.timeout_s = timeout_s
        if alt_servers is None:
            if user_email is not None:
                # Primary is NASA (set by caller); fallback to ESA
                self.alt_servers = [self.ESA_FTP]
                print("ℹ ESA fallback enabled (primary: NASA CDDIS)")
            else:
                self.alt_servers = []
                print("ℹ Using ESA FTP exclusively")
                print(
                    "  To download from NASA CDDIS first, with ESA as the "
                    "fallback, set "
                    "CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL "
                    "in config/.env or as an environment variable"
                )
        else:
            if user_email is None:
                self.alt_servers = [s for s in alt_servers if "cddis" not in s.lower()]
                if len(self.alt_servers) < len(alt_servers):
                    print("⚠ Skipping CDDIS servers (no credentials)")
            else:
                self.alt_servers = alt_servers

        self.user_email = user_email

    def download(
        self,
        url: str,
        destination: Path,
        file_info: dict[str, Any] | None = None,
    ) -> Path:
        """Download a file with progress tracking and fallback servers.

        Parameters
        ----------
        url : str
            Primary URL to download from.
        destination : Path
            Local path to save the file.
        file_info : dict[str, Any], optional
            Additional information (agency, GPS week, etc.).

        Returns
        -------
        Path
            Path to the downloaded file.
        """
        start_time = time.time()
        destination.parent.mkdir(parents=True, exist_ok=True)

        log.info(
            "file_download_started",
            url=url,
            destination=str(destination),
            file_info=file_info,
        )

        try:
            print(f"Attempting to download from primary server: {url}")
            result = self._try_download_url(url, destination)
            duration = time.time() - start_time

            log.info(
                "file_download_complete",
                url=url,
                destination=str(destination),
                duration_seconds=round(duration, 2),
                server="primary",
            )
            return result
        except Exception as e:
            # Check if this is a network connectivity issue
            if self._is_network_error(e):
                log.error(
                    "network_error",
                    error=str(e),
                    exception=type(e).__name__,
                )
                raise RuntimeError(
                    "❌ No internet connection detected.\n"
                    "   Please check your network and try again."
                ) from e

            print(f"Primary download failed: {e!s}")
            log.warning(
                "primary_download_failed",
                url=url,
                error=str(e),
                exception=type(e).__name__,
            )

            all_errors = [f"Primary server error: {e!s}"]

            if not self.alt_servers:
                print("ℹ No fallback servers available")
                log.error(
                    "no_fallback_servers",
                    url=url,
                    alt_servers_configured=False,
                )
                raise RuntimeError(
                    f"Failed to download file from primary server.\n"
                    f"\nPrimary URL: {url}\n"
                    f"Error: {e!s}\n"
                    f"\nPossible causes:\n"
                    f"  - File not yet available (product may not be published yet)\n"
                    f"  - Incorrect FTP path for server\n"
                    f"  - Temporary server issue\n"
                    f"\nTip: add NASA_EARTHDATA_ACC_MAIL to config/.env "
                    f"to enable NASA CDDIS fallback"
                ) from e

            for alt_server in self.alt_servers:
                try:
                    if file_info and "cddis" in alt_server.lower():
                        alt_url = self._construct_nasa_cddis_url(file_info)
                    else:
                        alt_url = self._construct_alternate_url(url, alt_server)

                    print(f"Trying alternate server: {alt_url}")
                    log.info(
                        "fallback_download_started",
                        alt_url=alt_url,
                        alt_server=alt_server,
                    )
                    result = self._try_download_url(alt_url, destination)
                    duration = time.time() - start_time

                    log.info(
                        "file_download_complete",
                        url=alt_url,
                        destination=str(destination),
                        duration_seconds=round(duration, 2),
                        server="fallback",
                        fallback_server=alt_server,
                    )
                    return result
                except Exception as alt_e:
                    # Check for network error on alternate server too
                    if self._is_network_error(alt_e):
                        raise RuntimeError(
                            "❌ No internet connection detected.\n"
                            "   Please check your network and try again."
                        ) from alt_e

                    error_msg = f"Alternate server {alt_server} error: {alt_e!s}"
                    print(error_msg)
                    all_errors.append(error_msg)

            raise RuntimeError(
                "Failed to download from all servers. Errors:\n" + "\n".join(all_errors)
            ) from e

    def _try_download_url(self, url: str, destination: Path) -> Path:
        """Attempt to download from a specific URL."""
        temp_path = destination.with_suffix(destination.suffix + ".tmp")

        if urlparse(url).hostname == urlparse(self.NASA_FTP).hostname:
            return self._download_from_nasa_cddis(url, destination)
        else:
            with _download_progress() as progress:
                task = progress.add_task(destination.name, total=None)

                def update_progress(count, block_size, total_size):
                    if total_size != -1:
                        progress.update(task, total=total_size)
                    progress.advance(task, block_size)

                request.urlretrieve(url, temp_path, reporthook=update_progress)

        if url.endswith(".gz"):
            with gzip.open(temp_path, "rb") as f_in:
                with open(destination, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            temp_path.unlink()
        else:
            temp_path.rename(destination)

        return destination

    def _download_from_nasa_cddis(self, url: str, destination: Path) -> Path:
        """Download file from NASA CDDIS server using FTPS."""
        if self.user_email is None:
            raise RuntimeError(
                "NASA CDDIS requires authentication. "
                "Set CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL "
                "in config/.env.\n"
                "Register at: https://urs.earthdata.nasa.gov/users/new"
            )

        parts = url.replace("ftp://", "").replace("ftps://", "").split("/")
        host = parts[0]
        directory = "/".join(parts[1:-1])
        filename = parts[-1]

        print(f"Connecting to {host} using FTPS...")
        ftps = FTP_TLS(host=host, timeout=self.timeout_s)
        ftps.login(user="anonymous", passwd=self.user_email)
        ftps.prot_p()

        for subdir in directory.split("/"):
            if subdir:
                try:
                    ftps.cwd(subdir)
                except error_perm as e:
                    raise RuntimeError(
                        f"Failed to change to directory {subdir}: {e!s}"
                    ) from e

        if filename not in ftps.nlst():
            raise RuntimeError(f"File {filename} not found in directory {directory}")

        temp_path = destination.with_suffix(destination.suffix + ".tmp")
        with temp_path.open("wb") as f:
            with _download_progress() as progress:
                total = None
                try:
                    size = ftps.size(filename)
                    if size:
                        total = size
                except OSError, error_perm:
                    pass

                task = progress.add_task(filename, total=total)

                def write_callback(data):
                    f.write(data)
                    progress.advance(task, len(data))

                ftps.retrbinary(f"RETR {filename}", write_callback)

        ftps.quit()

        if filename.endswith(".gz"):
            with gzip.open(temp_path, "rb") as f_in:
                with destination.open("wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            temp_path.unlink()
        else:
            temp_path.rename(destination)

        return destination

    def _is_network_error(self, exception: Exception) -> bool:
        """Check if exception indicates a network connectivity issue.

        Parameters
        ----------
        exception : Exception
            The exception to check.

        Returns
        -------
        bool
            True if the error is network-related.
        """
        # Check for common network error patterns
        error_str = str(exception).lower()
        network_indicators = [
            "nodename nor servname provided",  # DNS failure (errno 8)
            "no route to host",  # Network unreachable
            "network is unreachable",
            "temporary failure in name resolution",
            "connection refused",
            "no address associated with hostname",
        ]

        # Check error message
        if any(indicator in error_str for indicator in network_indicators):
            return True

        # Check errno codes for network issues
        if isinstance(exception, OSError):
            # Common network-related errno values
            network_errnos = {
                8,  # EAI_NONAME: nodename nor servname provided
                101,  # ENETUNREACH: Network unreachable
                113,  # EHOSTUNREACH: No route to host
                111,  # ECONNREFUSED: Connection refused
            }
            if exception.errno in network_errnos:
                return True

        # Check urllib errors
        if isinstance(exception, urlerror.URLError):
            if isinstance(exception.reason, OSError):
                return self._is_network_error(exception.reason)

        return False

    def _construct_alternate_url(self, original_url: str, alt_server: str) -> str:
        """Construct an alternate URL based on server's directory structure."""
        _, _, server_path = original_url.partition("://")
        server, _, path = server_path.partition("/")
        return f"{alt_server.rstrip('/')}/{path}"

    def _construct_nasa_cddis_url(self, file_info: dict) -> str:
        """Construct URL specifically for NASA CDDIS server."""
        gps_week = file_info.get("gps_week")
        filename = file_info.get("filename")
        return f"{self.NASA_FTP}/gnss/products/{gps_week}/{filename}.gz"
