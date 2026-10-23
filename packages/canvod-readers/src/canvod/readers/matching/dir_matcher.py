"""Directory matching for RINEX data files.

Scans filesystem to identify directories containing RINEX files for
canopy and reference receivers across multiple dates.
"""

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from natsort import natsorted

from canvod.readers.gnss_specs.constants import RINEX_OBS_GLOB_PATTERNS
from canvod.utils.tools import YYYYDOY, deprecated

from .models import MatchedDirs, PairMatchedDirs

DATE_DIR_LEN = 5

#: Files that make a directory count as holding GNSS data: RINEX and
#: Septentrio short names, canonical canVOD names, and their compressed forms.
_GNSS_FILE_GLOBS: tuple[str, ...] = (
    *RINEX_OBS_GLOB_PATTERNS,
    "*_R_*_*_*_*.rnx*",
    "*_R_*_*_*_*.crx*",
    "*_R_*_*_*_*.sbf*",
    "*_R_*_*_*_*.ubx*",
    "*_R_*_*_*_*.nmea*",
    "*.[0-9][0-9][oOdD]",
    "*.[0-9][0-9][oOdD].*",
    "*.[0-9][0-9]_.*",
)


def _has_rinex_files(directory: Path) -> bool:
    """Check if directory exists and contains GNSS observation files.

    Parameters
    ----------
    directory : Path
        Directory to check.

    Returns
    -------
    bool
        True if directory exists and contains GNSS data files
        (see ``_GNSS_FILE_GLOBS``).

    """
    if not directory.exists():
        return False
    return any(any(directory.glob(pattern)) for pattern in _GNSS_FILE_GLOBS)


@deprecated(
    "DataDirMatcher is left over from development and will be removed with the next major version. "
    "Use canvodpy.Site(<site>).pipeline() or the `canvodpy run` command instead."
)
class DataDirMatcher:
    """Match RINEX data directories for canopy and reference receivers.

    Scans a root directory structure to find dates with RINEX files
    present in both canopy and reference receiver directories.

    Parameters
    ----------
    root : Path
        Root directory containing receiver subdirectories
    reference_pattern : Path, optional
        Relative path pattern for reference receiver
        (default: "01_reference/01_GNSS/01_raw")
    canopy_pattern : Path, optional
        Relative path pattern for canopy receiver
        (default: "02_canopy/01_GNSS/01_raw")

    Examples
    --------
    >>> from pathlib import Path
    >>> matcher = DataDirMatcher(
    ...     root=Path("/data/01_ExampleSite"),
    ...     reference_pattern=Path("01_reference/01_GNSS/01_raw"),
    ...     canopy_pattern=Path("02_canopy/01_GNSS/01_raw")
    ... )
    >>>
    >>> # Iterate over matched directories
    >>> for matched_dirs in matcher:
    ...     print(matched_dirs.yyyydoy)
    ...     rinex_files = list(matched_dirs.canopy_data_dir.glob("*.25o"))
    ...     print(f"  Found {len(rinex_files)} RINEX files")

    >>> # Get list of common dates
    >>> dates = matcher.get_common_dates()
    >>> print(f"Found {len(dates)} dates with data")

    """

    def __init__(
        self,
        root: Path,
        reference_pattern: Path = Path("01_reference/01_GNSS/01_raw"),
        canopy_pattern: Path = Path("02_canopy/01_GNSS/01_raw"),
    ) -> None:
        """Initialize matcher with directory structure."""
        self.root = Path(root)
        self.reference_dir = self.root / reference_pattern
        self.canopy_dir = self.root / canopy_pattern

        # Validate directories exist
        self._validate_directory(self.root, "Root")
        self._validate_directory(self.reference_dir, "Reference")
        self._validate_directory(self.canopy_dir, "Canopy")

    def __iter__(self) -> Iterator[MatchedDirs]:
        """Iterate over matched directory pairs with RINEX files.

        Yields
        ------
        MatchedDirs
            Matched directories for each date.

        """
        for date_str in self.get_common_dates():
            yield MatchedDirs(
                canopy_data_dir=self.canopy_dir / date_str,
                reference_data_dir=self.reference_dir / date_str,
                yyyydoy=YYYYDOY.from_yydoy_str(date_str),
            )

    def get_common_dates(self) -> list[str]:
        """Get dates with RINEX files in both receivers.

        Uses parallel processing to check directories efficiently.

        Returns
        -------
        list[str]
            Sorted list of date strings (YYDDD format, e.g., "25001")
            that have RINEX files in both canopy and reference directories.

        """
        # Find dates with RINEX in each receiver
        ref_dates = self._get_dates_with_rinex(self.reference_dir)
        can_dates = self._get_dates_with_rinex(self.canopy_dir)

        # Find intersection
        common = ref_dates & can_dates
        common.discard("00000")  # Remove placeholder directories

        # Sort naturally (numerical order)
        return natsorted(common)

    def _get_dates_with_rinex(self, base_dir: Path) -> set[str]:
        """Find all date directories containing RINEX files.

        Uses parallel processing to check multiple directories at once.

        Parameters
        ----------
        base_dir : Path
            Base directory to search (e.g., canopy or reference root).

        Returns
        -------
        set[str]
            Set of date directory names that contain RINEX files.

        """
        # Get all subdirectories
        date_dirs = (d for d in base_dir.iterdir() if d.is_dir())

        # Check for RINEX files in parallel
        dates_with_rinex = set()

        with ThreadPoolExecutor() as executor:
            future_to_dir = {
                executor.submit(self._has_rinex_files, d): d for d in date_dirs
            }

            for future in as_completed(future_to_dir):
                directory = future_to_dir[future]
                if future.result():
                    dates_with_rinex.add(directory.name)

        return dates_with_rinex

    @staticmethod
    def _has_rinex_files(directory: Path) -> bool:
        """Check if directory contains RINEX observation files.

        Parameters
        ----------
        directory : Path
            Directory to check.

        Returns
        -------
        bool
            True if RINEX files found.

        """
        return _has_rinex_files(directory)

    def _validate_directory(self, path: Path, name: str) -> None:
        """Validate directory exists.

        Parameters
        ----------
        path : Path
            Directory to check.
        name : str
            Name for error message.

        Raises
        ------
        FileNotFoundError
            If directory doesn't exist.

        """
        if not path.exists():
            msg = f"{name} directory not found: {path}"
            raise FileNotFoundError(msg)


@deprecated(
    "PairDataDirMatcher is left over from development and will be removed with the next major version. "
    "It only finds data in YYDDD day folders. Use canvodpy.Site(<site>).pipeline() or the "
    "`canvodpy run` command instead, which find each file's day from its name in any folder layout."
)
class PairDataDirMatcher:
    """Match RINEX directories for receiver pairs across dates.

    Supports multi-receiver configurations where multiple canopy/reference
    pairs may exist at the same site. Requires a configuration dict
    specifying receiver locations and analysis pairs.

    Parameters
    ----------
    base_dir : Path
        Root directory containing all receiver data
    receivers : dict
        Receiver configuration mapping receiver names to their directory paths.
        The ``directory`` value is the full relative path from ``base_dir`` to the
        raw RINEX data directory (before the ``{YYDOY}`` date folders).
        Example: {"canopy_01": {"directory": "02_canopy_01/01_GNSS/01_raw"},
                  "reference_01": {"directory": "01_reference_01/01_GNSS/01_raw"}}
    analysis_pairs : dict
        Analysis pair configuration specifying which receivers to match
        Example: {"pair_01": {"canopy_receiver": "canopy_01",
                               "reference_receiver": "reference_01"}}
    has_data : Callable[[str, Path], bool], optional
        ``has_data(receiver_name, day_dir)`` decides whether a receiver's
        day directory holds data to process. The pipeline passes its own
        file discovery here, so a day counts only if the run would process
        files from it. Defaults to a filename-glob check.

    Examples
    --------
    >>> receivers = {
    ...     "canopy_01": {"directory": "02_canopy/01_GNSS/01_raw"},
    ...     "reference_01": {"directory": "01_reference/01_GNSS/01_raw"}
    ... }
    >>> pairs = {
    ...     "main_pair": {
    ...         "canopy_receiver": "canopy_01",
    ...         "reference_receiver": "reference_01"
    ...     }
    ... }
    >>>
    >>> matcher = PairDataDirMatcher(
    ...     base_dir=Path("/data/01_ExampleSite"),
    ...     receivers=receivers,
    ...     analysis_pairs=pairs
    ... )
    >>>
    >>> for matched in matcher:
    ...     print(f"{matched.yyyydoy}: {matched.pair_name}")
    ...     print(f"  Canopy: {matched.canopy_data_dir}")
    ...     print(f"  Reference: {matched.reference_data_dir}")

    """

    def __init__(
        self,
        base_dir: Path,
        receivers: dict[str, dict[str, str]],
        analysis_pairs: dict[str, dict[str, str]],
        has_data: Callable[[str, Path], bool] | None = None,
    ) -> None:
        """Initialize pair matcher with receiver configuration."""
        self.base_dir = Path(base_dir)
        self.receivers = receivers
        self.analysis_pairs = analysis_pairs
        self._has_data = has_data or (lambda _receiver, path: _has_rinex_files(path))

        # Validate receivers have directory config
        self.receiver_dirs = self._build_receiver_dir_mapping()

    def _build_receiver_dir_mapping(self) -> dict[str, str]:
        """Map receiver names to their directory prefixes.

        Returns
        -------
        dict[str, str]
            Mapping of receiver name to directory path.

        Raises
        ------
        ValueError
            If receiver missing 'directory' in config.

        """
        mapping = {}
        for receiver_name, config in self.receivers.items():
            if "directory" not in config:
                msg = f"Receiver '{receiver_name}' missing 'directory' in config"
                raise ValueError(msg)
            mapping[receiver_name] = config["directory"]
        return mapping

    def _get_receiver_path(self, receiver_name: str, yyyydoy: YYYYDOY) -> Path:
        """Build full path to receiver data for a specific date.

        Parameters
        ----------
        receiver_name : str
            Receiver name (e.g., "canopy_01").
        yyyydoy : YYYYDOY
            Date object.

        Returns
        -------
        Path
            Full path to receiver's RINEX directory for the date.

        """
        receiver_dir = self.receiver_dirs[receiver_name]

        # Convert YYYYDDD to YYDDD format for directory name
        yyddd_str = yyyydoy.yydoy
        if yyddd_str is None:
            msg = f"Missing YYDDD representation for date {yyyydoy}"
            raise ValueError(msg)

        return self.base_dir / receiver_dir / yyddd_str

    def _get_all_dates(self) -> set[YYYYDOY]:
        """Find all dates that have data in any receiver directory.

        Returns
        -------
        set[YYYYDOY]
            Set of all dates with available data.

        """
        all_dates = set()

        for receiver_name in self.receivers:
            receiver_dir = self.receiver_dirs[receiver_name]
            receiver_base = self.base_dir / receiver_dir

            if not receiver_base.exists():
                continue

            # Find all date directories (format: YYDDD - 5 digits)
            for date_dir in receiver_base.iterdir():
                if not date_dir.is_dir():
                    continue

                # Check if directory name is 5 digits
                if len(date_dir.name) != DATE_DIR_LEN or not date_dir.name.isdigit():
                    continue

                # Skip placeholder directories
                if date_dir.name == "00000":
                    continue

                try:
                    yyyydoy = YYYYDOY.from_yydoy_str(date_dir.name)
                    all_dates.add(yyyydoy)
                except ValueError:
                    continue

        return all_dates

    def __iter__(self) -> Iterator[PairMatchedDirs]:
        """Iterate over all date/pair combinations with available data.

        Yields
        ------
        PairMatchedDirs
            Matched directories for a receiver pair on a specific date.

        """
        all_dates = sorted(self._get_all_dates())

        for yyyydoy in all_dates:
            # For each configured analysis pair
            for pair_name, pair_config in self.analysis_pairs.items():
                canopy_rx = pair_config["canopy_receiver"]
                reference_rx = pair_config["reference_receiver"]

                # Build paths for this pair
                canopy_path = self._get_receiver_path(canopy_rx, yyyydoy)
                reference_path = self._get_receiver_path(reference_rx, yyyydoy)

                # Check for RINEX files
                canopy_has_files = self._has_data(canopy_rx, canopy_path)
                reference_has_files = self._has_data(reference_rx, reference_path)

                # Only yield if both directories exist and have data
                if canopy_has_files and reference_has_files:
                    yield PairMatchedDirs(
                        yyyydoy=yyyydoy,
                        pair_name=pair_name,
                        canopy_receiver=canopy_rx,
                        reference_receiver=reference_rx,
                        canopy_data_dir=canopy_path,
                        reference_data_dir=reference_path,
                    )
