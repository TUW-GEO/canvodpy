"""Demo data: one day of the Rosalia site, downloaded on first use.

``demo_data()`` downloads the published archives of one file type,
checks each archive's md5, unpacks it into a cache folder and returns
that folder. The folder has the layout of the test data, so the demo
notebooks and the tests find the files at the same relative paths. A
second call finds the data in the cache and downloads nothing.

The archives (ADR 0017):

- RINEX v3.04, the whole of 2025-01-01, canopy and reference receiver;
- SBF, 00:00 to 02:00 of 2025-01-01, canopy and reference receiver;
- auxiliary files: SP3 orbits and CLK clocks of 2024-12-31 to 2025-01-02
  and the auxiliary store of 2025-01-01.

``ARCHIVES`` is the single list of what each archive holds;
``just demo-archives`` builds the zips from it. The md5 values are those
of zips built from the test data at commit 077aa69 of
``packages/canvod-readers/tests/test_data``. The URLs are set once the
Zenodo records are published.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from canvod.auxiliary.core.downloader import FtpDownloader

DemoFileType = Literal["rinex", "sbf", "aux"]

DEMO_DATA_VERSION = "1"
"""Folder name under the cache; raise it when the archives change."""


@dataclass(frozen=True)
class DemoArchive:
    """One published zip of demo data.

    Attributes
    ----------
    name : str
        File name of the zip, also its name on Zenodo.
    file_type : str
        The ``file_type`` of ``demo_data()`` that downloads it.
    url : str or None
        Download URL; None while the archive is not published.
    md5 : str
        md5 of the zip, as Zenodo shows it.
    members : tuple[str, ...]
        Glob patterns of the files it holds, relative to the test data
        folder ``valid/``; used to build the zip.
    """

    name: str
    file_type: str
    url: str | None
    md5: str
    members: tuple[str, ...]


_RINEX = "rinex_v3_04/01_Rosalia/{receiver}/01_GNSS/01_raw/25001/{prefix}_R_2025001????_15M_05S_AA.rnx"
_SBF = "sbf/01_Rosalia/{receiver}/25001/{prefix}_R_20250010[01]??_15M_05S_AA.sbf"

ARCHIVES: tuple[DemoArchive, ...] = (
    DemoArchive(
        name="canvodpy-demo-rinex-canopy.zip",
        file_type="rinex",
        url=None,
        md5="b10ea0231d71c871b9566010029cc598",
        members=(_RINEX.format(receiver="02_canopy", prefix="ROSA01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-rinex-reference.zip",
        file_type="rinex",
        url=None,
        md5="727c34442c622ac1db315ecae5b51556",
        members=(_RINEX.format(receiver="01_reference", prefix="ROSR01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-sbf-canopy.zip",
        file_type="sbf",
        url=None,
        md5="32c5e72cbe1aef639997862bdf1b6fc9",
        members=(_SBF.format(receiver="02_canopy", prefix="ROSA01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-sbf-reference.zip",
        file_type="sbf",
        url=None,
        md5="c92b99639337322427954c4c29d719ab",
        members=(_SBF.format(receiver="01_reference", prefix="ROSR01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-aux.zip",
        file_type="aux",
        url=None,
        md5="f38bddf8972f9d1ebf3565688e3a6a48",
        members=(
            "aux_data/01_SP3/COD0MGXFIN_*_01D_05M_ORB.SP3",
            "aux_data/02_CLK/COD0MGXFIN_*_01D_30S_CLK.CLK",
            "aux_data/aux_2025001.zarr/**/*",
        ),
    ),
)


def default_cache_dir() -> Path:
    """Return the user cache folder of canvodpy (platform specific)."""
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("canvodpy")) / "demo"


def demo_data(file_type: DemoFileType, *, cache_dir: Path | None = None) -> Path:
    """Download and unpack the demo data of one file type.

    Parameters
    ----------
    file_type : {"rinex", "sbf", "aux"}
        ``"rinex"``: RINEX v3.04 of both receivers, the whole day.
        ``"sbf"``: SBF of both receivers, 00:00 to 02:00.
        ``"aux"``: SP3 and CLK files and the auxiliary store.
    cache_dir : Path, optional
        Where to keep the data. Default: the user cache folder of
        canvodpy (``default_cache_dir()``).

    Returns
    -------
    Path
        The folder that holds the files, in the layout of the test data,
        for example ``<folder>/rinex_v3_04/01_Rosalia/02_canopy/...``.
        The same folder for every file type.

    Raises
    ------
    ValueError
        If ``file_type`` is not one of the known ones.
    RuntimeError
        If an archive is not published yet, can't be downloaded, or its
        md5 doesn't match.

    Examples
    --------
    >>> from canvodpy import demo_data
    >>> root = demo_data("rinex")  # doctest: +SKIP
    """
    archives = [a for a in ARCHIVES if a.file_type == file_type]
    if not archives:
        known = ", ".join(repr(t) for t in sorted({a.file_type for a in ARCHIVES}))
        msg = f"Unknown demo file type {file_type!r}; known: {known}"
        raise ValueError(msg)

    root = Path(cache_dir or default_cache_dir()) / DEMO_DATA_VERSION
    for archive in archives:
        _ensure(archive, root)
    return root


def _ensure(archive: DemoArchive, root: Path) -> None:
    """Download, check and unpack one archive, unless it is in the cache."""
    marker = root / f".{archive.name}.md5"
    if marker.exists() and marker.read_text().strip() == archive.md5:
        return
    if archive.url is None:
        msg = f"Demo archive {archive.name} is not published yet"
        raise RuntimeError(msg)

    zip_path = root / ".downloads" / archive.name
    try:
        FtpDownloader(alt_servers=[]).download(archive.url, zip_path)
    except RuntimeError as e:
        msg = f"Could not download demo archive {archive.name} from {archive.url}"
        raise RuntimeError(msg) from e

    try:
        with zip_path.open("rb") as f:
            md5 = hashlib.file_digest(f, "md5").hexdigest()
        if md5 != archive.md5:
            msg = (
                f"Demo archive {archive.name} has md5 {md5}, expected "
                f"{archive.md5}; it was not unpacked"
            )
            raise RuntimeError(msg)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(root)
    finally:
        zip_path.unlink(missing_ok=True)
    marker.write_text(archive.md5)
