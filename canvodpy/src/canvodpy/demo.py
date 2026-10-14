"""Demo data: one day of the Rosalia site, downloaded on first use.

``demo_data()`` downloads the published archives of one kind of data,
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
``packages/canvod-readers/tests/test_data``. The observations are in
Zenodo record 10.5281/zenodo.23366661, the auxiliary files in
10.5281/zenodo.23366994.
"""

from __future__ import annotations

import hashlib
import http.client
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DemoKind = Literal["rinex", "sbf", "aux"]

DEMO_DATA_VERSION = "1"

# Attempts per download; Zenodo sometimes drops a connection mid-file.
DOWNLOAD_ATTEMPTS = 5
"""Folder name under the cache; raise it when the archives change."""


@dataclass(frozen=True)
class DemoArchive:
    """One published zip of demo data.

    Attributes
    ----------
    name : str
        File name of the zip, also its name on Zenodo.
    kind : str
        The ``kind`` of ``demo_data()`` that downloads it.
    url : str or None
        Download URL; None while the archive is not published.
    md5 : str
        md5 of the zip, as Zenodo shows it.
    members : tuple[str, ...]
        Glob patterns of the files it holds, relative to the test data
        folder ``valid/``; used to build the zip.
    """

    name: str
    kind: str
    url: str | None
    md5: str
    members: tuple[str, ...]


_RINEX = "rinex_v3_04/01_Rosalia/{receiver}/01_GNSS/01_raw/25001/{prefix}_R_2025001????_15M_05S_AA.rnx"
_SBF = "sbf/01_Rosalia/{receiver}/25001/{prefix}_R_20250010[01]??_15M_05S_AA.sbf"

ARCHIVES: tuple[DemoArchive, ...] = (
    DemoArchive(
        name="canvodpy-demo-rinex-canopy.zip",
        kind="rinex",
        url="https://zenodo.org/records/23366661/files/canvodpy-demo-rinex-canopy.zip?download=1",
        md5="b10ea0231d71c871b9566010029cc598",
        members=(_RINEX.format(receiver="02_canopy", prefix="ROSA01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-rinex-reference.zip",
        kind="rinex",
        url="https://zenodo.org/records/23366661/files/canvodpy-demo-rinex-reference.zip?download=1",
        md5="727c34442c622ac1db315ecae5b51556",
        members=(_RINEX.format(receiver="01_reference", prefix="ROSR01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-sbf-canopy.zip",
        kind="sbf",
        url="https://zenodo.org/records/23366661/files/canvodpy-demo-sbf-canopy.zip?download=1",
        md5="32c5e72cbe1aef639997862bdf1b6fc9",
        members=(_SBF.format(receiver="02_canopy", prefix="ROSA01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-sbf-reference.zip",
        kind="sbf",
        url="https://zenodo.org/records/23366661/files/canvodpy-demo-sbf-reference.zip?download=1",
        md5="c92b99639337322427954c4c29d719ab",
        members=(_SBF.format(receiver="01_reference", prefix="ROSR01TUW"),),
    ),
    DemoArchive(
        name="canvodpy-demo-aux.zip",
        kind="aux",
        url="https://zenodo.org/records/23366994/files/canvodpy-demo-aux.zip?download=1",
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


def demo_data(kind: DemoKind, *, cache_dir: Path | None = None) -> Path:
    """Download and unpack one kind of demo data.

    Parameters
    ----------
    kind : {"rinex", "sbf", "aux"}
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
        The same folder for every kind.

    Raises
    ------
    ValueError
        If ``kind`` is not one of the known ones.
    RuntimeError
        If an archive is not published yet, can't be downloaded, or its
        md5 doesn't match.

    Examples
    --------
    >>> from canvodpy import demo_data
    >>> root = demo_data("rinex")  # doctest: +SKIP
    """
    archives = [a for a in ARCHIVES if a.kind == kind]
    if not archives:
        known = ", ".join(repr(t) for t in sorted({a.kind for a in ARCHIVES}))
        msg = f"Unknown kind of demo data {kind!r}; known: {known}"
        raise ValueError(msg)

    root = Path(cache_dir or default_cache_dir()) / DEMO_DATA_VERSION
    for archive in archives:
        _ensure(archive, root)
    return root


def _download(url: str, path: Path) -> None:
    """Download *url* to *path*, continuing after a broken connection.

    The bytes received so far are kept in ``<path>.part``; each attempt
    asks for the rest (an HTTP Range request, which Zenodo answers), also
    in a later call after this one gave up.

    Raises
    ------
    OSError
        If the download is still incomplete after the last attempt (the
        error of that attempt).
    """
    part = path.with_name(path.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    error: OSError | None = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        if attempt:
            time.sleep(min(2**attempt, 30))
        have = part.stat().st_size if part.exists() else 0
        request = urllib.request.Request(url)
        if have:
            request.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206:
                    have = 0  # the server sends the whole file again
                total = _total_size(response, have)
                with part.open("ab" if have else "wb") as f:
                    shutil.copyfileobj(response, f, 1 << 20)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise  # not found, or not allowed: trying again won't help
            error = e
            continue
        except (OSError, http.client.HTTPException) as e:
            error = e if isinstance(e, OSError) else OSError(str(e))
            continue
        if total is None or part.stat().st_size == total:
            part.replace(path)
            return
        error = OSError(f"got {part.stat().st_size} of {total} bytes")
    assert error is not None
    raise error


def _total_size(response: http.client.HTTPResponse, start: int) -> int | None:
    """The size of the whole file, from the headers of *response*."""
    if content_range := response.headers.get("Content-Range"):
        return int(content_range.rsplit("/", 1)[1])
    if length := response.headers.get("Content-Length"):
        return start + int(length)
    return None


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
        _download(archive.url, zip_path)
    except OSError as e:
        msg = (
            f"Could not download demo archive {archive.name} from "
            f"{archive.url}: {e}. Check the connection and try again; a new "
            "attempt continues where this one stopped."
        )
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
