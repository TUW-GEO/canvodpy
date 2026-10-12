"""Time-aware GNSS satellite catalog from IGS satellite metadata.

Parses the IGS ``igs_satellite_metadata.snx`` SINEX file to provide
authoritative, time-aware satellite metadata:

- PRN ↔ SVN mapping with validity periods
- Satellite block/type (GPS-IIF, GPS-IIIA, GAL-FOC, etc.)
- Transmit power (Watts) per SVN with validity periods
- Satellite mass (kg)
- GLONASS frequency channel numbers
- COSPAR ID, NORAD catalog number
- Orbital plane and slot assignments
- Launch dates (from comment field)

This replaces the ``WikipediaCache`` approach with a single authoritative
source maintained by the IGS.

Examples
--------
Fetch and query::

    catalog = SatelliteCatalog.fetch()

    # What SVN is behind G01 on this date?
    svn = catalog.prn_to_svn("G01", date(2025, 6, 17))

    # Was there a reassignment in my processing window?
    changes = catalog.reassignments_in_range(
        "G01", date(2025, 1, 1), date(2025, 12, 31)
    )

    # All active PRNs for GPS on a date
    active = catalog.active_prns("G", date(2025, 1, 1))

    # Satellite block type
    block = catalog.satellite_block("G063", date(2025, 1, 1))

    # Transmit power
    power = catalog.tx_power("G063", date(2025, 1, 1))

From a local file::

    catalog = SatelliteCatalog.from_file("/path/to/igs_satellite_metadata.snx")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl
    import xarray as xr

import structlog

_log = structlog.get_logger(__name__)

IGS_SNX_URL = "https://files.igs.org/pub/station/general/igs_satellite_metadata.snx"
SNX_FILENAME = "igs_satellite_metadata.snx"

# Search order for discovering the SNX file (first match wins):
#   1. Explicit path passed to from_file() / load()
#   2. aux_data_dir from canvod config (if available)
#   3. Project-local ./aux/ directory
#   4. ~/.cache/canvod/
#   5. Bundled fallback in the package (always works offline)

_FALLBACK_SNX = Path(__file__).parent / "data" / SNX_FILENAME

# Constellation prefix → full name
_CONSTELLATION_NAMES = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "I": "IRNSS",
    "S": "SBAS",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidityPeriod:
    """A value valid over a time range."""

    start: date
    end: date | None  # None = still valid


@dataclass(frozen=True)
class PrnAssignment(ValidityPeriod):
    """PRN assigned to an SVN for a time period."""

    svn: str
    prn: str


@dataclass(frozen=True)
class SatelliteIdentity:
    """Static identity of a satellite vehicle."""

    svn: str
    cospar_id: str
    satcat: int
    block: str
    comment: str  # typically includes launch date


@dataclass(frozen=True)
class TxPowerRecord(ValidityPeriod):
    """Transmit power (Watts) for an SVN over a time period."""

    svn: str
    power_watts: int
    comment: str


@dataclass(frozen=True)
class MassRecord(ValidityPeriod):
    """Satellite mass (kg) for an SVN over a time period."""

    svn: str
    mass_kg: float
    comment: str


@dataclass(frozen=True)
class FrequencyChannel(ValidityPeriod):
    """GLONASS frequency channel for an SVN over a time period."""

    svn: str
    channel: int
    comment: str


@dataclass(frozen=True)
class PlaneSlot(ValidityPeriod):
    """Orbital plane and slot assignment."""

    svn: str
    plane: str
    slot: str
    comment: str


@dataclass(frozen=True)
class Reassignment:
    """A PRN reassignment event."""

    prn: str
    old_svn: str
    new_svn: str
    old_end: date
    new_start: date


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _parse_snx_epoch(epoch_str: str) -> date | None:
    """Parse SINEX epoch ``YYYY:DDD:SSSSS`` to a date.

    Returns ``None`` for the sentinel ``0000:000:00000`` (= open-ended).
    """
    parts = epoch_str.strip().split(":")
    if len(parts) != 3:
        return None
    year = int(parts[0])
    doy = int(parts[1])
    if year == 0 and doy == 0:
        return None
    # Two-digit year handling (SINEX convention)
    if year < 100:
        year += 1900 if year >= 80 else 2000
    return date(year, 1, 1) + timedelta(days=doy - 1)


def _extract_block(lines: list[str], block_name: str) -> list[str]:
    """Extract data lines (non-comment, non-header) from a SINEX block."""
    in_block = False
    result = []
    start_tag = f"+{block_name}"
    end_tag = f"-{block_name}"
    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith(start_tag):
            in_block = True
            continue
        if stripped.startswith(end_tag):
            break
        if in_block and not stripped.startswith("*") and stripped:
            result.append(line.rstrip())
    return result


# ---------------------------------------------------------------------------
# SatelliteCatalog
# ---------------------------------------------------------------------------


@dataclass
class SatelliteCatalog:
    """Time-aware GNSS satellite catalog from IGS SINEX metadata.

    Contains all satellite metadata from the IGS
    ``igs_satellite_metadata.snx`` file, indexed by SVN and PRN
    with validity periods.
    """

    identities: dict[str, SatelliteIdentity] = field(default_factory=dict)
    prn_assignments: list[PrnAssignment] = field(default_factory=list)
    tx_power_records: list[TxPowerRecord] = field(default_factory=list)
    mass_records: list[MassRecord] = field(default_factory=list)
    frequency_channels: list[FrequencyChannel] = field(default_factory=list)
    plane_slots: list[PlaneSlot] = field(default_factory=list)
    source_path: str | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> SatelliteCatalog:
        """Parse a local IGS satellite metadata SINEX file.

        Parameters
        ----------
        path : str or Path
            Path to ``igs_satellite_metadata.snx``.
        """
        path = Path(path)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        cat = cls(source_path=str(path))
        cat._parse_identifiers(lines)
        cat._parse_prn(lines)
        cat._parse_tx_power(lines)
        cat._parse_mass(lines)
        cat._parse_frequency_channel(lines)
        cat._parse_plane(lines)
        return cat

    @classmethod
    def load(
        cls,
        search_dirs: list[Path] | None = None,
        allow_download: bool = True,
        max_age_days: int = 7,
        url: str = IGS_SNX_URL,
    ) -> SatelliteCatalog:
        """Load the satellite catalog, searching multiple locations.

        Discovery order:

        1. *search_dirs* (explicit paths, e.g. from config ``aux_data_dir``)
        2. ``~/.cache/canvod/`` (user-level cache)
        3. Download from IGS (if *allow_download* is True and cache is stale)
        4. Bundled fallback shipped with the package (always works offline)

        The downloaded file is stored in the first writable directory from
        *search_dirs*, or ``~/.cache/canvod/`` if none are provided.

        Parameters
        ----------
        search_dirs : list[Path], optional
            Additional directories to search.  The first writable one is
            also used as the download target.  Typically includes the
            project's ``aux_data_dir`` from config.
        allow_download : bool
            If True (default), download from IGS when no fresh local copy
            is found.  Set to False for fully offline operation.
        max_age_days : int
            Re-download if the newest local copy is older than this
            (default 7 days).
        url : str
            IGS download URL.

        Returns
        -------
        SatelliteCatalog
            Parsed catalog.  Never raises — falls back to bundled copy.
        """
        # Build search path
        dirs = list(search_dirs or [])
        user_cache = Path.home() / ".cache" / "canvod"
        if user_cache not in dirs:
            dirs.append(user_cache)

        # 1. Search for existing file (pick freshest)
        best_file: Path | None = None
        best_mtime: float = 0
        for d in dirs:
            candidate = d / SNX_FILENAME
            if candidate.is_file():
                mtime = candidate.stat().st_mtime
                if mtime > best_mtime:
                    best_file = candidate
                    best_mtime = mtime

        # Check freshness
        if best_file is not None:
            age = datetime.now(tz=UTC) - datetime.fromtimestamp(best_mtime, tz=UTC)
            if age.days < max_age_days:
                _log.debug(
                    "satellite_catalog_loaded",
                    source=str(best_file),
                    age_days=age.days,
                )
                return cls.from_file(best_file)
            _log.info(
                "satellite_catalog_stale",
                source=str(best_file),
                age_days=age.days,
                max_age_days=max_age_days,
            )

        # 2. Download if allowed
        if allow_download:
            download_dir = cls._first_writable_dir(dirs)
            downloaded = cls._download(url, download_dir)
            if downloaded is not None:
                return cls.from_file(downloaded)

        # 3. Use stale local copy if available (better than fallback)
        if best_file is not None:
            _log.warning(
                "satellite_catalog_using_stale",
                source=str(best_file),
                hint="Could not download fresh copy; using stale local file.",
            )
            return cls.from_file(best_file)

        # 4. Bundled fallback (always available, ships with package)
        if _FALLBACK_SNX.is_file():
            _log.warning(
                "satellite_catalog_using_bundled_fallback",
                source=str(_FALLBACK_SNX),
                hint=(
                    "No local copy found and download failed or disabled. "
                    "Using bundled fallback (may be outdated). Place a fresh "
                    f"copy of '{SNX_FILENAME}' in one of: {[str(d) for d in dirs]}"
                ),
            )
            return cls.from_file(_FALLBACK_SNX)

        # Should not reach here if package is installed correctly
        msg = (
            f"Cannot find {SNX_FILENAME} in any search location and "
            "no bundled fallback is available."
        )
        raise FileNotFoundError(msg)

    @classmethod
    def fetch(
        cls,
        url: str = IGS_SNX_URL,
        cache_dir: str | Path | None = None,
        max_age_days: int = 7,
    ) -> SatelliteCatalog:
        """Fetch the catalog (convenience wrapper around :meth:`load`).

        Parameters
        ----------
        url : str
            IGS download URL.
        cache_dir : str or Path, optional
            Cache directory. Defaults to ``~/.cache/canvod/``.
        max_age_days : int
            Re-download if cached file is older than this.
        """
        search_dirs = [Path(cache_dir)] if cache_dir else []
        return cls.load(
            search_dirs=search_dirs,
            allow_download=True,
            max_age_days=max_age_days,
            url=url,
        )

    # -- Download helper ------------------------------------------------------

    @staticmethod
    def _first_writable_dir(dirs: list[Path]) -> Path:
        """Find or create the first writable directory."""
        for d in dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                # Test writability
                test_file = d / ".write_test"
                test_file.touch()
                test_file.unlink()
                return d
            except OSError:
                continue
        # Fallback: user cache is almost always writable
        fallback = Path.home() / ".cache" / "canvod"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    @staticmethod
    def _download(url: str, target_dir: Path) -> Path | None:
        """Download the SNX file. Returns path on success, None on failure."""
        import urllib.request

        target = target_dir / SNX_FILENAME
        try:
            _log.info("satellite_catalog_downloading", url=url, target=str(target))
            urllib.request.urlretrieve(url, target)
            _log.info("satellite_catalog_downloaded", target=str(target))
            return target
        except Exception as exc:
            _log.warning(
                "satellite_catalog_download_failed",
                url=url,
                error=str(exc),
                hint="Working offline? No problem; stale or bundled copy will be used.",
            )
            return None

    # -- Queries --------------------------------------------------------------

    def prn_to_svn(self, prn: str, on_date: date) -> str | None:
        """Get the SVN assigned to a PRN on a given date.

        Parameters
        ----------
        prn : str
            PRN code (e.g. ``"G01"``).
        on_date : date
            Query date.

        Returns
        -------
        str or None
            SVN (e.g. ``"G063"``) or None if no assignment found.
        """
        for a in self.prn_assignments:
            if a.prn == prn and self._in_range(on_date, a):
                return a.svn
        return None

    def svn_to_prn(self, svn: str, on_date: date) -> str | None:
        """Get the PRN assigned to an SVN on a given date."""
        for a in self.prn_assignments:
            if a.svn == svn and self._in_range(on_date, a):
                return a.prn
        return None

    def prn_history(self, prn: str) -> list[PrnAssignment]:
        """Get the full assignment history for a PRN.

        Returns a chronologically sorted list of all SVNs that have
        been assigned to this PRN.
        """
        records = [a for a in self.prn_assignments if a.prn == prn]
        return sorted(records, key=lambda a: a.start)

    def svn_history(self, svn: str) -> list[PrnAssignment]:
        """Get the full PRN history for an SVN."""
        records = [a for a in self.prn_assignments if a.svn == svn]
        return sorted(records, key=lambda a: a.start)

    def reassignments_in_range(
        self,
        prn: str,
        start: date,
        end: date,
    ) -> list[Reassignment]:
        """Detect PRN reassignments within a time range.

        Parameters
        ----------
        prn : str
            PRN code (e.g. ``"G01"``).
        start, end : date
            Time range to check.

        Returns
        -------
        list[Reassignment]
            Reassignment events where the SVN behind this PRN changed.
        """
        history = self.prn_history(prn)
        reassignments = []
        for i in range(1, len(history)):
            prev = history[i - 1]
            curr = history[i]
            # Check if this transition falls within the query range
            if curr.start <= end and (prev.end is None or prev.end >= start):
                if prev.svn != curr.svn:
                    reassignments.append(
                        Reassignment(
                            prn=prn,
                            old_svn=prev.svn,
                            new_svn=curr.svn,
                            old_end=prev.end or curr.start,
                            new_start=curr.start,
                        )
                    )
        return reassignments

    def active_prns(
        self,
        constellation: str,
        on_date: date,
    ) -> list[str]:
        """Get all active PRNs for a constellation on a date.

        Parameters
        ----------
        constellation : str
            Single-letter prefix (``"G"``, ``"R"``, ``"E"``, ``"C"``,
            ``"J"``, ``"I"``, ``"S"``).
        on_date : date
            Query date.

        Returns
        -------
        list[str]
            Sorted list of active PRN codes.
        """
        prns = set()
        for a in self.prn_assignments:
            if a.prn.startswith(constellation) and self._in_range(on_date, a):
                prns.add(a.prn)
        return sorted(prns)

    def satellite_block(self, svn: str) -> str | None:
        """Get the satellite block/type for an SVN.

        Parameters
        ----------
        svn : str
            SVN code (e.g. ``"G063"``).

        Returns
        -------
        str or None
            Block type (e.g. ``"GPS-IIF"``, ``"GAL-2"``).
        """
        identity = self.identities.get(svn)
        return identity.block if identity else None

    def satellite_info(self, svn: str) -> SatelliteIdentity | None:
        """Get full identity for an SVN."""
        return self.identities.get(svn)

    def tx_power(self, svn: str, on_date: date) -> int | None:
        """Get transmit power (Watts) for an SVN on a date.

        Parameters
        ----------
        svn : str
            SVN code.
        on_date : date
            Query date.

        Returns
        -------
        int or None
            Transmit power in Watts, or None if not available.
        """
        for r in self.tx_power_records:
            if r.svn == svn and self._in_range(on_date, r):
                return r.power_watts
        return None

    def mass(self, svn: str, on_date: date) -> float | None:
        """Get satellite mass (kg) for an SVN on a date."""
        for r in self.mass_records:
            if r.svn == svn and self._in_range(on_date, r):
                return r.mass_kg
        return None

    def glonass_channel(self, svn: str, on_date: date) -> int | None:
        """Get GLONASS frequency channel number for an SVN on a date."""
        for r in self.frequency_channels:
            if r.svn == svn and self._in_range(on_date, r):
                return r.channel
        return None

    def plane_and_slot(
        self,
        svn: str,
        on_date: date,
    ) -> tuple[str, str] | None:
        """Get orbital plane and slot for an SVN on a date."""
        for r in self.plane_slots:
            if r.svn == svn and self._in_range(on_date, r):
                return r.plane, r.slot
        return None

    def get_prn_metadata(
        self,
        prn: str,
        on_date: date,
    ) -> dict | None:
        """Get all metadata for a PRN on a given date.

        Resolves the SVN and returns a dict with all available info.
        """
        svn = self.prn_to_svn(prn, on_date)
        if svn is None:
            return None

        identity = self.identities.get(svn)
        plane_slot = self.plane_and_slot(svn, on_date)

        return {
            "prn": prn,
            "svn": svn,
            "block": identity.block if identity else None,
            "cospar_id": identity.cospar_id if identity else None,
            "satcat": identity.satcat if identity else None,
            "comment": identity.comment if identity else None,
            "tx_power_watts": self.tx_power(svn, on_date),
            "mass_kg": self.mass(svn, on_date),
            "plane": plane_slot[0] if plane_slot else None,
            "slot": plane_slot[1] if plane_slot else None,
            "glonass_channel": self.glonass_channel(svn, on_date),
        }

    def summary(self) -> dict[str, int | dict[str, int]]:
        """Return a summary of catalog contents."""
        constellations: dict[str, int] = {}
        for svn in self.identities:
            prefix = svn[0]
            name = _CONSTELLATION_NAMES.get(prefix, prefix)
            constellations[name] = constellations.get(name, 0) + 1

        return {
            "total_svns": len(self.identities),
            "constellations": constellations,
            "prn_assignments": len(self.prn_assignments),
            "tx_power_records": len(self.tx_power_records),
            "mass_records": len(self.mass_records),
            "frequency_channels": len(self.frequency_channels),
            "plane_slots": len(self.plane_slots),
        }

    # -- DataFrame export -----------------------------------------------------

    def to_dataframe(self, on_date: date | None = None) -> pl.DataFrame:
        """Export catalog as a Polars DataFrame.

        If *on_date* is given, returns one row per active PRN on that date
        with resolved SVN, block, TX power, mass, plane, slot, etc.
        If *on_date* is None, returns one row per PRN assignment (full history).

        Parameters
        ----------
        on_date : date, optional
            Snapshot date.  If provided, only active PRNs are included
            and all time-varying fields are resolved to that date.

        Returns
        -------
        polars.DataFrame
            Catalog data suitable for plotting, filtering, joining.
        """
        import polars as pl

        if on_date is not None:
            rows = []
            seen_prns: set[str] = set()
            for a in self.prn_assignments:
                if a.prn in seen_prns:
                    continue
                if not self._in_range(on_date, a):
                    continue
                seen_prns.add(a.prn)
                ident = self.identities.get(a.svn)
                ps = self.plane_and_slot(a.svn, on_date)
                rows.append(
                    {
                        "prn": a.prn,
                        "svn": a.svn,
                        "constellation": a.prn[0],
                        "block": ident.block if ident else None,
                        "cospar_id": ident.cospar_id if ident else None,
                        "satcat": ident.satcat if ident else None,
                        "tx_power_watts": self.tx_power(a.svn, on_date),
                        "mass_kg": self.mass(a.svn, on_date),
                        "plane": ps[0] if ps else None,
                        "slot": ps[1] if ps else None,
                        "glonass_channel": self.glonass_channel(a.svn, on_date),
                        "launch": ident.comment if ident else None,
                    }
                )
            return pl.DataFrame(rows).sort("prn")

        # Full history: one row per PRN assignment
        rows = []
        for a in self.prn_assignments:
            ident = self.identities.get(a.svn)
            rows.append(
                {
                    "prn": a.prn,
                    "svn": a.svn,
                    "constellation": a.prn[0],
                    "block": ident.block if ident else None,
                    "start": a.start,
                    "end": a.end,
                }
            )
        return pl.DataFrame(rows).sort("prn", "start")

    def enrich_dataset(
        self,
        ds: xr.Dataset,
        on_date: date | None = None,
    ) -> xr.Dataset:
        """Add satellite metadata as coordinates on the ``sid`` dimension.

        Adds ``svn``, ``block``, ``tx_power_watts``, ``mass_kg``,
        ``plane``, ``slot`` as sid-level coordinates.  These are constant
        per satellite (resolved for a single date), not per-epoch.

        Parameters
        ----------
        ds : xarray.Dataset
            Dataset with a ``sid`` dimension and an ``sv`` coordinate
            containing bare PRN codes (e.g. ``"G01"``), as produced by every
            ``canvod-readers`` reader. ``sid`` itself is the compound
            ``"{sv}|{band}|{code}"`` form and is never matched directly.
        on_date : date, optional
            Date for resolving time-varying fields.  If not provided,
            inferred from the first epoch in the dataset.

        Returns
        -------
        xarray.Dataset
            Dataset with additional sid-level coordinates.
        """
        import numpy as np

        if on_date is None:
            epoch_vals = ds.epoch.values
            if len(epoch_vals) > 0:
                ts = np.datetime64(epoch_vals[0], "D")
                on_date = ts.astype("datetime64[D]").astype(date)
            else:
                msg = "Cannot infer date from empty dataset; provide on_date."
                raise ValueError(msg)

        svs = list(ds.sv.values)
        svn_arr = []
        block_arr = []
        tx_power_arr = []
        mass_arr = []
        plane_arr = []
        slot_arr = []

        for prn in svs:
            meta = self.get_prn_metadata(str(prn), on_date)
            if meta:
                svn_arr.append(meta["svn"])
                block_arr.append(meta["block"] or "")
                tx_power_arr.append(meta["tx_power_watts"])
                mass_arr.append(meta["mass_kg"])
                plane_arr.append(meta["plane"] or "")
                slot_arr.append(meta["slot"] or "")
            else:
                svn_arr.append("")
                block_arr.append("")
                tx_power_arr.append(None)
                mass_arr.append(None)
                plane_arr.append("")
                slot_arr.append("")

        ds = ds.assign_coords(
            {
                "svn": ("sid", svn_arr),
                "block": ("sid", block_arr),
                "tx_power_watts": ("sid", np.array(tx_power_arr, dtype="float64")),
                "mass_kg": ("sid", np.array(mass_arr, dtype="float64")),
                "plane": ("sid", plane_arr),
                "slot": ("sid", slot_arr),
            }
        )

        n_enriched = sum(1 for s in svn_arr if s)
        log_fn = _log.warning if svs and n_enriched == 0 else _log.info
        log_fn(
            "dataset_enriched_with_catalog",
            total_sids=len(svs),
            enriched=n_enriched,
            missing=len(svs) - n_enriched,
        )
        return ds

    # -- Parsing --------------------------------------------------------------

    def _parse_identifiers(self, lines: list[str]) -> None:
        """Parse SATELLITE/IDENTIFIER block."""
        for line in _extract_block(lines, "SATELLITE/IDENTIFIER"):
            if len(line) < 44:
                continue
            svn = line[1:5].strip()
            cospar_id = line[6:16].strip()
            satcat_str = line[17:23].strip()
            block = line[23:39].strip()
            comment = line[39:].strip() if len(line) > 39 else ""

            # Normalize SVN: G001 → G001 (keep as-is for consistency)
            self.identities[svn] = SatelliteIdentity(
                svn=svn,
                cospar_id=cospar_id,
                satcat=int(satcat_str) if satcat_str else 0,
                block=block,
                comment=comment,
            )

    def _parse_prn(self, lines: list[str]) -> None:
        """Parse SATELLITE/PRN block."""
        for line in _extract_block(lines, "SATELLITE/PRN"):
            if len(line) < 39:
                continue
            svn = line[1:5].strip()
            start = _parse_snx_epoch(line[6:20])
            end = _parse_snx_epoch(line[21:35])
            prn = line[36:39].strip()

            if start is None:
                continue

            self.prn_assignments.append(
                PrnAssignment(svn=svn, prn=prn, start=start, end=end)
            )

    def _parse_tx_power(self, lines: list[str]) -> None:
        """Parse SATELLITE/TX_POWER block."""
        for line in _extract_block(lines, "SATELLITE/TX_POWER"):
            if len(line) < 40:
                continue
            svn = line[1:5].strip()
            start = _parse_snx_epoch(line[6:20])
            end = _parse_snx_epoch(line[21:35])
            power_str = line[36:40].strip()
            comment = line[41:].strip() if len(line) > 41 else ""

            if start is None or not power_str:
                continue

            self.tx_power_records.append(
                TxPowerRecord(
                    svn=svn,
                    power_watts=int(power_str),
                    start=start,
                    end=end,
                    comment=comment,
                )
            )

    def _parse_mass(self, lines: list[str]) -> None:
        """Parse SATELLITE/MASS block."""
        for line in _extract_block(lines, "SATELLITE/MASS"):
            if len(line) < 46:
                continue
            svn = line[1:5].strip()
            start = _parse_snx_epoch(line[6:20])
            end = _parse_snx_epoch(line[21:35])
            mass_str = line[36:46].strip()
            comment = line[46:].strip() if len(line) > 46 else ""

            if start is None or not mass_str:
                continue

            self.mass_records.append(
                MassRecord(
                    svn=svn,
                    mass_kg=float(mass_str),
                    start=start,
                    end=end,
                    comment=comment,
                )
            )

    def _parse_frequency_channel(self, lines: list[str]) -> None:
        """Parse SATELLITE/FREQUENCY_CHANNEL block."""
        for line in _extract_block(lines, "SATELLITE/FREQUENCY_CHANNEL"):
            if len(line) < 40:
                continue
            svn = line[1:5].strip()
            start = _parse_snx_epoch(line[6:20])
            end = _parse_snx_epoch(line[21:35])
            chan_str = line[36:40].strip()
            comment = line[40:].strip() if len(line) > 40 else ""

            if start is None or not chan_str:
                continue

            self.frequency_channels.append(
                FrequencyChannel(
                    svn=svn,
                    channel=int(chan_str),
                    start=start,
                    end=end,
                    comment=comment,
                )
            )

    def _parse_plane(self, lines: list[str]) -> None:
        """Parse SATELLITE/PLANE block."""
        for line in _extract_block(lines, "SATELLITE/PLANE"):
            if len(line) < 46:
                continue
            svn = line[1:5].strip()
            start = _parse_snx_epoch(line[6:20])
            end = _parse_snx_epoch(line[21:35])
            plane = line[36:37].strip()
            slot = line[38:45].strip()
            comment = line[45:].strip() if len(line) > 45 else ""

            if start is None:
                continue

            self.plane_slots.append(
                PlaneSlot(
                    svn=svn,
                    plane=plane,
                    slot=slot,
                    start=start,
                    end=end,
                    comment=comment,
                )
            )

    # -- Internal helpers -----------------------------------------------------

    @staticmethod
    def _in_range(query_date: date, record: ValidityPeriod) -> bool:
        """Check if a date falls within a validity period."""
        if query_date < record.start:
            return False
        if record.end is not None and query_date > record.end:
            return False
        return True

    def __repr__(self) -> str:
        s = self.summary()
        return (
            f"SatelliteCatalog("
            f"{s['total_svns']} SVNs, "
            f"{s['prn_assignments']} PRN assignments, "
            f"{s['tx_power_records']} TX power records, "
            f"constellations={s['constellations']})"
        )
