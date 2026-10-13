"""GNSS data-file discovery shared by the pipeline run and its dry-run preview.

One code path decides which files of a receiver are processed for a day, so
``canvodpy run --dry-run`` reports exactly the files a real run would ingest.

Each receiver's configured ``directory`` is scanned recursively once per run.
Hidden directories are skipped and symbolic links are not followed. A file's
day comes from the date in its (canonical) name, not from the folder it sits
in, so any folder layout works: all files in one folder, one folder per day
(``YYDDD`` or ``YYYYDDD``), or deeper nesting. A file belongs to the day it
starts on.

Which files count:

1. **Recipe** -- when the receiver config sets ``recipe:``, the naming recipe
   (``canvod-filemap``) selects the files and maps each to its canonical
   canVOD name. This is the only way non-canonical filenames are processed,
   and the recipe sets the receiver identity (e.g. ``ROSA01TUW``).
2. **Canonical convention** -- otherwise, only files whose names follow the
   canVOD naming convention (``canvod-preflight``) are processed, restricted
   by ``reader_format``. Whether ``canvod-filemap`` is installed does not
   change this.

Compressed files (gzip, zip and the like, and Hatanaka-compressed RINEX:
``.crx``, RINEX 2 ``.yyd``) are never selected, with or without a recipe,
because the readers do not decompress. They are reported apart from the
other files a run skips (:func:`is_compressed`).

Each receiver needs its own directory: a directory whose canonical files
belong to more than one receiver identity is an error, and so are two files
that map to the same canonical name and two files of the same type whose
named time spans overlap (e.g. a daily file next to the 15-minute files of
the same day).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any

from natsort import natsorted

#: Suffixes of general-purpose compression, compared in lower case.
COMPRESSION_SUFFIXES = frozenset(
    {".gz", ".z", ".zip", ".bz2", ".xz", ".zst", ".7z", ".tgz", ".tar", ".rar"}
)
#: Hatanaka-compressed RINEX: ``.crx`` (RINEX 3/4), ``.yyd`` (RINEX 2).
_HATANAKA = re.compile(r"\.(?:crx|\d{2}d)$", re.IGNORECASE)


def is_compressed(path: Path) -> bool:
    """``True`` if ``path`` is a compressed file the readers cannot read.

    Covers general-purpose compression (``.gz``, ``.Z``, ``.zip``, ...) and
    Hatanaka-compressed RINEX observations (``.crx``, RINEX 2 ``.yyd``).
    """
    return path.suffix.lower() in COMPRESSION_SUFFIXES or bool(
        _HATANAKA.search(path.name)
    )


@dataclass(frozen=True)
class DiscoveredFile:
    """One GNSS data file selected for processing."""

    path: Path
    canonical_name: str


def parse_sampling_interval_from_filename(filename: str) -> float | None:
    """Sampling interval from the data-frequency field of a RINEX v3 long name.

    E.g. ``ROSA01TUW_R_20250020000_01D_05S_AA.rnx``: ``05S`` is 5 s
    (RINEX 3.04, Section 4: units S, M, H, D, Z for hertz, C for 100 Hz,
    U for unspecified).

    Parameters
    ----------
    filename : str
        File name (stem or full name).

    Returns
    -------
    float or None
        Sampling interval in seconds, or ``None`` if the name has no
        data-frequency field or its unit is C or U (the caller then reads
        the interval from the data).
    """
    import re

    parts = Path(filename).stem.split("_")
    if len(parts) >= 5:
        m = re.match(r"^(\d+)([SMHDZC])$", parts[4])
        if m:
            value, unit = int(m.group(1)), m.group(2)
            multipliers = {"S": 1, "M": 60, "H": 3600, "D": 86400}
            if unit == "Z":  # Hz -> seconds
                return 1.0 / value if value else None
            if unit in multipliers:
                return float(value * multipliers[unit])
    return None


@dataclass(frozen=True)
class ReceiverDay:
    """One receiver's data for one day, the unit a run processes.

    Parameters
    ----------
    receiver : str
        Receiver name in the site configuration.
    directory : Path
        The receiver's configured data directory (any layout below it).
    yyyydoy : str
        Day in ``YYYYDOY`` format.
    recipe : Path | None
        The receiver's naming recipe file, if it has one (see
        :func:`recipe_file`).
    """

    receiver: str
    directory: Path
    yyyydoy: str
    recipe: Path | None = None

    def __str__(self) -> str:
        return f"{self.receiver} {self.yyyydoy} ({self.directory})"


class DiscoveryError(ValueError):
    """A receiver directory's files cannot be assigned unambiguously."""


FILEMAP_INSTALL_HINT = (
    "Install it in the canvodpy repository with: uv sync --group filemap; "
    "elsewhere from GitHub, see "
    "https://extensions.canvodpy.eu/packages/filemap/overview/"
)


def canonical_name_for(path: Path | str) -> str:
    """Return the canonical canVOD filename for ``path``, or ``""``.

    The physical filename is parsed against the canVOD naming convention;
    a name that does not follow it yields ``""``.
    """
    from canvod.preflight.convention import CanVODFilename

    try:
        return CanVODFilename.from_filename(Path(path).name).name
    except ValueError:
        return ""


def recipe_file(site: str, recipe: str | None) -> Path | None:
    """The naming recipe file of a receiver of ``site``.

    Recipes are read from ``<config dir>/recipes/<site>/<recipe>.yaml``, in
    the configuration directory the settings file is read from
    (:func:`canvod.config.loader.get_default_config_dir`). The lookup itself
    is :func:`canvod.filemap.find_recipe`.

    Parameters
    ----------
    site : str
        Site name in the settings file.
    recipe : str | None
        The receiver's ``recipe:`` setting.

    Returns
    -------
    Path | None
        The recipe file, ``None`` if the receiver has no recipe.

    Raises
    ------
    DiscoveryError
        If canvod-filemap is not installed or the recipe file does not exist.
    """
    if not recipe:
        return None
    from canvod.config.loader import get_default_config_dir

    try:
        from canvod.filemap import RecipeNotFoundError, find_recipe
    except ImportError as exc:
        msg = (
            f"Recipe '{recipe}' requires canvod-filemap, but it is not "
            f"installed. {FILEMAP_INSTALL_HINT}"
        )
        raise DiscoveryError(msg) from exc
    try:
        return find_recipe(get_default_config_dir(), site, recipe)
    except RecipeNotFoundError as exc:
        msg = f"{exc}\nCreate it with: just naming-init {site} {recipe}"
        raise DiscoveryError(msg) from exc


@lru_cache(maxsize=32)
def _load_recipe(recipe_path: Path) -> Any:
    from canvod.filemap.recipe import NamingRecipe

    return NamingRecipe.load(recipe_path)


#: File types each built-in reader format reads (``None``/``"auto"``: all of
#: them); a reader plugin reads its reader's ``file_type``. RINEX 2 and 3
#: share the canonical type ``rnx``; the header tells them apart.
_READER_FILE_TYPES: dict[str | None, frozenset[str]] = {
    "sbf": frozenset({"sbf"}),
    "rinex3": frozenset({"rnx"}),
    "rinex3_stripped": frozenset({"rnx"}),
    "rinex2": frozenset({"rnx"}),
    "rinex": frozenset({"rnx"}),
    "nmea": frozenset({"nmea"}),
}
_ALL_FILE_TYPES = frozenset({"rnx", "sbf", "nmea"})

#: Reader format of each canonical file type that needs no look inside.
_FORMAT_OF_FILE_TYPE = {"sbf": "sbf", "nmea": "nmea"}


def _receiver_identity(cfg: dict[str, Any], base_path: Path, site: str) -> str | None:
    """Canonical receiver identity (e.g. ``ROSA01TUW``) of one receiver.

    Taken from the receiver's recipe if it has one, otherwise from the
    canonical names of the files in its directory (``None`` if it has none).
    """
    path = recipe_file(site, cfg.get("recipe"))
    if path is not None:
        recipe = _load_recipe(path)
        role = "R" if recipe.receiver_type == "reference" else "A"
        return f"{recipe.site}{role}{recipe.receiver_number:02d}{recipe.agency}"
    try:
        return _scan_directory(base_path / cfg["directory"], None).identity
    except DiscoveryError:
        return None  # reported when the receiver's files are read


def check_receivers(
    receivers: dict[str, dict[str, Any]], base_path: Path, site: str
) -> None:
    """Check that the files of each receiver can be told apart.

    The canonical name of a file starts with the receiver identity (site,
    role, receiver number, agency, e.g. ``ROSA01TUW``). A receiver's identity
    comes from its naming recipe if it has one, otherwise from the canonical
    names of its files. Two receivers with the same identity cannot be told
    apart in the store, and an identity whose role (``R`` reference, ``A``
    canopy) differs from the receiver's configured type would label the
    files with the wrong role.

    Parameters
    ----------
    receivers : dict[str, dict]
        Receiver name to receiver configuration (``type``, ``directory``,
        ``recipe``).
    base_path : Path
        The site's data root, which receiver directories are relative to.
    site : str
        Site name in the settings file, which selects the recipe folder.

    Raises
    ------
    DiscoveryError
        Listing every problem found, or if a receiver's directory or recipe
        cannot be read (see :func:`receiver_days`).
    """
    recipe_receivers = [name for name, cfg in receivers.items() if cfg.get("recipe")]
    if recipe_receivers:
        try:
            import canvod.filemap  # noqa: F401
        except ImportError as exc:
            msg = (
                f"Receiver(s) {', '.join(recipe_receivers)} use a naming recipe, "
                f"which requires canvod-filemap, but it is not installed. "
                f"{FILEMAP_INSTALL_HINT}"
            )
            raise DiscoveryError(msg) from exc

    owner: dict[str, str] = {}
    problems: list[str] = []
    for name, cfg in receivers.items():
        identity = _receiver_identity(cfg, base_path, site)
        if identity is None:
            continue
        source = f"its recipe '{cfg['recipe']}'" if cfg.get("recipe") else "its files"
        expected_role = "R" if cfg.get("type") == "reference" else "A"
        if identity[3] != expected_role:
            problems.append(
                f"Receiver '{name}' is configured as '{cfg.get('type')}', but "
                f"{source} name it {identity}, the identity of a "
                f"{'reference' if identity[3] == 'R' else 'canopy'} receiver."
            )
        if identity in owner:
            problems.append(
                f"Receivers '{owner[identity]}' and '{name}' both get canonical "
                f"names starting with {identity}. Give each receiver its own "
                f"directory, and each receiver with a recipe its own "
                f"receiver_number."
            )
        else:
            owner[identity] = name
    if problems:
        msg = "Receiver identity problems:\n  - " + "\n  - ".join(problems)
        raise DiscoveryError(msg)


def _canonical_file(path: Path, file_types: frozenset[str]) -> DiscoveredFile | None:
    """``path`` as a discovered file if its name follows the convention."""
    from canvod.preflight.convention import CanVODFilename

    try:
        parsed = CanVODFilename.from_filename(path.name)
    except ValueError:
        return None
    if parsed.compression is not None or parsed.file_type not in file_types:
        return None
    return DiscoveredFile(path=path, canonical_name=parsed.name)


def _recipe_file(path: Path, naming_recipe: Any) -> DiscoveredFile | None:
    """``path`` as a discovered file if the recipe recognizes its name."""
    if not fnmatch(path.name, naming_recipe.glob) or not naming_recipe.matches(
        path.name
    ):
        return None
    return DiscoveredFile(
        path=path, canonical_name=naming_recipe.to_virtual_file(path).canonical_str
    )


@dataclass(frozen=True)
class DirectoryScan:
    """The files found in one receiver directory.

    Attributes
    ----------
    days : dict[str, tuple[DiscoveredFile, ...]]
        Day (``YYYYDOY``) to the files starting on it, naturally sorted.
    identity : str | None
        Receiver identity of the files (e.g. ``ROSA01TUW``), ``None`` if
        there are none.
    unrecognized : tuple[Path, ...]
        Files neither the recipe nor the naming convention recognizes, and
        which are therefore never processed.
    compressed : tuple[Path, ...]
        Compressed files (:func:`is_compressed`), never processed.
    """

    days: dict[str, tuple[DiscoveredFile, ...]]
    identity: str | None
    unrecognized: tuple[Path, ...]
    compressed: tuple[Path, ...] = ()


def scan_directory(directory: Path, recipe: Path | None = None) -> DirectoryScan:
    """Scan a receiver directory as a run does.

    Cached for the run; :func:`clear_discovery_cache` forgets the result so
    a new run sees files added since.

    Raises
    ------
    DiscoveryError
        If the files cannot be assigned unambiguously (see the module
        docstring), or if the recipe file does not exist.
    """
    return _scan_directory(Path(directory), recipe)


@lru_cache(maxsize=64)
def _scan_directory(directory: Path, recipe: Path | None) -> DirectoryScan:
    from canvod.preflight.convention import CanVODFilename, find_overlaps

    try:
        naming_recipe = _load_recipe(recipe) if recipe else None
    except (FileNotFoundError, ImportError) as exc:
        raise DiscoveryError(str(exc)) from exc
    from canvod.preflight.convention import known_file_types

    found: list[DiscoveredFile] = []
    unrecognized: list[Path] = []
    compressed: list[Path] = []
    if directory.is_dir():
        for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                path = Path(dirpath) / name
                if is_compressed(path):
                    compressed.append(path)
                    continue
                discovered = (
                    _recipe_file(path, naming_recipe)
                    if naming_recipe is not None
                    else _canonical_file(path, known_file_types())
                )
                if discovered is not None:
                    found.append(discovered)
                else:
                    unrecognized.append(path)

    by_name: dict[str, list[Path]] = defaultdict(list)
    for f in found:
        by_name[f.canonical_name].append(f.path)
    duplicates = {n: p for n, p in by_name.items() if len(p) > 1}
    if duplicates:
        lines = [
            f"{name}: " + ", ".join(str(p) for p in natsorted(paths))
            for name, paths in sorted(duplicates.items())[:5]
        ]
        msg = (
            f"In {directory}, several files map to the same canonical name, so "
            f"it is unclear which one to process:\n  - " + "\n  - ".join(lines)
        )
        raise DiscoveryError(msg)

    identities = sorted({f.canonical_name[:9] for f in found})
    if len(identities) > 1:
        msg = (
            f"{directory} contains files of {len(identities)} receivers "
            f"({', '.join(identities)}). Give each receiver its own directory."
        )
        raise DiscoveryError(msg)

    parsed_names = {
        f.canonical_name: CanVODFilename.from_filename(f.canonical_name) for f in found
    }
    overlaps = find_overlaps(found, key=lambda f: parsed_names[f.canonical_name])
    if overlaps:
        lines = [f"{a.path} overlaps {b.path}" for a, b in overlaps[:5]]
        if len(overlaps) > 5:
            lines.append(f"... and {len(overlaps) - 5} more")
        msg = (
            f"In {directory}, {len(overlaps)} pair(s) of files cover the same "
            f"time according to their names, so that data would be read "
            f"twice:\n  - " + "\n  - ".join(lines) + "\nKeep one file of each "
            "pair in the receiver directory, for example either the daily file "
            "or the 15-minute files of a day, not both."
        )
        raise DiscoveryError(msg)

    by_day: dict[str, list[DiscoveredFile]] = defaultdict(list)
    for f in found:
        parsed = parsed_names[f.canonical_name]
        by_day[f"{parsed.year:04d}{parsed.doy:03d}"].append(f)
    return DirectoryScan(
        days={
            day: tuple(natsorted(files, key=lambda d: str(d.path)))
            for day, files in by_day.items()
        },
        identity=identities[0] if identities else None,
        unrecognized=tuple(natsorted(unrecognized, key=str)),
        compressed=tuple(natsorted(compressed, key=str)),
    )


def clear_discovery_cache() -> None:
    """Forget the scanned directories, so the next lookup rescans them."""
    _scan_directory.cache_clear()


def _of_format(
    files: tuple[DiscoveredFile, ...], reader_format: str | None, recipe: Path | None
) -> list[DiscoveredFile]:
    if recipe:  # the recipe's file_type already selects the files
        return list(files)
    file_types = _file_types(reader_format)
    return [f for f in files if Path(f.canonical_name).suffix[1:] in file_types]


def _file_types(reader_format: str | None) -> frozenset[str]:
    """File types ``reader_format`` reads; ``auto`` never picks a plugin."""
    if reader_format in (None, "auto"):
        return _ALL_FILE_TYPES
    if reader_format in _READER_FILE_TYPES:
        return _READER_FILE_TYPES[reader_format]
    from canvodpy.factories import ReaderFactory

    return frozenset({ReaderFactory.component_class(reader_format).file_type})


def receiver_days(
    receiver: str,
    directory: Path,
    reader_format: str | None = None,
    recipe: Path | None = None,
) -> list[ReceiverDay]:
    """All days for which ``directory`` holds files of the receiver, sorted."""
    index = _scan_directory(Path(directory), recipe).days
    return [
        ReceiverDay(receiver, Path(directory), day, recipe)
        for day in sorted(index)
        if _of_format(index[day], reader_format, recipe)
    ]


def discover_files(
    day: ReceiverDay, reader_format: str | None = None
) -> list[DiscoveredFile]:
    """Select the GNSS data files that a run processes for ``day``.

    Parameters
    ----------
    day : ReceiverDay
        Receiver, its directory, the day and its recipe.
    reader_format : str | None
        Receiver reader format (``"rinex3"``, ``"rinex"``, ``"sbf"``, or
        ``None``/``"auto"`` for all recognized types). Ignored with a recipe,
        whose ``file_type`` selects the files.

    Returns
    -------
    list[DiscoveredFile]
        Naturally sorted by physical path.
    """
    index = _scan_directory(Path(day.directory), day.recipe).days
    return _of_format(index.get(day.yyyydoy, ()), reader_format, day.recipe)


def unprocessed_files(
    directory: Path,
    reader_format: str | None = None,
    recipe: Path | None = None,
) -> list[Path]:
    """Files in ``directory`` that a run never processes.

    These are the compressed files (:func:`is_compressed`), the files
    neither the recipe nor the naming convention recognizes, and the
    recognized files of another file type than ``reader_format`` reads.

    Parameters
    ----------
    directory : Path
        The receiver's data directory.
    reader_format : str | None
        As for :func:`discover_files`.
    recipe : Path | None
        The receiver's naming recipe file, if it has one.

    Returns
    -------
    list[Path]
        Compressed files, unrecognized files, then the files of another
        type, each sorted.
    """
    scan = _scan_directory(Path(directory), recipe)
    read = {
        f.path
        for files in scan.days.values()
        for f in _of_format(files, reader_format, recipe)
    }
    other_type = sorted(
        f.path for files in scan.days.values() for f in files if f.path not in read
    )
    return [*scan.compressed, *scan.unrecognized, *other_type]


def detect_reader_format(files: list[DiscoveredFile]) -> str:
    """Reader format for a receiver whose config says ``reader_format: auto``.

    SBF and NMEA files are recognized by their canonical file type, RINEX
    files by the version in their header: ``"rinex2"`` or ``"rinex3"``.

    Raises
    ------
    DiscoveryError
        If ``files`` is empty, a RINEX header cannot be read, or the files
        need different readers (e.g. SBF next to RINEX, or RINEX 2 next to
        RINEX 3): set ``reader_format`` of the receiver, or keep the formats
        in separate directories.
    """
    from canvodpy.factories import ReaderFactory

    if not files:
        raise DiscoveryError("No files to detect the reader format from")
    formats: dict[str, Path] = {}
    for f in files:
        file_type = Path(f.canonical_name).suffix[1:]
        fmt = _FORMAT_OF_FILE_TYPE.get(file_type)
        if fmt is None:
            # The stripped RINEX 3 reader is an opt-in speed-up, never chosen
            # automatically; the full RINEX 3 reader reads those files too.
            try:
                fmt = ReaderFactory.detect_reader(f.path).replace("_stripped", "")
            except (OSError, ValueError) as exc:
                raise DiscoveryError(
                    f"Cannot tell the reader of {f.path}: {exc}. Set reader_format "
                    "for this receiver."
                ) from exc
        formats.setdefault(fmt, f.path)
    if len(formats) > 1:
        examples = ", ".join(
            f"{fmt} ({path.name})" for fmt, path in sorted(formats.items())
        )
        raise DiscoveryError(
            f"Files of one receiver need different readers: {examples}. Set "
            "reader_format for this receiver, or keep each format in its own "
            "directory."
        )
    return next(iter(formats))
