"""Virtual renaming engine: map physical files to canVOD conventional names.

The ``FilenameMapper`` discovers files on disk according to the configured
directory layout and source pattern, then wraps each in a ``VirtualFile``
that pairs the physical path with its canVOD conventional name.

.. deprecated::
    ``FilenameMapper`` is left over from development and will be removed
    with the next major version. Naming recipes (``canvod-filemap``) map
    non-canonical filenames, and ``canvodpy run`` finds the files in any
    folder layout (:mod:`canvodpy.orchestrator.discovery`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from natsort import natsorted

from canvod.utils.tools import deprecated

from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig
from .convention import (
    CanVODFilename,
    FileType,
    ReceiverType,
    find_overlaps,
    known_file_types,
)
from .patterns import (
    BUILTIN_PATTERNS,
    auto_match_order,
    hour_letter_to_int,
    match_pattern,
    resolve_year_from_yy,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VirtualFile:
    """Physical file mapped to its canVOD conventional name."""

    physical_path: Path
    conventional_name: CanVODFilename

    @property
    def canonical_str(self) -> str:
        """The conventional filename as a string."""
        return self.conventional_name.name

    def open(self, mode: str = "rb"):
        """Open the physical file."""
        return self.physical_path.open(mode)


# -- Extension → FileType mapping --------------------------------------------

_EXT_TO_FILETYPE: dict[str, FileType] = {
    ".rnx": FileType.RNX,
    ".crx": FileType.RNX,
    ".sbf": FileType.SBF,
    ".ubx": FileType.UBX,
    ".nmea": FileType.NMEA,
    ".obs": FileType.RNX,
}

_RNX2_OBS_CHARS = set("oOdD")
_COMPRESSION_EXTS = {".zip", ".gz", ".bz2", ".zst", ".Z"}


def _detect_file_type(path: Path) -> tuple[str, str | None]:
    """Detect the file type and compression from a file path."""
    suffixes = path.suffixes
    compression = None

    if suffixes and suffixes[-1] in _COMPRESSION_EXTS:
        compression = suffixes[-1].lstrip(".")
        suffixes = suffixes[:-1]

    if not suffixes:
        stem = path.stem if compression else path.name
        if stem.endswith("_"):
            return FileType.SBF, compression
        raise ValueError(f"Cannot detect file type for {path.name}")

    ext = suffixes[-1].lower()

    if ext in _EXT_TO_FILETYPE:
        return _EXT_TO_FILETYPE[ext], compression

    if ext[1:] in known_file_types():
        return ext[1:], compression

    if len(ext) == 4 and ext[1:3].isdigit():
        type_char = ext[3]
        if type_char in _RNX2_OBS_CHARS:
            return FileType.RNX, compression

    if ext.endswith("_") and len(ext) == 4 and ext[1:3].isdigit():
        return FileType.SBF, compression

    raise ValueError(f"Cannot detect file type for {path.name}")


@deprecated(
    "FilenameMapper is left over from development and will be removed with the next major version. "
    "Use a naming recipe (the receiver setting 'recipe', see canvod-filemap) instead; canvodpy run finds the files in any folder layout."
)
class FilenameMapper:
    """Maps physical files to canVOD conventional names.

    Parameters
    ----------
    site_naming
        Site-level naming config.
    receiver_naming
        Receiver-level naming config.
    receiver_type
        Whether this receiver is ``"reference"`` or ``"canopy"``.
    receiver_base_dir
        Absolute path to the receiver's data directory.
    """

    def __init__(
        self,
        site_naming: SiteNamingConfig,
        receiver_naming: ReceiverNamingConfig,
        receiver_type: Literal["reference", "canopy"],
        receiver_base_dir: Path,
    ) -> None:
        self.site_naming = site_naming
        self.receiver_naming = receiver_naming
        self.receiver_type_str = receiver_type
        self.receiver_base_dir = receiver_base_dir

        self._rx_type = (
            ReceiverType.REFERENCE
            if receiver_type == "reference"
            else ReceiverType.ACTIVE
        )

    def discover_all(self) -> list[VirtualFile]:
        """Discover all files and map them to conventional names."""
        files = self._discover_files()
        results = []
        for path in natsorted(files, key=lambda p: p.name):
            try:
                vf = self.map_single_file(path)
                results.append(vf)
            except ValueError, KeyError:
                logger.warning("Could not map %s; skipping", path.name)
                continue
        return results

    def discover_for_date(self, year: int, doy: int) -> list[VirtualFile]:
        """Discover files for a specific date."""
        layout = self.receiver_naming.directory_layout

        if layout == DirectoryLayout.YYDDD_SUBDIRS:
            yy = year % 100
            dir_name = f"{yy:02d}{doy:03d}"
            search_dir = self.receiver_base_dir / dir_name
        elif layout == DirectoryLayout.YYYYDDD_SUBDIRS:
            dir_name = f"{year:04d}{doy:03d}"
            search_dir = self.receiver_base_dir / dir_name
        else:
            all_files = self.discover_all()
            return [
                vf
                for vf in all_files
                if vf.conventional_name.year == year and vf.conventional_name.doy == doy
            ]

        if not search_dir.is_dir():
            return []

        files = self._glob_in_dir(search_dir)
        results = []
        for path in natsorted(files, key=lambda p: p.name):
            try:
                vf = self.map_single_file(path, year=year, doy=doy)
                results.append(vf)
            except ValueError, KeyError:
                logger.warning("Could not map %s; skipping", path.name)
                continue
        return results

    def map_single_file(
        self, file_path: Path, *, year: int | None = None, doy: int | None = None
    ) -> VirtualFile:
        """Map a single physical file to its canVOD conventional name.

        Raises
        ------
        ValueError
            If the file cannot be matched or mapped.
        """
        filename = file_path.name
        pattern_name = self.receiver_naming.source_pattern

        result = match_pattern(filename, pattern_name)
        if result is None:
            raise ValueError(f"No pattern matched for {filename!r}")

        pat, m = result
        groups = m.groupdict()

        expected_station = self.receiver_naming.source_station
        if expected_station and "station" in groups:
            actual_station = groups["station"]
            if actual_station.lower() != expected_station.lower():
                raise ValueError(
                    f"Station code mismatch for {filename!r}: "
                    f"expected {expected_station!r}, got {actual_station!r}"
                )

        if year is None:
            if "year" in groups and groups["year"] is not None:
                year = int(groups["year"])
            elif "yy" in groups and groups["yy"] is not None:
                year = resolve_year_from_yy(int(groups["yy"]))
            else:
                raise ValueError(f"Cannot determine year from {filename!r}")

        if doy is None:
            if "doy" in groups and groups["doy"] is not None:
                doy = int(groups["doy"])
            else:
                raise ValueError(f"Cannot determine DOY from {filename!r}")

        if "hour" in groups and groups["hour"] is not None:
            hour = int(groups["hour"])
        elif "hour_letter" in groups and groups["hour_letter"] is not None:
            hour = hour_letter_to_int(groups["hour_letter"])
        else:
            hour = 0

        if "minute" in groups and groups["minute"] is not None:
            minute = int(groups["minute"])
        else:
            minute = 0

        sampling = (
            groups.get("sampling")
            or self.receiver_naming.sampling
            or self.site_naming.default_sampling
        )
        period = groups.get("period")
        if not period:
            hour_letter = groups.get("hour_letter")
            if hour_letter == "0" and hour == 0 and minute == 0:
                period = "01D"
            else:
                period = self.receiver_naming.period or self.site_naming.default_period

        content = self.receiver_naming.content or self.site_naming.default_content
        agency = self.receiver_naming.agency or self.site_naming.agency
        file_type, compression = _detect_file_type(file_path)

        conventional = CanVODFilename(
            site=self.site_naming.site_id,
            receiver_type=self._rx_type,
            receiver_number=self.receiver_naming.receiver_number,
            agency=agency,
            year=year,
            doy=doy,
            hour=hour,
            minute=minute,
            period=period,
            sampling=sampling,
            content=content,
            file_type=file_type,
            compression=compression,
        )

        return VirtualFile(physical_path=file_path, conventional_name=conventional)

    @staticmethod
    def detect_overlaps(
        vfs: list[VirtualFile],
    ) -> list[tuple[VirtualFile, VirtualFile]]:
        """Detect pairs of files whose named time spans overlap.

        See :func:`canvod.preflight.convention.find_overlaps`.
        """
        return find_overlaps(vfs, key=lambda vf: vf.conventional_name)

    # -- Private helpers ------------------------------------------------------

    def _discover_files(self) -> list[Path]:
        """Discover all data files according to directory layout."""
        layout = self.receiver_naming.directory_layout

        if layout == DirectoryLayout.FLAT:
            return self._glob_in_dir(self.receiver_base_dir)

        if not self.receiver_base_dir.is_dir():
            return []

        if layout == DirectoryLayout.YYDDD_SUBDIRS:
            dir_pattern = re.compile(r"^\d{5}$")
        else:
            dir_pattern = re.compile(r"^\d{7}$")

        files: list[Path] = []
        for subdir in sorted(self.receiver_base_dir.iterdir()):
            if subdir.is_dir() and dir_pattern.match(subdir.name):
                files.extend(self._glob_in_dir(subdir))
        return files

    def _glob_in_dir(self, directory: Path) -> list[Path]:
        """Glob for data files in a directory using the source pattern's globs."""
        pattern_name = self.receiver_naming.source_pattern

        if pattern_name == "auto":
            globs: set[str] = set()
            for name in auto_match_order():
                globs.update(BUILTIN_PATTERNS[name].file_globs)
        else:
            globs = set(BUILTIN_PATTERNS[pattern_name].file_globs)

        files: list[Path] = []
        seen: set[Path] = set()
        for g in sorted(globs):
            for path in directory.glob(g):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    files.append(path)
        return files
