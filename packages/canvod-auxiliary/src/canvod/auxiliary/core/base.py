"""Abstract base class for auxiliary GNSS files."""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from canvod.utils.tools import YYYYDOY, deprecated
from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from canvod.auxiliary.core.downloader import FileDownloader, FtpDownloader
from canvod.auxiliary.interpolation import Interpolator

# How much of the previous and next day AuxFile.join_days keeps: several
# epochs of any product (15 min orbits, 30 s clocks), enough for the clock
# jump detection window on both sides.
DAY_JOIN_MARGIN = np.timedelta64(1, "h")


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class AuxFile(ABC):
    """Abstract base class for GNSS auxiliary files (SP3, CLK, IONEX, etc.).

    This class provides two ways to create instances:
    1. from_datetime_date(): Create from a datetime.date object and metadata
    2. from_file(): Create directly from an existing file path

    The class handles both newly downloaded files and existing local files,
    maintaining consistent behavior regardless of how the instance is created.

    FTP Server Configuration:
    ------------------------
    - user_email: Optional email for NASA CDDIS authentication
      - If None: Uses ESA FTP server exclusively (no authentication required)
      - If provided: Enables NASA CDDIS as fallback server (requires registration)
      - To enable CDDIS, set processing.credentials.nasa_earthdata_acc_mail
        in config/canvod-settings.yaml

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True`, and
    it uses `ABC` to define required subclass hooks.
    """

    date: str
    agency: str
    product_type: str
    ftp_server: str
    local_dir: Path
    file_type: list[str] = Field(default_factory=list)
    fpath: Path | None = None
    user_email: str | None = None
    ftp_timeout_s: int = 30
    downloader: FileDownloader | None = None
    _data: xr.Dataset | None = Field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize after dataclass creation.

        Sets up paths, downloader, and verifies local file existence.
        """
        if not self.file_type:
            self.file_type = ["unknown"]
        self.local_dir = Path(self.local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)

        if self.downloader is None:
            self.downloader = FtpDownloader(
                user_email=self.user_email, timeout_s=self.ftp_timeout_s
            )

        self.fpath = self.check_file_exists()

    @classmethod
    def from_datetime_date(
        cls,
        date: datetime.date,
        agency: str,
        product_type: str,
        ftp_server: str,
        local_dir: Path,
        **kwargs: Any,
    ) -> AuxFile:
        """Create an AuxFile instance from a datetime.date.

        Parameters
        ----------
        date : datetime.date
            Date for the desired auxiliary file.
        agency : str
            Agency providing the data (e.g., "COD", "IGS").
        product_type : str
            Product type ("final" or "rapid").
        ftp_server : str
            Base URL for file downloads.
        local_dir : Path
            Directory for storing files locally.
        **kwargs : Any
            Extra keyword arguments for subclass construction.

        Returns
        -------
        AuxFile
            A new instance of the AuxFile subclass.
        """
        yyyydoy = YYYYDOY.from_date(date=date).to_str()
        return cls(
            date=yyyydoy,
            agency=agency,
            product_type=product_type,
            ftp_server=ftp_server,
            local_dir=local_dir,
            **kwargs,
        )

    @classmethod
    def from_file(cls, fpath: Path | str, **kwargs: Any) -> AuxFile:
        """Create an AuxFile instance from an existing file path.

        Parameters
        ----------
        fpath : Path
            Path to the existing GNSS file.
        **kwargs : Any
            Extra keyword arguments for subclass construction.

        Returns
        -------
        AuxFile
            A new instance of the AuxFile subclass.

        Raises
        ------
        FileNotFoundError
            If the specified file does not exist.
        """
        fpath = Path(fpath)
        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")

        fname = fpath.name
        agency = fname[0:3]
        yyyydoy = fname.split("_")[1][0:7]

        return cls(
            date=yyyydoy,
            agency=agency,
            product_type="final",
            ftp_server="N/A",
            local_dir=fpath.parent,
            fpath=fpath,
            **kwargs,
        )

    def download_file(
        self,
        url: str,
        destination: Path,
        file_info: dict | None = None,
    ) -> Path:
        """Download a file using the configured downloader.

        Parameters
        ----------
        url : str
            Download URL.
        destination : Path
            Local file destination.
        file_info : dict, optional
            Extra info passed to the downloader.

        Returns
        -------
        Path
            Path to the downloaded file.
        """
        if self.downloader is None:
            raise RuntimeError("No downloader is configured")
        return self.downloader.download(url, destination, file_info)

    def download_with_fallback(
        self,
        ftp_path: str,
        destination: Path,
        file_info: dict | None = None,
        product_spec: Any | None = None,
    ) -> Path:
        """Download a file, trying all servers from the product spec in priority order.

        Iterates through the product's FTP server list (from products.toml),
        skipping servers that require authentication when no credentials are
        configured. Warns when falling back to an alternate server. Raises a
        clear error when all servers fail.

        Parameters
        ----------
        ftp_path : str
            Server-relative path (e.g. ``/gnss/products/2345/FILE.gz``).
        destination : Path
            Local file destination.
        file_info : dict, optional
            Extra context passed to the downloader.
        product_spec : ProductSpec, optional
            Product specification with ``ftp_servers`` list. If None, falls
            back to single-server download using ``self.ftp_server``.

        Returns
        -------
        Path
            Path to the downloaded file.

        Raises
        ------
        RuntimeError
            If download fails from all available servers.
        """
        if self.downloader is None:
            raise RuntimeError("No downloader is configured")

        # Fall back to legacy single-server path when no product spec
        if product_spec is None or not product_spec.ftp_servers:
            url = f"{self.ftp_server}{ftp_path}"
            return self.downloader.download(url, destination, file_info)

        # Sort servers by priority (lowest number = highest priority)
        servers = sorted(product_spec.ftp_servers, key=lambda s: s.priority)

        # Filter out auth-required servers when no credentials
        available_servers = []
        skipped_servers = []
        for server in servers:
            if server.requires_auth and self.user_email is None:
                skipped_servers.append(server)
            else:
                available_servers.append(server)

        if not available_servers:
            server_names = ", ".join(s.url for s in skipped_servers)
            raise RuntimeError(
                f"No FTP servers available for {product_spec.prefix}.\n"
                f"All servers require authentication: {server_names}\n"
                f"Set CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL "
                f"in config/.env to enable NASA CDDIS access.\n"
                f"Register at: https://urs.earthdata.nasa.gov/users/new"
            )

        errors: list[str] = []
        for i, server in enumerate(available_servers):
            url = f"{server.url.rstrip('/')}{ftp_path}"
            try:
                result = self.downloader.download(url, destination, file_info)
                if i > 0:
                    # We got here via fallback — log which server succeeded
                    print(
                        f"  ✓ Download succeeded from fallback server: "
                        f"{server.description or server.url}"
                    )
                return result
            except Exception as e:
                if self.downloader._is_network_error(e):
                    raise RuntimeError(
                        "No internet connection detected. "
                        "Please check your network and try again."
                    ) from e

                server_label = server.description or server.url
                error_msg = f"{server_label}: {e!s}"
                errors.append(error_msg)
                print(f"  ⚠ Download failed from {server_label}: {e!s}")

                # Warn about fallback if there are more servers to try
                if i < len(available_servers) - 1:
                    next_server = available_servers[i + 1]
                    next_label = next_server.description or next_server.url
                    print(f"  → Trying fallback server: {next_label}")

        # All servers exhausted
        product_label = f"{product_spec.agency_code}/{product_spec.product_type}"
        error_detail = "\n".join(f"  - {e}" for e in errors)
        if skipped_servers:
            skip_detail = "\n".join(
                f"  - {s.description or s.url} (requires auth)" for s in skipped_servers
            )
            auth_hint = (
                f"\n\nSkipped servers (no credentials):\n{skip_detail}\n"
                f"Set CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL "
                f"in config/.env to enable these servers."
            )
        else:
            auth_hint = ""

        raise RuntimeError(
            f"Failed to download {product_label} from all available servers.\n"
            f"\nFile: {destination.name}\n"
            f"\nServer errors:\n{error_detail}"
            f"{auth_hint}"
        )

    @abstractmethod
    def read_file(self) -> xr.Dataset:
        """Read and parse the auxiliary file.

        Returns
        -------
        xr.Dataset
            Parsed dataset representation of the file.
        """
        pass

    @abstractmethod
    def get_interpolation_strategy(self) -> Interpolator:
        """Get the interpolation strategy for this file type."""
        pass

    def join_days(
        self,
        previous: AuxFile,
        following: AuxFile,
        margin: np.timedelta64 = DAY_JOIN_MARGIN,
    ) -> xr.Dataset:
        """This file's data with the end of the previous and the start of the next day.

        A daily file can end before midnight (e.g. a 15 min orbit file at
        23:45), and its first and last epochs have neighbors on one side
        only. With ``margin`` of the neighboring days on both sides, the
        whole day lies inside the data: nothing is extrapolated.

        Parameters
        ----------
        previous, following : AuxFile
            The same product for the previous and the next day.
        margin : np.timedelta64
            How much of each neighboring day is kept.

        Returns
        -------
        xr.Dataset
            The epochs of this file, plus those of the neighbors within
            ``margin`` of this day that this file lacks (e.g. this file's
            24:00 epoch wins over the next file's 00:00), sorted by epoch.
            Satellites missing in a file are NaN there. Attrs of this file.
        """
        day = self.data
        start = np.datetime64(YYYYDOY.from_str(self.date).date, "ns")
        end = start + np.timedelta64(1, "D")
        before = previous.data.sel(epoch=slice(start - margin, None))
        after = following.data.sel(epoch=slice(None, end + margin))
        parts = [
            part.sel(epoch=~part.epoch.isin(day.epoch.values))
            for part in (before, after)
        ]
        joined = xr.concat(
            [parts[0], day, parts[1]],
            dim="epoch",
            join="outer",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            combine_attrs="override",
        ).sortby("epoch")
        joined.attrs = dict(day.attrs)
        return joined

    @property
    def data(self) -> xr.Dataset:
        """Access the file's data, loading it if necessary."""
        if self._data is None:
            self._data = self.read_file()
            strategy = self.get_interpolation_strategy()
            self._data.attrs["interpolator_config"] = strategy.to_attrs()
        return self._data

    def check_file_exists(self) -> Path:
        """Return the local file, downloading it if needed.

        The candidate names (one per sampling the product has been
        published with) are tried in order: first a local copy of any of
        them, then a download of each in turn.

        Returns
        -------
        Path
            Local file path.

        Raises
        ------
        RuntimeError
            If no candidate could be downloaded; the message names every
            file tried.
        """
        candidates = self.candidate_filenames()
        for name in candidates:
            file_path = self.local_dir / name
            if file_path.exists():
                print(f"File {file_path} exists.")
                return file_path

        errors: list[str] = []
        for name in candidates:
            print(f"File {self.local_dir / name} does not exist. Downloading...")
            try:
                self.download_aux_file(name)
            except RuntimeError as e:
                if "No internet connection" in str(e):
                    raise
                errors.append(f"{name}:\n{e}")
                continue
            return self.local_dir / name

        raise RuntimeError(
            f"No {'/'.join(self.file_type)} file of {self.agency}/"
            f"{self.product_type} for {self.date} could be downloaded. "
            f"Tried {', '.join(candidates)}.\n\n" + "\n\n".join(errors)
        )

    @abstractmethod
    def candidate_filenames(self) -> list[str]:
        """File names of this file, in the order they are tried."""

    @deprecated(
        "AuxFile.generate_filename_based_on_type() is left over from "
        "development and will be removed with the next major version. Use "
        "AuxFile.candidate_filenames() instead: a product can be published "
        "with several samplings."
    )
    def generate_filename_based_on_type(self) -> Path:
        """First candidate file name."""
        return Path(self.candidate_filenames()[0])

    @abstractmethod
    def download_aux_file(self, filename: str) -> None:
        """Download one candidate file into ``local_dir``.

        Parameters
        ----------
        filename : str
            One of :meth:`candidate_filenames`.
        """
