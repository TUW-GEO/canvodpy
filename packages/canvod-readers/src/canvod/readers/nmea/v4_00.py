"""NMEA v4.00 sentence reader.

Parses NMEA sentences (RMC, GGA, GSV) and produces an ``xarray.Dataset``
with ``(epoch, sid)`` dimensions compatible with the canvodpy pipeline.

Supports:
- GPS ($GP), GLONASS ($GL), Galileo ($GA), BeiDou ($GB) GSV sentences
- RMC and GGA sentences for epoch timestamps (UTC, converted to GPS time
  with the leap seconds of the date, see ``gnss_specs.leap_seconds``)
- PRN-to-RINEX SV mapping per NMEA v4 PRN numbering scheme
- Checksum validation

Classes:
- NmeaObs: Main reader class, converts NMEA sentences to xarray Dataset
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Final

import numpy as np
import xarray as xr
from pydantic import BaseModel, ConfigDict, field_validator

from canvod.readers.base import (
    GNSSDataReader,
    validate_dataset,
)
from canvod.readers.gnss_specs.leap_seconds import utc_to_gps
from canvod.readers.gnss_specs.metadata import (
    COORDS_METADATA,
    DTYPES,
    SNR_METADATA,
    epoch_coord_attrs,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.readers.nmea.exceptions import (
    NmeaChecksumError,
    NmeaInvalidSentenceError,
    NmeaMissingSentenceError,
)
from canvod.utils.tools import hashing

# ---------------------------------------------------------------------------
# NMEA checksum helpers
# ---------------------------------------------------------------------------
_CHECKSUM_RE: Final = re.compile(r"^\$(.+)\*([0-9A-Fa-f]{2})$")


def compute_nmea_checksum(sentence: str) -> str:
    """Compute the XOR checksum of the NMEA payload (between ``$`` and ``*``)."""
    m = _CHECKSUM_RE.match(sentence.strip())
    if not m:
        msg = f"Cannot extract payload from sentence: {sentence!r}"
        raise NmeaInvalidSentenceError(msg)
    payload = m.group(1)
    cksum = 0
    for ch in payload:
        cksum ^= ord(ch)
    return f"{cksum:02X}"


def validate_nmea_checksum(sentence: str) -> None:
    """Validate an NMEA sentence checksum."""
    m = _CHECKSUM_RE.match(sentence.strip())
    if not m:
        msg = f"Malformed NMEA sentence (no checksum): {sentence!r}"
        raise NmeaInvalidSentenceError(msg)
    expected = m.group(2).upper()
    actual = compute_nmea_checksum(sentence)
    if expected != actual:
        raise NmeaChecksumError(sentence, expected, actual)


# ---------------------------------------------------------------------------
# NMEA sentence field helpers
# ---------------------------------------------------------------------------


def _parse_nmea_fields(sentence: str) -> tuple[str, list[str]]:
    """Split an NMEA sentence into its message ID and data fields."""
    sentence = sentence.strip()
    star_idx = sentence.rfind("*")
    if star_idx != -1:
        sentence = sentence[:star_idx]
    parts = sentence.split(",")
    return parts[0], parts[1:]


def _talker_id(msg_id: str) -> str:
    """Extract the 2-char talker ID from a message ID like ``$GPGSV``."""
    return msg_id[1:3]


# ---------------------------------------------------------------------------
# PRN → RINEX SV mapping
# ---------------------------------------------------------------------------

# The GSV SNR unit is not established: the bundled SiRF NMEA Reference
# Manual (Rev 2.1, GSV) gives "SNR (C/N0) ... dBHz", gpsd documents dB.
_NMEA_SNR_METADATA: Final[dict[str, Any]] = {
    **SNR_METADATA,
    "description": (
        "SNR field of the NMEA GSV sentence (00-99, null when not tracking). "
        "Its unit is not established (the SiRF NMEA Reference Manual Rev 2.1 "
        "gives C/N0 in dBHz, other sources dB); dB is assumed."
    ),
}

# Default band/code assigned to NMEA SNR (one band per system).
# NMEA GSV reports SNR on the primary signal band for each constellation.
DEFAULT_NMEA_BAND_MAP: Final[dict[str, tuple[str, str]]] = {
    "G": ("L1", "C"),  # GPS L1 C/A
    "R": ("G1", "C"),  # GLONASS G1 C/A
    "E": ("E1", "C"),  # Galileo E1
    "C": ("B1I", "I"),  # BeiDou B1I
    "S": ("L1", "C"),  # SBAS L1
}

# u-blox NMEA 4.11 signal ID mapping (Table 4, section 1.5.4).
# Key: (system_letter, signal_id_hex_digit) → (band, tracking_code)
# The signal ID is the 1-digit hex field after the last satellite block
# in a GSV sentence, right before *checksum.
UBLOX_SIGNAL_ID_MAP: Final[dict[str, dict[str, tuple[str, str]]]] = {
    "G": {  # GPS (NMEA system ID 1)
        "1": ("L1", "C"),  # L1 C/A
        "5": ("L2", "M"),  # L2 CM
        "6": ("L2", "L"),  # L2 CL
        "7": ("L5", "I"),  # L5 I
        "8": ("L5", "Q"),  # L5 Q
    },
    "S": {  # SBAS (NMEA system ID 1, same as GPS)
        "1": ("L1", "C"),  # L1 C/A
    },
    "E": {  # Galileo (NMEA system ID 3)
        "1": ("E5a", "X"),  # E5 aI + aQ
        "2": ("E5b", "X"),  # E5 bI + bQ
        "7": ("E1", "X"),  # E1 C + B
    },
    "R": {  # GLONASS (NMEA system ID 2)
        "1": ("G1", "C"),  # L1 OF
        "3": ("G2", "C"),  # L2 OF
    },
    "C": {  # BeiDou (NMEA system ID 4)
        "1": ("B1I", "I"),  # B1I D1/D2
        "3": ("B1C", "X"),  # B1C
        "5": ("B2a", "X"),  # B2a
        "B": ("B2I", "I"),  # B2I D1/D2
    },
}

_GPS_PRN_MAX = 32
_SBAS_PRN_MAX = 64


def prn_to_sv(talker: str, prn: int) -> str | None:
    """Map an NMEA talker + PRN to a RINEX-style SV identifier.

    Returns
    -------
    str or None
        RINEX SV identifier (e.g. ``"G01"``, ``"R05"``),
        or ``None`` if the PRN cannot be mapped.
    """
    if talker == "GP":
        if 1 <= prn <= _GPS_PRN_MAX:
            return f"G{prn:02d}"
        if _GPS_PRN_MAX < prn <= _SBAS_PRN_MAX:
            return f"S{prn - _GPS_PRN_MAX:02d}"
        return None
    if talker == "GL":
        if 1 <= prn <= 32:
            return f"R{prn:02d}"
        if 65 <= prn <= 96:
            return f"R{prn - 64:02d}"
        return None
    if talker == "GA":
        if 1 <= prn <= 36:
            return f"E{prn:02d}"
        return None
    if talker == "GB":
        if 1 <= prn <= 63:
            return f"C{prn:02d}"
        return None
    if talker == "GN":
        if 1 <= prn <= 32:
            return f"G{prn:02d}"
        if 33 <= prn <= 64:
            return f"S{prn - 32:02d}"
        if 65 <= prn <= 96:
            return f"R{prn - 64:02d}"
        if 301 <= prn <= 336:
            return f"E{prn - 300:02d}"
        if 401 <= prn <= 463:
            return f"C{prn - 400:02d}"
        return None
    return None


def _sv_to_sid(sv: str, signal_id: str | None = None) -> str:
    """Build the signal ID string for a given SV.

    Parameters
    ----------
    sv : str
        RINEX-style SV identifier (e.g. ``"G01"``).
    signal_id : str or None
        Single hex digit from the GSV ``signalId`` field (u-blox NMEA 4.11).
        If provided, uses :data:`UBLOX_SIGNAL_ID_MAP` for band/code resolution.
        If ``None`` or not found, falls back to :data:`DEFAULT_NMEA_BAND_MAP`.
    """
    system = sv[0]
    if signal_id is not None:
        sig_map = UBLOX_SIGNAL_ID_MAP.get(system, {})
        band_code = sig_map.get(signal_id.upper())
        if band_code is not None:
            band, code = band_code
            return f"{sv}|{band}|{code}"
    # Fallback: default L/G/E/B1 band with X code when no signal ID
    band, code = DEFAULT_NMEA_BAND_MAP.get(system, ("L1", "X"))
    return f"{sv}|{band}|{code}"


# ---------------------------------------------------------------------------
# Epoch parsing helpers
# ---------------------------------------------------------------------------


def _parse_rmc_datetime(fields: list[str]) -> datetime | None:
    """Extract UTC datetime from an RMC sentence's fields."""
    if len(fields) < 9:
        return None
    utc_time = fields[0]
    date_str = fields[8]
    if not utc_time or not date_str:
        return None
    try:
        hour = int(utc_time[:2])
        minute = int(utc_time[2:4])
        sec_frac = float(utc_time[4:])
        second = int(sec_frac)
        microsecond = int((sec_frac - second) * 1_000_000)

        day = int(date_str[:2])
        month = int(date_str[2:4])
        year_2d = int(date_str[4:6])
        year = year_2d + 2000 if year_2d < 80 else year_2d + 1900

        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)
    except ValueError, IndexError:
        return None


def _parse_gga_time(fields: list[str]) -> tuple[int, int, float] | None:
    """Extract (hour, minute, seconds) from a GGA sentence's fields."""
    if not fields or not fields[0]:
        return None
    utc_time = fields[0]
    try:
        hour = int(utc_time[:2])
        minute = int(utc_time[2:4])
        seconds = float(utc_time[4:])
        return hour, minute, seconds
    except ValueError, IndexError:
        return None


# ---------------------------------------------------------------------------
# GSV satellite entry parsing
# ---------------------------------------------------------------------------


def _extract_gsv_signal_id(fields: list[str]) -> str | None:
    """Extract the u-blox signal ID from a GSV sentence's fields.

    The signal ID is the last field before ``*checksum``, present only
    when the number of fields after ``numSV`` (index 2) is not a multiple
    of 4 (i.e. there is one extra field beyond the satellite blocks).

    Rules (per user spec / u-blox convention):
    - 1 digit  → u-blox signal ID (hex), use :data:`UBLOX_SIGNAL_ID_MAP`
    - 2 digits → last satellite's SNR, no signal ID
    - absent   → no signal ID, use :data:`DEFAULT_NMEA_BAND_MAP`
    """
    # fields[0]=numMsg, [1]=msgNum, [2]=numSV, then 4-field sat blocks
    n_after_header = len(fields) - 3
    if n_after_header <= 0:
        return None
    extra = n_after_header % 4
    if extra == 1:
        candidate = fields[-1].strip()
        if len(candidate) == 1:
            return candidate
    return None


def _parse_gsv_satellites(
    talker: str,
    fields: list[str],
    signal_id: str | None = None,
) -> list[tuple[str, float | None]]:
    """Parse satellite entries from a single GSV sentence.

    Returns list of ``(sid, snr)`` pairs where *sid* is the full
    signal identifier (e.g. ``"G01|L1|C"``).
    """
    results: list[tuple[str, float | None]] = []
    # Satellite blocks start at index 3 and repeat every 4 fields
    sat_start = 3
    # Stop before the signal_id field if present
    end = len(fields) - 1 if signal_id is not None else len(fields)
    while sat_start < end:
        prn_str = fields[sat_start] if sat_start < end else ""
        snr_str = fields[sat_start + 3] if sat_start + 3 < end else ""

        if not prn_str:
            sat_start += 4
            continue

        try:
            prn = int(prn_str)
        except ValueError:
            sat_start += 4
            continue

        sv = prn_to_sv(talker, prn)
        if sv is None:
            sat_start += 4
            continue

        snr: float | None = None
        if snr_str:
            with contextlib.suppress(ValueError):
                snr = float(snr_str)

        sid = _sv_to_sid(sv, signal_id)
        results.append((sid, snr))
        sat_start += 4

    return results


# ---------------------------------------------------------------------------
# Parsed epoch container
# ---------------------------------------------------------------------------


class _ParsedEpoch:
    """Internal container for a parsed NMEA epoch."""

    __slots__ = ("satellites", "timestamp")

    def __init__(
        self,
        timestamp: datetime,
        satellites: dict[str, float | None],
    ) -> None:
        self.timestamp = timestamp
        self.satellites = satellites  # sid → snr (None = not tracked)


# ---------------------------------------------------------------------------
# Main reader
# ---------------------------------------------------------------------------


class NmeaObs(GNSSDataReader, BaseModel):
    """NMEA v4.00 sentence reader.

    Reads ``$xxRMC`` / ``$xxGGA`` for epoch timestamps and ``$xxGSV``
    for satellite SNR values.  Produces an ``xarray.Dataset`` compatible
    with the canvodpy pipeline.

    NMEA times are UTC. The epochs (and ``start_time``, ``end_time``) are
    GPS time: the UTC times plus the leap seconds of the date (18 s since
    2017). A time after the leap seconds known to canVODpy raises
    ``ValueError``.

    Parameters
    ----------
    fpath : Path
        Path to the NMEA file.
    aggregate_glonass_fdma : bool, default True
        Must be ``True``: GLONASS FDMA signals are always given as
        aggregated G1/G2 bands; ``False`` is refused.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    file_type: ClassVar[str] = "nmea"

    fpath: Path

    @field_validator("fpath")
    @classmethod
    def _file_must_exist(cls, v: Path) -> Path:
        v = Path(v)
        if not v.is_file():
            msg = f"File {v} does not exist."
            raise ValueError(msg)
        return v

    # ----- lazy parsing ----- #

    @cached_property
    def _parsed_epochs(self) -> list[_ParsedEpoch]:
        return self._parse_file()

    @cached_property
    def _file_hash_value(self) -> str:
        return hashing.file_hash(self.fpath)

    # ---- ABC implementations ---- #

    @property
    def file_hash(self) -> str:
        return self._file_hash_value

    @property
    def source_format(self) -> str:
        return "nmea"

    @property
    def start_time(self) -> datetime:
        return self._parsed_epochs[0].timestamp

    @property
    def end_time(self) -> datetime:
        return self._parsed_epochs[-1].timestamp

    @property
    def systems(self) -> list[str]:
        sys_set: set[str] = set()
        for ep in self._parsed_epochs:
            for sid in ep.satellites:
                sys_set.add(sid.split("|")[0][0])
        return sorted(sys_set)

    @property
    def num_epochs(self) -> int:
        return len(self._parsed_epochs)

    @property
    def num_satellites(self) -> int:
        svs: set[str] = set()
        for ep in self._parsed_epochs:
            for sid in ep.satellites:
                svs.add(sid.split("|")[0])
        return len(svs)

    # ---- iter_epochs ---- #

    def iter_epochs(self) -> Iterator[_ParsedEpoch]:
        """Yield ``_ParsedEpoch`` objects for every parsed epoch."""
        yield from self._parsed_epochs

    # ---- to_ds ---- #

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: Any,
    ) -> xr.Dataset:
        """Build an ``xarray.Dataset`` with ``(epoch, sid)`` dimensions.

        Parameters
        ----------
        keep_data_vars : list[str] | None
            Data variables to keep. For NMEA only ``["SNR"]`` is available.
        **kwargs
            Ignored.

        Returns
        -------
        xr.Dataset
        """
        epochs = self._parsed_epochs
        if not epochs:
            msg = "No epochs parsed from file"
            raise NmeaMissingSentenceError(msg)

        mapper = SignalIDMapper()

        # Collect all unique signal IDs (satellites already keyed by SID)
        all_sids: set[str] = set()
        for ep in epochs:
            all_sids.update(ep.satellites.keys())

        sorted_sids = sorted(all_sids)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}

        n_epochs = len(epochs)
        n_sids = len(sorted_sids)

        # Allocate data array
        snr_data = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["SNR"])

        timestamps: list[np.datetime64] = []
        for t_idx, ep in enumerate(epochs):
            timestamps.append(np.datetime64(ep.timestamp.replace(tzinfo=None), "ns"))
            for sid, snr in ep.satellites.items():
                if snr is None:
                    continue
                s_idx = sid_to_idx[sid]
                snr_data[t_idx, s_idx] = snr

        # Build coordinate arrays
        sv_list: list[str] = []
        system_list: list[str] = []
        band_list: list[str] = []
        code_list: list[str] = []
        freq_center_list: list[float] = []
        freq_min_list: list[float] = []
        freq_max_list: list[float] = []

        for sid in sorted_sids:
            sv_part, band, code = sid.split("|")
            system = sv_part[0]
            sv_list.append(sv_part)
            system_list.append(system)
            band_list.append(band)
            code_list.append(code)

            center = mapper.get_band_frequency(band)
            bw = mapper.get_band_bandwidth(band)

            if center is not None and bw is not None:
                bw_val = bw[0] if isinstance(bw, list) else bw
                freq_center_list.append(float(center))
                freq_min_list.append(float(center - bw_val / 2.0))
                freq_max_list.append(float(center + bw_val / 2.0))
            else:
                freq_center_list.append(np.nan)
                freq_min_list.append(np.nan)
                freq_max_list.append(np.nan)

        signal_id_coord = xr.DataArray(
            sorted_sids, dims=["sid"], attrs=COORDS_METADATA["sid"]
        )

        coords = {
            "epoch": ("epoch", timestamps, epoch_coord_attrs("GPS")),
            "sid": signal_id_coord,
            "sv": ("sid", sv_list, COORDS_METADATA["sv"]),
            "system": ("sid", system_list, COORDS_METADATA["system"]),
            "band": ("sid", band_list, COORDS_METADATA["band"]),
            "code": ("sid", code_list, COORDS_METADATA["code"]),
            "freq_center": (
                "sid",
                np.asarray(freq_center_list, dtype=DTYPES["freq_center"]),
                COORDS_METADATA["freq_center"],
            ),
            "freq_min": (
                "sid",
                np.asarray(freq_min_list, dtype=DTYPES["freq_min"]),
                COORDS_METADATA["freq_min"],
            ),
            "freq_max": (
                "sid",
                np.asarray(freq_max_list, dtype=DTYPES["freq_max"]),
                COORDS_METADATA["freq_max"],
            ),
        }

        ds = xr.Dataset(
            data_vars={
                "SNR": (["epoch", "sid"], snr_data, _NMEA_SNR_METADATA),
            },
            coords=coords,
            attrs={},
        )

        # Standard attributes (includes "File Hash")
        ds.attrs.update(self._build_attrs())

        # Normalize string dtypes for Icechunk / Zarr V3 compatibility
        for name in list(ds.coords) + list(ds.data_vars):
            if ds[name].dtype.kind in ("U", "T"):
                ds[name] = ds[name].astype(object)

        # Validate output structure
        if keep_data_vars is None:
            keep_data_vars = ["SNR"]
        validate_dataset(ds, required_vars=keep_data_vars)

        return ds

    # ---- internal parsing ---- #

    def _parse_file(self) -> list[_ParsedEpoch]:
        """Parse the NMEA file into epoch blocks.

        Grouping strategy: a new epoch starts whenever an RMC or GGA sentence
        is encountered with a different timestamp than the previous one.
        """
        lines = self.fpath.read_text(errors="replace").splitlines()

        relevant_prefixes = (
            "$GPRMC",
            "$GNRMC",
            "$GPGGA",
            "$GNGGA",
            "$GPGSV",
            "$GLGSV",
            "$GAGSV",
            "$GBGSV",
            "$GNGSV",
        )

        relevant_lines: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            for prefix in relevant_prefixes:
                if line.startswith(prefix):
                    try:
                        validate_nmea_checksum(line)
                    except NmeaChecksumError, NmeaInvalidSentenceError:
                        break
                    relevant_lines.append(line)
                    break

        if not relevant_lines:
            msg = "No RMC/GGA/GSV sentences found in file"
            raise NmeaMissingSentenceError(msg)

        # Parse into epoch blocks
        epochs: list[_ParsedEpoch] = []
        current_dt: datetime | None = None
        last_known_date: tuple[int, int, int] | None = None
        current_sats: dict[str, float | None] = {}

        def _flush_epoch() -> None:
            nonlocal current_dt, current_sats
            if current_dt is not None and current_sats:
                epochs.append(
                    _ParsedEpoch(
                        # NMEA times are UTC; every stored epoch is GPS time
                        timestamp=utc_to_gps(current_dt),
                        satellites=dict(current_sats),
                    )
                )
            current_sats = {}

        for line in relevant_lines:
            msg_id, fields = _parse_nmea_fields(line)
            sentence_type = msg_id[3:]  # e.g. "RMC", "GGA", "GSV"

            if sentence_type == "RMC":
                dt = _parse_rmc_datetime(fields)
                if dt is not None:
                    last_known_date = (dt.year, dt.month, dt.day)
                    if current_dt is None or dt != current_dt:
                        _flush_epoch()
                        current_dt = dt

            elif sentence_type == "GGA":
                hms = _parse_gga_time(fields)
                if hms is not None:
                    h, m, s = hms
                    sec = int(s)
                    usec = int((s - sec) * 1_000_000)
                    if last_known_date is not None:
                        yr, mo, dy = last_known_date
                        dt = datetime(yr, mo, dy, h, m, sec, usec, tzinfo=UTC)
                        if current_dt is None or dt != current_dt:
                            _flush_epoch()
                            current_dt = dt

            elif sentence_type == "GSV":
                talker = _talker_id(msg_id)
                signal_id = _extract_gsv_signal_id(fields)
                sat_entries = _parse_gsv_satellites(talker, fields, signal_id)
                for sid, snr in sat_entries:
                    existing = current_sats.get(sid)
                    if existing is None or (
                        snr is not None and (existing is None or snr > existing)
                    ):
                        current_sats[sid] = snr

        # Flush last epoch
        _flush_epoch()

        if not epochs:
            msg = "No valid epochs could be parsed from file"
            raise NmeaMissingSentenceError(msg)

        has_gsv = any(
            line.startswith(("$GPGSV", "$GLGSV", "$GAGSV", "$GBGSV", "$GNGSV"))
            for line in relevant_lines
        )
        if not has_gsv:
            msg = "No GSV sentences found in file: cannot extract SNR data"
            raise NmeaMissingSentenceError(msg)

        return epochs
