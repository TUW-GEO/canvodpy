"""RINEX v3.04 observation file reader.

Classes:
- Rnxv3Header: Parse RINEX v3 headers
- Rnxv3Obs: Main reader class, converts RINEX to xarray Dataset
"""

import functools
import json
import re
import warnings
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, cast

import georinex as gr
import numpy as np
import pint
import pytz
import structlog
import xarray as xr
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from canvod.readers.base import GNSSDataReader, validate_dataset
from canvod.readers.gnss_specs.constants import (
    EPOCH_RECORD_INDICATOR,
    UREG,
)
from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)
from canvod.readers.gnss_specs.exceptions import (
    IncompleteEpochError,
    InvalidEpochError,
    MissingEpochError,
)
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
    SNR_METADATA,
    epoch_coord_attrs,
    require_gps_time,
)
from canvod.readers.gnss_specs.models import (
    Observation,
    RINEX304ComplianceValidator,
    RnxObsFileModel,
    Rnxv3ObsEpochRecord,
    Rnxv3ObsEpochRecordCompletenessModel,
    Rnxv3ObsEpochRecordLineModel,
    RnxVersion3Model,
    Satellite,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.utils.tools import bytes_hash, deprecated

log = structlog.get_logger(__name__)

GLONASS_COD_PHS_MIN_COMPONENTS = 6
PGM_RUNBY_MIN_COMPONENTS = 4
TIME_OF_FIRST_OBS_MIN_COMPONENTS = 6
RECEIVER_COMPONENTS_SECOND = 2
POSITION_PARTS_MIN = 2
DELTA_PARTS_MIN = 2
OBS_SLICE_MIN_LEN = 6
OBS_SLICE_MAX_LEN = 16
OBS_SLICE_DECIMAL_POS = -6
LLI_SSI_PAIR_LEN = 2
# Observables an SSI may be taken from, by precedence (RINEX 3.04 Table A3
# notes 2-3): the phase's SSI, else the code's when no phase was observed.
_SSI_SOURCE_RANK = {"L": 2, "C": 1}
MIN_EPOCHS_FOR_INTERVAL = 2


def _str_to_object(ds: xr.Dataset) -> xr.Dataset:
    """Cast StringDType / fixed-width unicode coords and vars to object dtype.

    NumPy 2.x introduces ``StringDType`` (kind ``"T"``) which Zarr V3 /
    Icechunk cannot round-trip.  Fixed-width unicode (kind ``"U"``) also
    causes dtype mismatches on store append.  Normalizing to ``object``
    keeps behavior identical to NumPy 1.x.
    """
    for name in list(ds.coords) + list(ds.data_vars):
        if ds[name].dtype.kind in ("U", "T"):
            ds[name] = ds[name].astype(object)
    return ds


# --- Fast-path constants ---
_EPOCH_RE = re.compile(
    r"^>\s*(\d{4})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d+\.\d+)\s+(\d+)\s+(\d+)"
)

_OBS_VAL_END = 14

# A satellite line: the SV in columns 0-2, then one 16-character field per
# observation type of the system's SYS / # / OBS TYPES record.
_OBS_FIELD_LEN = 16
# The value of the standard field form (RINEX 3.04 Table A3: F14.3), so the
# decimal point is in column 10; ASCII digits only.
_OBS_VALUE_RE = re.compile(r" *-?[0-9]*\.[0-9]{3}")
# LLI and SSI characters of the standard field form (RINEX 3.04 Table A3:
# I1, blank if not known); any other character makes the field malformed.
_FLAG_OF_CHAR: dict[str, int | None] = {" ": None} | {str(d): d for d in range(10)}
_NOT_A_FLAG = -1

ObsField = tuple[float | None, int | None, int | None]


@functools.cache
def _get_constellation_svs(system: str) -> tuple[str, ...]:
    """Return the static SV identifiers for a GNSS system.

    Taken from the constellation models that also define the global sid
    space (``pad_to_global_sid()``), so the reader cannot keep a stale copy:
    a separate table here once limited SBAS to S01-S36 and silently dropped
    real GEOs such as EGNOS PRN 148 (S48) at read time.
    """
    models = {
        "G": GPS,
        "E": GALILEO,
        "R": GLONASS,
        "C": BEIDOU,
        "J": QZSS,
        "S": SBAS,
        "I": IRNSS,
    }
    model = models.get(system)
    return tuple(model().svs) if model is not None else ()


def _parse_obs_fast(slice_text: str) -> tuple[float | None, int | None, int | None]:
    """Parse RINEX observation slice using direct string indexing.

    Standard RINEX v3 format: 14 chars value + 1 char LLI + 1 char SSI = 16 chars.
    """
    if len(slice_text) < OBS_SLICE_MIN_LEN:
        return None, None, None

    try:
        val_end = min(_OBS_VAL_END, len(slice_text))
        val_str = slice_text[:val_end].strip()
        if not val_str:
            return None, None, None

        value = float(val_str)

        obs_lli = None
        obs_ssi = None
        if len(slice_text) > _OBS_VAL_END:
            c = slice_text[_OBS_VAL_END]
            if c.isdigit():
                obs_lli = int(c)
        if len(slice_text) > _OBS_VAL_END + 1:
            c = slice_text[_OBS_VAL_END + 1]
            if c.isdigit():
                obs_ssi = int(c)

        return value, obs_lli, obs_ssi
    except ValueError:
        return None, None, None


# RINEX 3.04 Table A2, TIME OF FIRST OBS: time systems, and the default of a
# single-system file.
_TIME_SYSTEMS = frozenset({"GPS", "GLO", "GAL", "QZS", "BDT", "IRN"})
_DEFAULT_TIME_SYSTEM = {
    "G": "GPS",
    "R": "GLO",
    "E": "GAL",
    "J": "QZS",
    "C": "BDT",
    "I": "IRN",
}

# --- Shared by both dataset builders ---
RinexV3Parser = Literal["validated", "unvalidated_fast"]

_OBS_VAR_ORDER = ("SNR", "Pseudorange", "Phase", "Doppler", "LLI", "SSI")
_OBS_VARS = frozenset(_OBS_VAR_ORDER)
# Rank of the observable each SSI value came from, so phase outranks code
# regardless of the header's observable order. Internal, never in a dataset.
_SSI_RANK_KEY = "_ssi_rank"

_UNVALIDATED_PARSER_MESSAGE = (
    "DANGEROUS: the unvalidated fast RINEX v3 parser is in use. It does not "
    "validate epochs, satellite IDs, satellite counts or observation fields, "
    "so corrupted records can enter the dataset as partial or wrong values. "
    "canVODpy takes no responsibility for its results; checking the input "
    "files is entirely the user's responsibility. Use parser='validated' "
    "(config: processing.params.rinex_v3_parser: validated) unless the files "
    "were verified otherwise."
)


class UnvalidatedParserWarning(UserWarning):
    """Emitted on every use of the unvalidated fast RINEX v3 parser."""


def _allocate_obs_arrays(
    n_epochs: int, n_sids: int, kept_vars: frozenset[str]
) -> dict[str, np.ndarray]:
    """Allocate the fill-valued (epoch, sid) arrays of the kept variables."""
    arrays: dict[str, np.ndarray] = {}
    for var in _OBS_VAR_ORDER:
        if var in kept_vars:
            fill = -1 if var in ("LLI", "SSI") else np.nan
            arrays[var] = np.full((n_epochs, n_sids), fill, dtype=DTYPES[var])
    if "SSI" in arrays:
        arrays[_SSI_RANK_KEY] = np.zeros((n_epochs, n_sids), dtype=np.int8)
    return arrays


def _store_observation(
    arrays: dict[str, np.ndarray],
    t_idx: int,
    s_idx: int,
    obs_type: str,
    value: float,
    lli: int | None,
    ssi: int | None,
) -> None:
    """Store one observation; the single definition of the storage rules.

    An SNR of 0 means not observed and stays missing. RINEX 3.04 Table A3
    notes 1-3: the LLI belongs to the phase observation only; the SSI to the
    phase, or to the code when the signal has no phase. Phase, code, Doppler
    and SNR share a sid, so flags on other observables must not overwrite the
    phase's.
    """
    var = _VAR_OF_OBS_TYPE.get(obs_type)
    if var is not None and var in arrays and not (var == "SNR" and value == 0):
        arrays[var][t_idx, s_idx] = value
    if lli is not None and obs_type == "L" and "LLI" in arrays:
        arrays["LLI"][t_idx, s_idx] = lli
    if ssi is not None and "SSI" in arrays:
        rank = _SSI_SOURCE_RANK.get(obs_type, 0)
        if rank > arrays[_SSI_RANK_KEY][t_idx, s_idx]:
            arrays["SSI"][t_idx, s_idx] = ssi
            arrays[_SSI_RANK_KEY][t_idx, s_idx] = rank


_VAR_OF_OBS_TYPE = {"S": "SNR", "C": "Pseudorange", "L": "Phase", "D": "Doppler"}


def _obs_types_to_read(kept_vars: frozenset[str]) -> frozenset[str]:
    """Return the observation types whose fields the kept variables need.

    A variable needs the fields of its own type; the LLI those of the phase,
    the SSI those of the phase and the code (see :func:`_store_observation`).
    Fields of other types are never stored, so they are not read.
    """
    types = {t for t, var in _VAR_OF_OBS_TYPE.items() if var in kept_vars}
    if "LLI" in kept_vars:
        types.add("L")
    if "SSI" in kept_vars:
        types.update(_SSI_SOURCE_RANK)
    return frozenset(types)


def _epoch_datetime64(
    year: int, month: int, day: int, hour: int, minute: int, seconds: float
) -> np.datetime64:
    """Return a RINEX v3 epoch as ``datetime64[ns]``, as written in the file.

    The seconds field is F11.7 (RINEX 3.04 Table A3), so the time is rounded
    to its 100 ns resolution; truncating a float such as 0.1 would lose
    100 ns. Seconds outside [0, 60) raise ``ValueError``, like an invalid
    calendar date.
    """
    if not 0 <= seconds < 60:
        msg = f"second must be in [0, 60), not {seconds}"
        raise ValueError(msg)
    start_of_minute = np.datetime64(datetime(year, month, day, hour, minute), "ns")
    return start_of_minute + np.timedelta64(round(seconds * 1e7) * 100, "ns")


class Rnxv3Header(BaseModel):
    """Enhanced RINEX v3 header following the original implementation logic.

    Key changes from previous version:
    - date field is now datetime (like original)
    - Uses the original parsing logic for __get_pgm_runby_date

    Notes
    -----
    This is a Pydantic `BaseModel` configured with `ConfigDict` (frozen,
    validate_assignment, arbitrary_types_allowed, str_strip_whitespace). Prefer
    :meth:`from_file` for construction.

    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )

    # Required fields
    fpath: Path
    version: float
    filetype: str
    rinextype: str
    systems: str
    pgm: str
    run_by: str
    date: datetime
    marker_name: str
    observer: str
    agency: str
    receiver_number: str
    receiver_type: str
    receiver_version: str
    antenna_number: str
    antenna_type: str
    approx_position: list[pint.Quantity]
    antenna_position: list[pint.Quantity]
    t0: dict[str, datetime]
    signal_strength_unit: pint.Unit | str
    obs_codes_per_system: dict[str, list[str]]

    # Optional fields with defaults
    comment: str | None = None
    marker_number: int | None = None
    marker_type: str | None = None
    glonass_cod: str | None = None
    glonass_phs: str | None = None
    glonass_bis: str | None = None
    glonass_slot_freq_dict: dict[str, int] = Field(default_factory=dict)
    leap_seconds: pint.Quantity | None = None
    system_phase_shift: dict[str, dict[str, float | None]] = Field(default_factory=dict)

    @field_validator("marker_number", mode="before")
    @classmethod
    def parse_marker_number(cls, v: object) -> int | None:
        """Convert empty strings to None, parse valid integers."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        try:
            if not isinstance(v, (str, int, float)):
                return None
            return int(v)
        except ValueError, TypeError:
            return None

    @classmethod
    def from_file(cls, fpath: Path) -> Self:
        """Create header from a RINEX file."""
        # External validation models handle file and version checks
        _ = RnxObsFileModel(fpath=fpath)

        try:
            header = gr.rinexheader(fpath)
        except (OSError, ValueError, TypeError) as e:
            msg = f"Failed to read RINEX header: {e}"
            raise ValueError(msg) from e

        cast(Any, RnxVersion3Model).version_must_be_3(header["version"])

        # Parse and create instance using original logic
        parsed_data = cls._parse_header_data(cast(dict[str, Any], header), fpath)
        return cls.model_validate(parsed_data)

    @staticmethod
    def _parse_header_data(
        header: dict[str, Any],
        fpath: Path,
    ) -> dict[str, Any]:
        """Parse raw header into structured data using original logic.

        Parameters
        ----------
        header : dict[str, Any]
            Raw header dictionary returned by `georinex`.
        fpath : Path
            Path to the RINEX file.

        Returns
        -------
        dict[str, Any]
            Parsed header data suitable for model validation.

        """
        data = {
            "fpath": fpath,
            "version": header.get("version", 3.0),
            "filetype": header.get("filetype", ""),
            "rinextype": header.get("rinextype", ""),
            "systems": header.get("systems", ""),
        }

        if "PGM / RUN BY / DATE" in header:
            pgm, run_by, date_dt = Rnxv3Header._get_pgm_runby_date(header)
            data.update(
                {
                    "pgm": pgm,
                    "run_by": run_by,
                    "date": date_dt,  # This is now a datetime object
                }
            )
        else:
            data.update(
                {
                    "pgm": "",
                    "run_by": "",
                    "date": datetime.now(UTC),  # Default to current time
                }
            )

        if "OBSERVER / AGENCY" in header:
            observer, agency = Rnxv3Header._get_observer_agency(header)
            data.update({"observer": observer, "agency": agency})
        else:
            data.update({"observer": "", "agency": ""})

        if "REC # / TYPE / VERS" in header:
            rec_num, rec_type, rec_version = Rnxv3Header._get_receiver_num_type_version(
                header
            )
            data.update(
                {
                    "receiver_number": rec_num,
                    "receiver_type": rec_type,
                    "receiver_version": rec_version,
                }
            )
        else:
            data.update(
                {"receiver_number": "", "receiver_type": "", "receiver_version": ""}
            )

        if "ANT # / TYPE" in header:
            ant_num, ant_type = Rnxv3Header._get_antenna_num_type(header)
            data.update({"antenna_number": ant_num, "antenna_type": ant_type})
        else:
            data.update({"antenna_number": "", "antenna_type": ""})

        # Parse positions with safe fallbacks
        pos_parts = header.get("APPROX POSITION XYZ", "0 0 0").split()
        delta_parts = header.get("ANTENNA: DELTA H/E/N", "0 0 0").split()

        def safe_float(s: str, default: float = 0.0) -> float:
            try:
                return float(s)
            except ValueError, TypeError:
                return default

        pos_y = (
            safe_float(pos_parts[1]) * UREG.meters
            if len(pos_parts) > 1
            else 0.0 * UREG.meters
        )
        pos_z = (
            safe_float(pos_parts[2]) * UREG.meters
            if len(pos_parts) > POSITION_PARTS_MIN
            else 0.0 * UREG.meters
        )
        ant_y = (
            safe_float(delta_parts[1]) * UREG.meters
            if len(delta_parts) > 1
            else 0.0 * UREG.meters
        )
        ant_z = (
            safe_float(delta_parts[2]) * UREG.meters
            if len(delta_parts) > DELTA_PARTS_MIN
            else 0.0 * UREG.meters
        )

        data.update(
            {
                "approx_position": [
                    safe_float(pos_parts[0]) * UREG.meters,
                    pos_y,
                    pos_z,
                ],
                "antenna_position": [
                    safe_float(delta_parts[0]) * UREG.meters,
                    ant_y,
                    ant_z,
                ],
            }
        )

        data["t0"] = Rnxv3Header._get_time_of_first_obs(
            header, file_system=data["systems"]
        )

        # Signal strength unit
        data["signal_strength_unit"] = Rnxv3Header._get_signal_strength_unit(header)

        # Basic fields
        data.update(
            {
                "comment": header.get("COMMENT"),
                "marker_name": header.get("MARKER NAME", "").strip(),
                "marker_number": header.get("MARKER NUMBER"),
                "marker_type": header.get("MARKER TYPE"),
                "obs_codes_per_system": header.get("fields", {}),
            }
        )

        # Optional GLONASS fields using original methods
        if "GLONASS COD/PHS/BIS" in header:
            cod, phs, bis = Rnxv3Header._get_glonass_cod_phs_bis(header)
            data.update({"glonass_cod": cod, "glonass_phs": phs, "glonass_bis": bis})

        if "GLONASS SLOT / FRQ #" in header:
            data["glonass_slot_freq_dict"] = Rnxv3Header._get_glonass_slot_freq_num(
                header
            )

        # Leap seconds
        if "LEAP SECONDS" in header:
            leap_parts = header["LEAP SECONDS"].split()
            if leap_parts and leap_parts[0].lstrip("-").isdigit():
                data["leap_seconds"] = int(leap_parts[0]) * UREG.seconds

        # System phase shift using original method
        if "SYS / PHASE SHIFT" in header:
            data["system_phase_shift"] = Rnxv3Header._get_sys_phase_shift(header)
        else:
            data["system_phase_shift"] = {}

        return data

    @staticmethod
    def _get_pgm_runby_date(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, datetime]:
        """Parse ``PGM / RUN BY / DATE`` into program, run_by, and datetime.

        Based on the original __get_pgm_runby_date method.
        """
        header_value = header_dict.get("PGM / RUN BY / DATE", "")
        components = header_value.split()

        if not components:
            return "", "", datetime.now(UTC)

        pgm = components[0]
        run_by = components[1] if len(components) > PGM_RUNBY_MIN_COMPONENTS else ""

        # Original logic for extracting date components
        date = (
            [components[-3], components[-2], components[-1]]
            if len(components) > 1
            else None
        )

        if date:
            try:
                # Original parsing logic
                dt = datetime.strptime(
                    date[0] + date[1],
                    "%Y%m%d%H%M%S",
                )
                tz = pytz.timezone(date[2])  # e.g., "UTC"
                localized_date = tz.localize(dt)
                return pgm, run_by, localized_date
            except (ValueError, TypeError) as e:
                print(f"Warning: Could not parse date components {date}: {e}")
                return pgm, run_by, datetime.now(UTC)
        else:
            return pgm, run_by, datetime.now(UTC)

    @staticmethod
    def _get_observer_agency(header_dict: dict[str, Any]) -> tuple[str, str]:
        """Parse ``OBSERVER / AGENCY`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str]
            (observer, agency).

        """
        header_value = header_dict.get("OBSERVER / AGENCY", "")
        try:
            observer, agency = header_value.split(maxsplit=1)
            return observer, agency
        except ValueError:
            return "", ""

    @staticmethod
    def _get_receiver_num_type_version(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Parse ``REC # / TYPE / VERS`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str, str]
            (receiver_number, receiver_type, receiver_version).

        """
        header_value = header_dict.get("REC # / TYPE / VERS", "")
        components = header_value.split()

        if not components:
            return "", "", ""
        if len(components) == 1:
            return components[0], "", ""
        if len(components) == RECEIVER_COMPONENTS_SECOND:
            return components[0], components[1], ""
        return components[0], " ".join(components[1:-1]), components[-1]

    @staticmethod
    def _get_antenna_num_type(header_dict: dict[str, Any]) -> tuple[str, str]:
        """Parse ``ANT # / TYPE`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str]
            (antenna_number, antenna_type).

        """
        header_value = header_dict.get("ANT # / TYPE", "")
        components = header_value.split()

        if not components:
            return "", ""
        if len(components) == 1:
            return components[0], ""
        return components[0], " ".join(components[1:])

    @staticmethod
    def _get_time_of_first_obs(
        header_dict: dict[str, Any],
        file_system: str = "",
    ) -> dict[str, datetime]:
        """Parse the mandatory ``TIME OF FIRST OBS`` record.

        RINEX 3.04 Table A2: ``5I6,F13.7,5X,A3``, the time of the first
        observation record followed by its time system (GPS, GLO, GAL, QZS,
        BDT, IRN). The time system is compulsory in mixed files; a
        single-system file defaults to its own system. The time is returned
        as written, in that time system, like the epochs of the file; no
        conversion to another time scale is made.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.
        file_system : str, optional
            System letter of ``RINEX VERSION / TYPE`` (``"M"`` for mixed),
            used for the default time system.

        Returns
        -------
        dict[str, datetime]
            ``{time_system: time of first observation}``. The datetime carries
            ``tzinfo=UTC`` only to be timezone-aware; its time scale is the key.

        Raises
        ------
        ValueError
            If the record is missing or malformed, or if the time system is
            neither given nor implied by a single-system file.

        """
        header_value = header_dict.get("TIME OF FIRST OBS")
        if header_value is None:
            msg = "mandatory header record TIME OF FIRST OBS is missing"
            raise ValueError(msg)
        components = str(header_value).split()
        if len(components) < TIME_OF_FIRST_OBS_MIN_COMPONENTS:
            msg = f"malformed TIME OF FIRST OBS record: {header_value!r}"
            raise ValueError(msg)

        try:
            year, month, day, hour, minute = map(int, components[:5])
            seconds = float(components[5])
        except ValueError as e:
            msg = f"malformed TIME OF FIRST OBS record: {header_value!r}"
            raise ValueError(msg) from e

        if len(components) > TIME_OF_FIRST_OBS_MIN_COMPONENTS:
            time_system = components[TIME_OF_FIRST_OBS_MIN_COMPONENTS]
        else:
            time_system = _DEFAULT_TIME_SYSTEM.get(file_system.strip())
        if time_system not in _TIME_SYSTEMS:
            msg = (
                f"TIME OF FIRST OBS has no valid time system ({time_system!r}); "
                "it is compulsory in mixed files"
            )
            raise ValueError(msg)

        ts = _epoch_datetime64(year, month, day, hour, minute, seconds)
        return {time_system: ts.astype("datetime64[us]").item().replace(tzinfo=UTC)}

    @staticmethod
    def _get_glonass_cod_phs_bis(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Parse ``GLONASS COD/PHS/BIS`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str, str]
            (glonass_cod, glonass_phs, glonass_bis).

        """
        header_value = header_dict.get("GLONASS COD/PHS/BIS", "")
        components = header_value.split()

        if len(components) >= GLONASS_COD_PHS_MIN_COMPONENTS:
            c1c = f"{components[0]} {components[1]}"
            c2c = f"{components[2]} {components[3]}"
            c2p = f"{components[4]} {components[5]}"
            return c1c, c2c, c2p
        return "", "", ""

    @staticmethod
    def _get_glonass_slot_freq_num(
        header_dict: dict[str, Any],
    ) -> dict[str, int]:
        """Parse ``GLONASS SLOT / FRQ #`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        dict[str, int]
            Mapping of slot to frequency number.

        """
        header_value = header_dict.get("GLONASS SLOT / FRQ #", "")
        components = header_value.split()

        result = {}
        for i in range(1, len(components), 2):  # Skip first component
            if i + 1 < len(components):
                try:
                    slot = components[i]
                    freq_num = int(components[i + 1])
                    result[slot] = freq_num
                except ValueError, IndexError:
                    continue

        return result

    @staticmethod
    def _get_sys_phase_shift(
        header_dict: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        """Parse ``SYS / PHASE SHIFT`` records.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        dict[str, dict[str, float | None]]
            Mapping of system to signal phase shifts.

        """
        header_value = header_dict.get("SYS / PHASE SHIFT", "")
        components = header_value.split()

        sys_phase_shift_dict = defaultdict(dict)
        i = 0

        while i < len(components):
            if i >= len(components):
                break

            system_abbrv = components[i]

            if i + 1 >= len(components):
                break
            signal_code = components[i + 1]

            # Check if there's a phase shift value
            phase_shift = None
            if (
                i + 2 < len(components)
                and components[i + 2].replace(".", "", 1).replace("-", "", 1).isdigit()
            ):
                try:
                    phase_shift = float(components[i + 2])
                    i += 3
                except ValueError, TypeError:
                    i += 2
            else:
                i += 2

            sys_phase_shift_dict[system_abbrv][signal_code] = phase_shift

        return {k: dict(v) for k, v in sys_phase_shift_dict.items()}

    @staticmethod
    def _get_signal_strength_unit(
        header_dict: dict[str, Any],
    ) -> pint.Unit | str:
        """Parse ``SIGNAL STRENGTH UNIT`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        pint.Unit or str
            Parsed unit or a default string.

        """
        header_value = header_dict.get("SIGNAL STRENGTH UNIT", "").strip()

        # Using match statement like original
        match header_value:
            case "DBHZ":
                return UREG.dBHz
            case "DB":
                return UREG.dB
            case _:
                return header_value if header_value else "dB"

    @property
    def time_system(self) -> str:
        """Time system of all time tags in the file (``TIME OF FIRST OBS``)."""
        return next(iter(self.t0))

    @property
    def is_mixed_systems(self) -> bool:
        """Check if the RINEX file contains mixed GNSS systems."""
        return self.systems == "M"

    def __repr__(self) -> str:
        """Return a concise representation for debugging."""
        return (
            f"Rnxv3Header(file='{self.fpath.name}', "
            f"version={self.version}, "
            f"systems='{self.systems}')"
        )

    def __str__(self) -> str:
        """Return a human-readable header summary."""
        systems_str = "Mixed" if self.systems == "M" else self.systems
        return (
            f"RINEX v{self.version} Header\n"
            f"  File: {self.fpath.name}\n"
            f"  Marker: {self.marker_name}\n"
            f"  Systems: {systems_str}\n"
            f"  Receiver: {self.receiver_type}\n"
            f"  Date: {self.date.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        )


class Rnxv3Obs(GNSSDataReader):
    """RINEX v3.04 observation reader.

    Attributes
    ----------
    fpath : Path
        Path to the RINEX observation file.
    polarization : str, default "RHCP"
        Polarization label for observables.
    completeness_mode : {"strict", "warn", "off"}, default "strict"
        Behavior when epoch completeness checks fail.
    expected_dump_interval : str or pint.Quantity, optional
        Expected file dump interval for completeness validation.
    expected_sampling_interval : str or pint.Quantity, optional
        Expected sampling interval for completeness validation.
    apply_overlap_filter : bool, default False
        Whether to filter overlapping signal groups.
    overlap_preferences : dict[str, str], optional
        Preferred signals for overlap resolution.
    aggregate_glonass_fdma : bool, optional
        Whether to aggregate GLONASS FDMA channels.

    Notes
    -----
    Inherits ``fpath``, its validator, and ``arbitrary_types_allowed``
    from :class:`GNSSDataReader`.

    """

    model_config = ConfigDict(frozen=True)

    polarization: str = "RHCP"

    completeness_mode: Literal["strict", "warn", "off"] = "strict"
    expected_dump_interval: str | pint.Quantity | None = None
    expected_sampling_interval: str | pint.Quantity | None = None

    apply_overlap_filter: bool = False
    overlap_preferences: dict[str, str] | None = None

    file_type: ClassVar[str] = "rnx"
    per_channel_glonass: ClassVar[bool] = True

    # Pydantic exempts PrivateAttr fields from frozen=True immutability, but ty
    # doesn't model that and flags every assignment below as read-only.
    _header: Rnxv3Header = PrivateAttr()
    _signal_mapper: SignalIDMapper = PrivateAttr()

    _lines: list[str] = PrivateAttr()
    _file_hash: str = PrivateAttr()
    _cached_epoch_batches: list[tuple[int, int]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _post_init(self) -> Self:
        """Initialize derived state after validation."""
        # PrivateAttr()-declared attributes are mutable even on frozen=True
        # Pydantic models -- only public fields are frozen. ty's pydantic
        # support doesn't model this and treats the assignment inside the
        # validator that first sets them as establishing a read-only
        # "property".
        # Load header once
        self._header = Rnxv3Header.from_file(self.fpath)

        # Initialize signal mapper
        self._signal_mapper = SignalIDMapper(
            aggregate_glonass_fdma=self.aggregate_glonass_fdma
        )

        # Optionally auto-check completeness
        if self.completeness_mode != "off":
            try:
                self.validate_epoch_completeness(
                    dump_interval=self.expected_dump_interval,
                    sampling_interval=self.expected_sampling_interval,
                )
            except MissingEpochError as e:
                if self.completeness_mode == "strict":
                    raise
                warnings.warn(str(e), RuntimeWarning, stacklevel=2)

        # Cache file lines
        self._lines = self._load_file()

        return self

    @property
    def header(self) -> Rnxv3Header:
        """Expose validated header (read-only).

        Returns
        -------
        Rnxv3Header
            Parsed and validated RINEX header.

        """
        return self._header

    def __str__(self) -> str:
        """Return a human-readable summary."""
        return (
            f"{self.__class__.__name__}:\n"
            f"  File Path: {self.fpath}\n"
            f"  Header: {self.header}\n"
            f"  Polarization: {self.polarization}\n"
        )

    def __repr__(self) -> str:
        """Return a concise representation for debugging."""
        return f"{self.__class__.__name__}(fpath={self.fpath})"

    def _load_file(self) -> list[str]:
        """Read file once, cache lines, and compute hash.

        Returns
        -------
        list[str]
            File contents split into lines.

        """
        if not hasattr(self, "_lines"):
            data = self.fpath.read_bytes()  # binary mode for consistent hash
            self._lines = data.decode("utf-8", errors="replace").splitlines()
            self._file_hash = bytes_hash(data)
        return self._lines

    @property
    def source_format(self) -> str:
        return "rinex3"

    @property
    def file_hash(self) -> str:
        """Return cached SHA256 short hash of the file content.

        Returns
        -------
        str
            16-character short hash for deduplication.

        """
        return self._file_hash

    @property
    def start_time(self) -> datetime:
        """Return start time of observations from header.

        Returns
        -------
        datetime
            First observation timestamp.

        """
        return min(self.header.t0.values())

    @property
    def end_time(self) -> datetime:
        """Return end time of observations from last epoch.

        Returns
        -------
        datetime
            Last observation timestamp.

        """
        last_epoch = None
        for epoch in self.iter_epochs():
            last_epoch = epoch
        if last_epoch:
            return self.get_datetime_from_epoch_record_info(last_epoch.info)
        return self.start_time

    @property
    def systems(self) -> list[str]:
        """Return list of GNSS systems in file.

        Returns
        -------
        list of str
            System identifiers (G, R, E, C, J, S, I).

        """
        if self.header.systems == "M":
            return list(self.header.obs_codes_per_system.keys())
        return [self.header.systems]

    @property
    def num_epochs(self) -> int:
        """Return number of epochs in file.

        Returns
        -------
        int
            Total epoch count.

        """
        return len(list(self.get_epoch_record_batches()))

    @property
    def num_satellites(self) -> int:
        """Return total number of unique satellites observed.

        Returns
        -------
        int
            Count of unique satellite vehicles across all systems.

        """
        satellites = set()
        for epoch in self.iter_epochs():
            for sat in epoch.data:
                satellites.add(sat.sv)
        return len(satellites)

    def get_epoch_record_batches(
        self, epoch_record_indicator: str = EPOCH_RECORD_INDICATOR
    ) -> list[tuple[int, int]]:
        """Get the start and end line numbers for each epoch in the file.

        Parameters
        ----------
        epoch_record_indicator : str, default '>'
            Character marking epoch record lines.

        Returns
        -------
        list of tuple of int
            List of (start_line, end_line) pairs for each epoch.

        """
        if self._cached_epoch_batches is not None:
            return self._cached_epoch_batches

        lines = self._load_file()
        starts = [
            i for i, line in enumerate(lines) if line.startswith(epoch_record_indicator)
        ]
        starts.append(len(lines))  # Add EOF
        # PrivateAttr, mutable despite frozen=True -- see _post_init's comment.
        self._cached_epoch_batches = [
            (start, starts[i + 1])
            for i, start in enumerate(starts)
            if i + 1 < len(starts)
        ]
        return self._cached_epoch_batches

    @deprecated(
        "`Rnxv3Obs.parse_observation_slice` is left over from development and "
        "will be removed with the next major version. Observation fields are "
        "read strictly by `Rnxv3Obs.iter_epochs()` and `Rnxv3Obs.to_ds()`; "
        "use those instead."
    )
    def parse_observation_slice(
        self,
        slice_text: str,
    ) -> tuple[float | None, int | None, int | None]:
        """Parse a RINEX observation slice into value, LLI, and SSI.

        Enhanced to handle both standard 16-character format and
        variable-length records.

        Parameters
        ----------
        slice_text : str
            Observation slice to parse.

        Returns
        -------
        tuple[float | None, int | None, int | None]
            Parsed (value, LLI, SSI) tuple.

        """
        if not slice_text or not slice_text.strip():
            return None, None, None

        try:
            # Method 1: Standard RINEX format with decimal at position -6
            if (
                len(slice_text) >= OBS_SLICE_MIN_LEN
                and len(slice_text) <= OBS_SLICE_MAX_LEN
                and slice_text[OBS_SLICE_DECIMAL_POS] == "."
            ):
                slice_chars = list(slice_text)
                ssi = slice_chars.pop(-1) if len(slice_chars) > 0 else ""
                lli = slice_chars.pop(-1) if len(slice_chars) > 0 else ""

                # Convert LLI and SSI
                lli = int(lli) if lli.strip() and lli.isdigit() else None
                ssi = int(ssi) if ssi.strip() and ssi.isdigit() else None

                # Convert value
                value_str = "".join(slice_chars).strip()
                if value_str:
                    value = float(value_str)
                    return value, lli, ssi

        except ValueError, IndexError:
            pass

        try:
            # Method 2: Flexible parsing for variable-length records
            slice_trimmed = slice_text.strip()
            if not slice_trimmed:
                return None, None, None

            # Look for a decimal point to identify the numeric value
            if "." in slice_trimmed:
                # Find the main numeric value (supports negative numbers)
                number_match = re.search(r"(-?\d+\.\d+)", slice_trimmed)

                if number_match:
                    value = float(number_match.group(1))

                    # Check for LLI/SSI indicators after the number
                    remaining_part = slice_trimmed[number_match.end() :].strip()
                    lli = None
                    ssi = None

                    # Parse remaining characters as potential LLI/SSI
                    if remaining_part:
                        # Could be just SSI, or LLI followed by SSI
                        if len(remaining_part) == 1:
                            # Just one indicator - assume it's SSI
                            if remaining_part.isdigit():
                                ssi = int(remaining_part)
                        elif len(remaining_part) >= LLI_SSI_PAIR_LEN:
                            # Two or more characters - take last two as LLI, SSI
                            lli_char = remaining_part[-2]
                            ssi_char = remaining_part[-1]

                            if lli_char.isdigit():
                                lli = int(lli_char)
                            if ssi_char.isdigit():
                                ssi = int(ssi_char)

                    return value, lli, ssi

        except ValueError, IndexError:
            pass

        # Method 3: Last resort - try simple float parsing
        try:
            simple_value = float(slice_text.strip())
            return simple_value, None, None
        except ValueError:
            pass

        return None, None, None

    def _read_observation_field(self, field: str) -> ObsField:
        """Return the (value, LLI, SSI) of one 16-character observation field.

        A field in the standard form (F14.3 with the decimal point in column
        10, then LLI and SSI, each blank or a digit) gives its value and
        flags. A fully blank field is a missing observation.

        Raises
        ------
        InvalidEpochError
            If the field is neither blank nor in the standard form.

        """
        if field.isspace():
            return None, None, None
        lli = _FLAG_OF_CHAR.get(field[14], _NOT_A_FLAG)
        ssi = _FLAG_OF_CHAR.get(field[15], _NOT_A_FLAG)
        if (
            lli == _NOT_A_FLAG
            or ssi == _NOT_A_FLAG
            or _OBS_VALUE_RE.fullmatch(field, 0, _OBS_VAL_END) is None
        ):
            msg = f"Malformed observation field: {field!r}"
            raise InvalidEpochError(msg)
        return float(field[:_OBS_VAL_END]), lli, ssi

    def _read_satellite_line(
        self, line: str, obs_types: frozenset[str] | None = None
    ) -> tuple[Satellite, list[ObsField]]:
        """Return the satellite and the (value, LLI, SSI) per observation type.

        The :class:`Satellite` model validates the SV; its observations are
        not filled in (see :meth:`_add_observations`).

        One entry per observation type of the system's ``SYS / # / OBS
        TYPES`` record, in its order. Fields missing at the end of a short
        line are empty; text beyond the last field is ignored.

        Parameters
        ----------
        line : str
            The satellite line.
        obs_types : frozenset of str or None
            If given, only the fields whose observation type (first letter of
            the code) is in it are read and checked; the others are returned
            empty. ``None`` reads every field.

        Raises
        ------
        ValueError
            If the SV is not a valid satellite identifier (pydantic
            ``ValidationError``).
        InvalidEpochError
            If the system has no ``SYS / # / OBS TYPES`` record, or a field
            is neither blank nor in the standard form.

        """
        sv = line[:3].strip()
        satellite = Satellite(sv=sv)
        obs_codes = self.header.obs_codes_per_system.get(sv[0])
        if obs_codes is None:
            msg = f"{sv}: system {sv[0]} has no SYS / # / OBS TYPES header record"
            raise InvalidEpochError(msg)

        data_part = line[3:]
        n_chars = len(data_part)
        fields: list[ObsField] = []
        for i, obs_code in enumerate(obs_codes):
            col = i * _OBS_FIELD_LEN
            if col >= n_chars or (
                obs_types is not None and obs_code[0] not in obs_types
            ):
                fields.append((None, None, None))
            else:
                field = data_part[col : col + _OBS_FIELD_LEN].ljust(_OBS_FIELD_LEN)
                fields.append(self._read_observation_field(field))
        return satellite, fields

    def process_satellite_data(self, s: str) -> Satellite:
        """Process satellite data line into a Satellite object with observations.

        Reads the line with the rules of the dataset builder (see
        :meth:`_read_satellite_line`); a field that is neither blank nor in
        the standard form raises :class:`InvalidEpochError`.
        """
        satellite, fields = self._read_satellite_line(s)
        self._add_observations(satellite, fields)
        return satellite

    def _add_observations(self, satellite: Satellite, fields: list[ObsField]) -> None:
        """Add an :class:`Observation` model per read field to the satellite."""
        for obs_code, (value, lli, ssi) in zip(
            self.header.obs_codes_per_system[satellite.sv[0]], fields, strict=True
        ):
            satellite.add_observation(
                Observation(obs_type=obs_code[0], value=value, lli=lli, ssi=ssi)
            )

    @property
    def epochs(self) -> list[Rnxv3ObsEpochRecord]:
        """Materialize all epochs (legacy compatibility).

        Returns
        -------
        list of Rnxv3ObsEpochRecord
            All epochs in memory (use iter_epochs for efficiency)

        """
        return list(self.iter_epochs())

    def iter_epochs(self) -> Iterator[Rnxv3ObsEpochRecord]:
        """Yield epochs one by one instead of materializing the whole list.

        Returns
        -------
        Generator
            Generator yielding Rnxv3ObsEpochRecord objects

        Yields
        ------
        Rnxv3ObsEpochRecord
            Each epoch with timestamp and satellite observations

        """
        yield from self._iter_validated_epochs(rejected=None)

    def _iter_validated_epochs(
        self, rejected: list[int] | None
    ) -> Iterator[Rnxv3ObsEpochRecord]:
        """Yield the epochs that pass validation (see :meth:`iter_epochs`).

        Parameters
        ----------
        rejected : list of int or None
            If given, the 0-based line index of each epoch record that failed
            validation is appended to it. Event epochs are not rejections.

        """
        for record, fields_per_satellite in self._iter_checked_epochs(rejected):
            for satellite, fields in zip(
                record.data, fields_per_satellite, strict=True
            ):
                self._add_observations(satellite, fields)
            yield record

    def _iter_checked_epochs(
        self, rejected: list[int] | None, obs_types: frozenset[str] | None = None
    ) -> Iterator[tuple[Rnxv3ObsEpochRecord, list[list[ObsField]]]]:
        """Yield each valid epoch and the read fields of its satellite lines.

        The single definition of the epoch checks of the validated parser.
        The pydantic models check the epoch line
        (:class:`Rnxv3ObsEpochRecordLineModel`), the SVs (:class:`Satellite`)
        and the satellite count (:class:`Rnxv3ObsEpochRecord`); the
        satellites of the record have no observations, their fields are
        returned as plain tuples, one list per satellite. An epoch is also
        rejected if a satellite's system has no ``SYS / # / OBS TYPES``
        record, or an observation field is not blank but holds no readable
        value.
        Event epochs (flag 2-6) and out-of-range flags are skipped and are
        not rejections.

        Parameters
        ----------
        rejected : list of int or None
            If given, the 0-based line index of each rejected epoch record is
            appended to it.
        obs_types : frozenset of str or None
            If given, only the observation fields of these types are read and
            checked (see :meth:`_read_satellite_line`); ``None`` reads every
            field.

        """
        lines = self._load_file()
        for start, end in self.get_epoch_record_batches():
            try:
                info = Rnxv3ObsEpochRecordLineModel.model_validate(
                    {"epoch": lines[start]}
                )
                if info.epoch_flag > 1:
                    continue
                read = [
                    self._read_satellite_line(line, obs_types)
                    for line in lines[start + 1 : end]
                    if line.strip()
                ]
                record = Rnxv3ObsEpochRecord(
                    info=info, data=[satellite for satellite, _ in read]
                )
            except InvalidEpochError, IncompleteEpochError, ValueError:
                # pydantic's ValidationError is a ValueError
                if rejected is not None:
                    rejected.append(start)
                continue
            yield record, [fields for _, fields in read]

    def iter_epochs_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> Iterable[Rnxv3ObsEpochRecord]:
        """Yield epochs lazily that fall into the given datetime range.

        Parameters
        ----------
        start : datetime
            Start of time range (inclusive)
        end : datetime
            End of time range (inclusive)

        Returns
        -------
        Generator
            Generator yielding epochs in the specified range

        Yields
        ------
        Rnxv3ObsEpochRecord
            Epochs within the time range

        """
        for epoch in self.iter_epochs():
            dt = self.get_datetime_from_epoch_record_info(epoch.info)
            if start <= dt <= end:
                yield epoch

    def get_datetime_from_epoch_record_info(
        self,
        epoch_record_info: Rnxv3ObsEpochRecordLineModel,
    ) -> datetime:
        """Convert epoch record info to datetime object.

        Parameters
        ----------
        epoch_record_info : Rnxv3ObsEpochRecordLineModel
            Parsed epoch record line

        Returns
        -------
        datetime
            Timestamp from epoch record

        """
        info = epoch_record_info
        ts = _epoch_datetime64(
            int(info.year),
            int(info.month),
            int(info.day),
            int(info.hour),
            int(info.minute),
            info.seconds,
        )
        # datetime holds microseconds; the F11.7 field has 100 ns resolution.
        return ts.astype("datetime64[us]").item().replace(tzinfo=UTC)

    @staticmethod
    def epochrecordinfo_dt_to_numpy_dt(
        epch: Rnxv3ObsEpochRecord,
    ) -> np.datetime64:
        """Return the epoch record's time as numpy datetime64[ns].

        Parameters
        ----------
        epch : Rnxv3ObsEpochRecord
            Epoch record containing timestamp info

        Returns
        -------
        np.datetime64
            Numpy datetime64 with nanosecond precision

        """
        info = epch.info
        return _epoch_datetime64(
            int(info.year),
            int(info.month),
            int(info.day),
            int(info.hour),
            int(info.minute),
            info.seconds,
        )

    def _epoch_datetimes(self) -> list[datetime]:
        """Extract epoch datetimes from the file.

        Uses the same epoch parsing logic already implemented.
        """
        dts: list[datetime] = []

        for start, _end in self.get_epoch_record_batches():
            info = Rnxv3ObsEpochRecordLineModel.model_validate(
                {"epoch": self._lines[start]}
            )
            dts.append(
                datetime(
                    year=int(info.year),
                    month=int(info.month),
                    day=int(info.day),
                    hour=int(info.hour),
                    minute=int(info.minute),
                    tzinfo=UTC,
                )
                + timedelta(seconds=float(info.seconds))
            )
        return dts

    def infer_sampling_interval(self) -> pint.Quantity | None:
        """Infer sampling interval from consecutive epoch deltas.

        Returns
        -------
        pint.Quantity or None
            Sampling interval in seconds, or None if cannot be inferred

        """
        dts = self._epoch_datetimes()
        if len(dts) < MIN_EPOCHS_FOR_INTERVAL:
            return None
        # Compute deltas
        deltas: list[timedelta] = [b - a for a, b in pairwise(dts) if b >= a]
        if not deltas:
            return None
        # Pick the most common delta (robust to missing epochs); rounded to
        # the millisecond so sub-second sampling (e.g. 0.1 s) is kept.
        seconds = Counter(
            round(dt.total_seconds(), 3) for dt in deltas if dt.total_seconds() > 0
        )
        if not seconds:
            return None
        mode_seconds, _ = seconds.most_common(1)[0]
        return (mode_seconds * UREG.second).to(UREG.seconds)

    def infer_dump_interval(
        self, sampling_interval: pint.Quantity | None = None
    ) -> pint.Quantity | None:
        """Infer the dump interval from the time the epochs span.

        The span from the first to the last epoch plus one sampling
        interval. Epochs missing between the first and the last epoch
        therefore show up in the completeness check; epochs missing before
        the first or after the last epoch (e.g. a file cut short) do not,
        since only the file name or the caller knows the intended length.

        Parameters
        ----------
        sampling_interval : pint.Quantity, optional
            Known sampling interval. Inferred from the epochs if not given.

        Returns
        -------
        pint.Quantity or None
            Dump interval in seconds, or None if it cannot be inferred
            (fewer than two epochs).

        """
        dts = self._epoch_datetimes()
        if len(dts) < 2:
            return None
        step = sampling_interval or self.infer_sampling_interval()
        if step is None:
            return None
        span = (dts[-1] - dts[0]).total_seconds() * UREG.seconds
        return (span + step.to(UREG.seconds)).to(UREG.seconds)

    def validate_epoch_completeness(
        self,
        dump_interval: str | pint.Quantity | None = None,
        sampling_interval: str | pint.Quantity | None = None,
    ) -> None:
        """Validate that the number of epochs matches the expected dump interval.

        The file must hold dump interval / sampling interval epochs.

        Parameters
        ----------
        dump_interval : str or pint.Quantity, optional
            Expected file dump interval (e.g. ``"15 min"``). If None, the
            span of the epochs is used (:meth:`infer_dump_interval`), which
            detects gaps between the first and the last epoch but not a
            file cut short.
        sampling_interval : str or pint.Quantity, optional
            Expected sampling interval. If None, the most common interval
            between consecutive epochs.

        Returns
        -------
        None

        Raises
        ------
        MissingEpochError
            If total sampling time doesn't match dump interval
        ValueError
            If intervals cannot be inferred

        """
        # Normalize/Infer sampling interval
        if sampling_interval is None:
            inferred = self.infer_sampling_interval()
            if inferred is None:
                msg = "Could not infer sampling interval from epochs"
                raise ValueError(msg)
            sampling_interval = inferred
        # normalize to pint
        elif not isinstance(sampling_interval, pint.Quantity):
            sampling_interval = UREG.Quantity(sampling_interval).to(UREG.seconds)

        # Normalize/Infer dump interval
        if dump_interval is None:
            inferred_dump = self.infer_dump_interval(
                sampling_interval=sampling_interval
            )
            if inferred_dump is None:
                msg = "Could not infer dump interval from file"
                raise ValueError(msg)
            dump_interval = inferred_dump
        elif not isinstance(dump_interval, pint.Quantity):
            # Accept '15 min', '1h', etc.
            dump_interval = UREG.Quantity(dump_interval).to(UREG.seconds)

        # Build inputs for the validator model
        epoch_indices = self.get_epoch_record_batches()

        # This throws MissingEpochError automatically if inconsistent
        cast(Any, Rnxv3ObsEpochRecordCompletenessModel)(
            epoch_records_indeces=epoch_indices,
            rnx_file_dump_interval=dump_interval,
            sampling_interval=sampling_interval,
        )

    def filter_by_overlapping_groups(
        self,
        ds: xr.Dataset,
        group_preference: dict[str, str] | None = None,
    ) -> xr.Dataset:
        """Filter overlapping bands using per-group preferences.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with `sid` dimension and signal properties.
        group_preference : dict[str, str], optional
            Mapping of overlap group to preferred band.

        Returns
        -------
        xr.Dataset
            Dataset filtered to preferred overlapping bands.

        """
        if group_preference is None:
            group_preference = {
                "L1_E1_B1I": "L1",
                "L5_E5a": "L5",
                "L2_E5b_B2b": "L2",
            }

        keep = []
        for sid in ds.sid.values:
            parts = str(sid).split("|")
            band = parts[1] if len(parts) >= 2 else ""
            group = self._signal_mapper.get_overlapping_group(band)
            if group and group in group_preference:
                if band == group_preference[group]:
                    keep.append(sid)
            else:
                keep.append(sid)
        return ds.sel(sid=keep)

    def _precompute_sids_from_header(
        self,
    ) -> tuple[list[str], dict[str, dict[str, object]]]:
        """Build sorted SID list and properties from header info alone.

        Uses the header's obs_codes_per_system and static constellation
        SV lists to pre-compute the full theoretical SID set, eliminating
        the discovery pass.

        Returns
        -------
        sorted_sids : list[str]
            Sorted list of signal IDs.
        sid_properties : dict[str, dict[str, object]]
            Mapping of SID to its properties (sv, system, band, code,
            freq_center, freq_min, freq_max, bandwidth, overlapping_group).

        """
        mapper = self._signal_mapper
        signal_ids: set[str] = set()
        sid_properties: dict[str, dict[str, object]] = {}

        # Pre-compute pint arithmetic once per unique band
        band_freq_cache: dict[str, tuple[float, float, float, float]] = {}

        for system, obs_codes in self.header.obs_codes_per_system.items():
            svs = _get_constellation_svs(system)

            for obs_code in obs_codes:
                if len(obs_code) < 3:
                    continue
                band_num = obs_code[1]
                code_char = obs_code[2]

                band_name = mapper.SYSTEM_BANDS.get(system, {}).get(
                    band_num, f"UnknownBand{band_num}"
                )

                # Cache frequency arithmetic per band
                if band_name not in band_freq_cache:
                    center_frequency = mapper.get_band_frequency(band_name)
                    bandwidth = mapper.get_band_bandwidth(band_name)

                    if center_frequency is not None and bandwidth is not None:
                        bw = bandwidth[0] if isinstance(bandwidth, list) else bandwidth
                        freq_min = center_frequency - (bw / 2.0)
                        freq_max = center_frequency + (bw / 2.0)
                        band_freq_cache[band_name] = (
                            float(center_frequency),
                            float(freq_min),
                            float(freq_max),
                            float(bw),
                        )
                    else:
                        band_freq_cache[band_name] = (
                            np.nan,
                            np.nan,
                            np.nan,
                            np.nan,
                        )

                freq_center, freq_min, freq_max, bw = band_freq_cache[band_name]
                overlapping_group = mapper.get_overlapping_group(band_name)

                sid_suffix = "|" + band_name + "|" + code_char

                for sv in svs:
                    sid = sv + sid_suffix
                    if sid not in signal_ids:
                        signal_ids.add(sid)
                        sid_properties[sid] = {
                            "sv": sv,
                            "system": system,
                            "band": band_name,
                            "code": code_char,
                            "freq_center": freq_center,
                            "freq_min": freq_min,
                            "freq_max": freq_max,
                            "bandwidth": bw,
                            "overlapping_group": overlapping_group,
                        }

        sorted_sids = sorted(signal_ids)
        return sorted_sids, {s: sid_properties[s] for s in sorted_sids}

    def _kept_vars(self, keep_data_vars: frozenset[str] | None) -> frozenset[str]:
        """Return the observation variables the dataset builders allocate."""
        return _OBS_VARS if keep_data_vars is None else keep_data_vars & _OBS_VARS

    def _obs_code_lut(self) -> dict[str, list[tuple[str, str]]]:
        """Map each system's header observation codes to (type, sid suffix).

        Entries follow the order of ``SYS / # / OBS TYPES``, so the i-th entry
        belongs to the i-th observation on a satellite line. Codes shorter
        than three characters map to ``("", "")`` and are skipped.
        """
        bands = self._signal_mapper.SYSTEM_BANDS
        lut: dict[str, list[tuple[str, str]]] = {}
        for system, obs_codes in self.header.obs_codes_per_system.items():
            entries: list[tuple[str, str]] = []
            for obs_code in obs_codes:
                if len(obs_code) < 3:
                    entries.append(("", ""))
                    continue
                band_name = bands.get(system, {}).get(
                    obs_code[1], f"UnknownBand{obs_code[1]}"
                )
                entries.append((obs_code[0], "|" + band_name + "|" + obs_code[2]))
            lut[system] = entries
        return lut

    def _create_dataset_validated(
        self, keep_data_vars: frozenset[str] | None = None
    ) -> xr.Dataset:
        """Build the dataset from the epochs that pass validation.

        Uses the checks of :meth:`_iter_checked_epochs`, the same as
        :meth:`iter_epochs`: pydantic models for the epoch line, the
        satellites and the epoch record, but no model object per
        observation. Only the observation fields the kept variables need are
        read and checked (:func:`_obs_types_to_read`), so a malformed field
        of a left-out variable does not drop its epoch. Epochs that fail are
        dropped and logged with their line numbers. Values are stored with the same rules as
        :meth:`_create_dataset_unvalidated_fast`, so both give the same
        dataset for a valid file.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid) and standard variables.

        """
        sorted_sids, sid_properties = self._precompute_sids_from_header()
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        obs_lut = self._obs_code_lut()

        kept_vars = self._kept_vars(keep_data_vars)
        rejected: list[int] = []
        records = list(
            self._iter_checked_epochs(rejected, _obs_types_to_read(kept_vars))
        )
        if rejected:
            log.warning(
                "rinex_epochs_rejected",
                file=self.fpath.name,
                n_rejected=len(rejected),
                first_lines=[i + 1 for i in rejected[:10]],
                reason="failed epoch validation (epoch line, satellite ID, "
                "satellite count or observation field)",
            )

        arrays = _allocate_obs_arrays(len(records), len(sorted_sids), kept_vars)
        timestamps = np.empty(len(records), dtype="datetime64[ns]")
        for t_idx, (record, fields_per_satellite) in enumerate(records):
            info = record.info
            timestamps[t_idx] = _epoch_datetime64(
                info.year, info.month, info.day, info.hour, info.minute, info.seconds
            )
            for satellite, fields in zip(
                record.data, fields_per_satellite, strict=True
            ):
                sv = satellite.sv
                for (obs_type, sid_suffix), (value, lli, ssi) in zip(
                    obs_lut[sv[0]], fields, strict=True
                ):
                    if not obs_type or value is None:
                        continue
                    s_idx = sid_to_idx.get(sv + sid_suffix)
                    if s_idx is None:
                        continue
                    _store_observation(arrays, t_idx, s_idx, obs_type, value, lli, ssi)

        return self._assemble_dataset(timestamps, arrays, sorted_sids, sid_properties)

    def _create_dataset_unvalidated_fast(
        self, keep_data_vars: frozenset[str] | None = None
    ) -> xr.Dataset:
        """Build the dataset by fixed-column slicing, WITHOUT any validation.

        DANGEROUS: no epoch, satellite or observation model is applied. A
        corrupted record can enter the dataset as partial or wrong values,
        e.g. the fields of a truncated satellite line, or an epoch whose
        satellite count does not match its records. Only epoch lines that do
        not match the epoch pattern, and event epochs, are skipped. Use it
        only for files that were checked otherwise; the results are the
        user's responsibility. For a valid file it gives the same dataset as
        :meth:`_create_dataset_validated` (``test_rinex_v3_path_parity.py``).

        The storage rules are inlined from :func:`_store_observation` for
        speed and must stay identical to it.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid) and standard variables.

        """
        lines = self._load_file()
        epoch_batches = self.get_epoch_record_batches()
        n_epochs = len(epoch_batches)

        sorted_sids, sid_properties = self._precompute_sids_from_header()
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        system_obs_lut = self._obs_code_lut()

        arrays = _allocate_obs_arrays(
            n_epochs, len(sorted_sids), self._kept_vars(keep_data_vars)
        )
        snr = arrays.get("SNR")
        pseudo = arrays.get("Pseudorange")
        phase = arrays.get("Phase")
        doppler = arrays.get("Doppler")
        lli = arrays.get("LLI")
        ssi = arrays.get("SSI")
        ssi_rank = arrays.get(_SSI_RANK_KEY)

        timestamps = np.empty(n_epochs, dtype="datetime64[ns]")
        valid_mask = np.ones(n_epochs, dtype=bool)
        for t_idx, (start, end) in enumerate(epoch_batches):
            m = _EPOCH_RE.match(lines[start])
            if m is None:
                valid_mask[t_idx] = False
                continue

            # Skip event epochs (flag 2-6: special records, not observations)
            # and out-of-range flags, as iter_epochs() does
            if int(m[7]) > 1:
                valid_mask[t_idx] = False
                continue

            timestamps[t_idx] = _epoch_datetime64(
                int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), float(m[6])
            )

            for line_idx in range(start + 1, end):
                sat_line = lines[line_idx]
                if len(sat_line) < 3:
                    continue
                sv = sat_line[:3].strip()
                if not sv:
                    continue
                lut_list = system_obs_lut.get(sv[0])
                if lut_list is None:
                    continue

                data_part = sat_line[3:]
                data_part_len = len(data_part)

                for i, (obs_type, sid_suffix) in enumerate(lut_list):
                    if not obs_type:
                        continue

                    col_start = i * 16
                    if col_start >= data_part_len:
                        break

                    s_idx = sid_to_idx.get(sv + sid_suffix)
                    if s_idx is None:
                        continue

                    value, obs_lli, obs_ssi = _parse_obs_fast(
                        data_part[col_start : col_start + 16]
                    )
                    if value is None:
                        continue

                    # Inlined _store_observation(); keep the two identical.
                    match obs_type:
                        case "S":
                            if snr is not None and value != 0:
                                snr[t_idx, s_idx] = value
                        case "C":
                            if pseudo is not None:
                                pseudo[t_idx, s_idx] = value
                        case "L":
                            if phase is not None:
                                phase[t_idx, s_idx] = value
                        case "D":
                            if doppler is not None:
                                doppler[t_idx, s_idx] = value
                    if lli is not None and obs_lli is not None and obs_type == "L":
                        lli[t_idx, s_idx] = obs_lli
                    if ssi is not None and ssi_rank is not None and obs_ssi is not None:
                        rank = _SSI_SOURCE_RANK.get(obs_type, 0)
                        if rank > ssi_rank[t_idx, s_idx]:
                            ssi[t_idx, s_idx] = obs_ssi
                            ssi_rank[t_idx, s_idx] = rank

        if not valid_mask.all():
            timestamps = timestamps[valid_mask]
            arrays = {name: arr[valid_mask] for name, arr in arrays.items()}

        return self._assemble_dataset(timestamps, arrays, sorted_sids, sid_properties)

    def _assemble_dataset(
        self,
        timestamps: np.ndarray,
        arrays: dict[str, np.ndarray],
        sorted_sids: list[str],
        sid_properties: dict[str, dict[str, object]],
    ) -> xr.Dataset:
        """Wrap filled observation arrays in the (epoch, sid) dataset.

        Shared by both parsers, so coordinates, attributes and variable order
        do not depend on the parser.
        """

        def sid_prop(key: str) -> list[object]:
            return [sid_properties[sid][key] for sid in sorted_sids]

        coords = {
            "epoch": (
                "epoch",
                timestamps,
                epoch_coord_attrs(self.header.time_system, self.fpath.name),
            ),
            "sid": xr.DataArray(
                np.array(sorted_sids, dtype=object),
                dims=["sid"],
                attrs=COORDS_METADATA["sid"],
            ),
            "sv": (
                "sid",
                np.array(sid_prop("sv"), dtype=object),
                COORDS_METADATA["sv"],
            ),
            "system": (
                "sid",
                np.array(sid_prop("system"), dtype=object),
                COORDS_METADATA["system"],
            ),
            "band": (
                "sid",
                np.array(sid_prop("band"), dtype=object),
                COORDS_METADATA["band"],
            ),
            "code": (
                "sid",
                np.array(sid_prop("code"), dtype=object),
                COORDS_METADATA["code"],
            ),
        }
        for key in ("freq_center", "freq_min", "freq_max"):
            coords[key] = (
                "sid",
                np.asarray(sid_prop(key), dtype=DTYPES[key]),
                COORDS_METADATA[key],
            )

        if self.header.signal_strength_unit == UREG.dBHz:
            snr_meta = CN0_METADATA
        else:
            snr_meta = SNR_METADATA

        data_vars = {
            var: (
                ["epoch", "sid"],
                arrays[var],
                snr_meta if var == "SNR" else OBSERVABLES_METADATA[var],
            )
            for var in _OBS_VAR_ORDER
            if var in arrays
        }

        ds = xr.Dataset(
            data_vars=data_vars,
            coords=coords,
            attrs={**self._build_attrs()},
        )

        if self.apply_overlap_filter:
            ds = self.filter_by_overlapping_groups(ds, self.overlap_preferences)

        return ds

    def _create_dataset(
        self,
        keep_data_vars: frozenset[str] | None,
        parser: RinexV3Parser,
    ) -> xr.Dataset:
        """Build the dataset with the chosen parser.

        ``"unvalidated_fast"`` emits an :class:`UnvalidatedParserWarning` and a
        log warning on every use.
        """
        if parser == "validated":
            return self._create_dataset_validated(keep_data_vars)
        if parser == "unvalidated_fast":
            warnings.warn(
                _UNVALIDATED_PARSER_MESSAGE, UnvalidatedParserWarning, stacklevel=3
            )
            log.warning(
                "rinex_unvalidated_parser",
                file=self.fpath.name,
                message=_UNVALIDATED_PARSER_MESSAGE,
            )
            return self._create_dataset_unvalidated_fast(keep_data_vars)
        msg = f"parser must be 'validated' or 'unvalidated_fast', not {parser!r}"
        raise ValueError(msg)

    def create_rinex_netcdf_with_signal_id(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        parser: RinexV3Parser = "validated",
    ) -> xr.Dataset:
        """Create a NetCDF dataset with signal IDs.

        Optionally restricts to epochs within a datetime range via
        post-filtering.

        Parameters
        ----------
        start : datetime, optional
            Start of time range (inclusive).
        end : datetime, optional
            End of time range (inclusive).
        parser : {"validated", "unvalidated_fast"}, default "validated"
            As for :meth:`to_ds`.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid).

        """
        ds = self._create_dataset(None, parser)

        if start or end:
            ds = ds.sel(epoch=slice(start, end))

        return ds

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert RINEX observations to xarray.Dataset with signal ID structure.

        Parameters
        ----------
        outname : Path or str, optional
            If provided, saves dataset to this file path
        keep_data_vars : list of str or None, optional
            Data variables to include in dataset. ``None`` includes all
            available. A run passes the
            ``processing.params.keep_gnss_observables`` setting. The
            validated parser reads and checks only the observation fields
            these variables need, so a malformed field of a left-out
            variable does not drop its epoch.
        write_global_attrs : bool, default False
            If True, adds comprehensive global attributes
        pad_global_sid : bool, default True
            If True, pads to global signal ID space
        strip_fillval : bool, default True
            If True, removes fill values
        add_future_datavars : bool, default True
            If True, adds placeholder variables for future data
        keep_sids : list of str or None, default None
            If provided, filters/pads dataset to these specific SIDs.
            If None and pad_global_sid=True, pads to all possible SIDs.
        parser : {"validated", "unvalidated_fast"}, default "validated"
            ``"validated"`` checks every epoch (epoch line, satellite IDs,
            satellite count, the observation fields of the kept variables)
            and drops (and logs) epochs that fail; see
            :meth:`_create_dataset_validated`.
            ``"unvalidated_fast"`` is DANGEROUS: it slices fixed columns
            without any check, so corrupted records can enter the dataset as
            partial or wrong values; canVODpy takes no responsibility for its
            results, and every use emits an :class:`UnvalidatedParserWarning`.
            Both give the same dataset for a valid file. A run passes the
            ``processing.params.rinex_v3_parser`` setting.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid) and requested data variables

        """
        outname = cast(Path | str | None, kwargs.pop("outname", None))
        write_global_attrs = bool(kwargs.pop("write_global_attrs", False))
        pad_global_sid = bool(kwargs.pop("pad_global_sid", True))
        strip_fillval = bool(kwargs.pop("strip_fillval", True))
        add_future_datavars = bool(kwargs.pop("add_future_datavars", True))
        keep_sids = cast(list[str] | None, kwargs.pop("keep_sids", None))
        parser = cast(RinexV3Parser, kwargs.pop("parser", "validated"))

        kept = None if keep_data_vars is None else frozenset(keep_data_vars)
        require_gps_time(self.header.time_system, self.fpath.name)
        ds = self._create_dataset(kept, parser)

        if pad_global_sid:
            from canvod.readers.preprocessing import pad_to_global_sid

            # Pad/filter to specified sids or all possible sids
            ds = pad_to_global_sid(
                ds,
                keep_sids=keep_sids,
                aggregate_glonass_fdma=self.aggregate_glonass_fdma,
            )

        if strip_fillval:
            from canvod.readers.preprocessing import strip_fillvalue

            ds = strip_fillvalue(ds)

        if add_future_datavars:
            pass

        if write_global_attrs:
            ds.attrs.update(self._create_comprehensive_attrs())

        ds.attrs.update(self._build_attrs())

        if outname:
            from canvod.config import load_config as _load_config

            comp = _load_config().processing.netcdf_compression
            encoding = {
                var: {"zlib": comp.zlib, "complevel": comp.complevel}
                for var in ds.data_vars
            }
            ds.to_netcdf(str(outname), encoding=encoding)

        # Normalize string dtypes for Icechunk / Zarr V3 compatibility
        ds = _str_to_object(ds)

        # Validate output structure for pipeline compatibility
        validate_dataset(ds, required_vars=keep_data_vars)

        return ds

    def validate_rinex_304_compliance(
        self,
        ds: xr.Dataset | None = None,
        strict: bool = False,
        print_report: bool = True,
    ) -> dict[str, list[str]]:
        """Run enhanced RINEX 3.04 specification validation.

        Validates:
        1. System-specific observation codes
        2. GLONASS mandatory fields (slot/frequency, biases)
        3. Phase shift records (RINEX 3.01+)
        4. Observation value ranges

        Parameters
        ----------
        ds : xr.Dataset, optional
            Dataset to validate. If None, creates one from current file.
        strict : bool
            If True, raise ValueError on validation failures
        print_report : bool
            If True, print validation report to console

        Returns
        -------
        dict[str, list[str]]
            Validation results by category

        Examples
        --------
        >>> reader = Rnxv3Obs(fpath="station.24o")
        >>> results = reader.validate_rinex_304_compliance()
        >>> # Or validate a specific dataset
        >>> ds = reader.to_ds()
        >>> results = reader.validate_rinex_304_compliance(ds=ds)

        """
        if ds is None:
            ds = self.to_ds(write_global_attrs=False)

        # Prepare header dict for validators
        header_dict: dict[str, Any] = {
            "obs_codes_per_system": self.header.obs_codes_per_system,
        }

        # Add GLONASS-specific headers if available
        if hasattr(self.header, "glonass_slot_frq"):
            header_dict["GLONASS SLOT / FRQ #"] = self.header.glonass_slot_frq

        if hasattr(self.header, "glonass_cod_phs_bis"):
            header_dict["GLONASS COD/PHS/BIS"] = self.header.glonass_cod_phs_bis

        if hasattr(self.header, "phase_shift"):
            header_dict["SYS / PHASE SHIFT"] = self.header.phase_shift

        # Run validation
        results = RINEX304ComplianceValidator.validate_all(
            ds=ds, header_dict=header_dict, strict=strict
        )

        if print_report:
            RINEX304ComplianceValidator.print_validation_report(results)

        return results

    def _create_comprehensive_attrs(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "File Path": str(self.fpath),
            "File Type": self.header.filetype,
            "RINEX Version": self.header.version,
            "RINEX Type": self.header.rinextype,
            "Observer": self.header.observer,
            "Agency": self.header.agency,
            "Date": self.header.date.isoformat(),
            "Marker Name": self.header.marker_name,
            "Marker Number": self.header.marker_number,
            "Marker Type": self.header.marker_type,
            "Approximate Position": (
                f"(X = {self.header.approx_position[0].magnitude} "
                f"{self.header.approx_position[0].units:~}, "
                f"Y = {self.header.approx_position[1].magnitude} "
                f"{self.header.approx_position[1].units:~}, "
                f"Z = {self.header.approx_position[2].magnitude} "
                f"{self.header.approx_position[2].units:~})"
            ),
            "Receiver Type": self.header.receiver_type,
            "Receiver Version": self.header.receiver_version,
            "Receiver Number": self.header.receiver_number,
            "Antenna Type": self.header.antenna_type,
            "Antenna Number": self.header.antenna_number,
            "Antenna Position": (
                f"(X = {self.header.antenna_position[0].magnitude} "
                f"{self.header.antenna_position[0].units:~}, "
                f"Y = {self.header.antenna_position[1].magnitude} "
                f"{self.header.antenna_position[1].units:~}, "
                f"Z = {self.header.antenna_position[2].magnitude} "
                f"{self.header.antenna_position[2].units:~})"
            ),
            "Program": self.header.pgm,
            "Run By": self.header.run_by,
            "Time of First Observation": json.dumps(
                {k: v.isoformat() for k, v in self.header.t0.items()}
            ),
            "GLONASS COD": self.header.glonass_cod,
            "GLONASS PHS": self.header.glonass_phs,
            "GLONASS BIS": self.header.glonass_bis,
            "GLONASS Slot Frequency Dict": json.dumps(
                self.header.glonass_slot_freq_dict
            ),
            "Leap Seconds": f"{self.header.leap_seconds:~}",
        }
        return attrs


def adapt_existing_rnxv3obs_class(original_class_path: str | None = None) -> str:
    """Provide guidance to integrate the enhanced sid functionality.

    This function provides guidance on how to modify the existing class
    to support the new sid structure alongside the current OFT structure.

    Returns
    -------
    str
        Integration instructions

    """
    _ = original_class_path
    return """
    INTEGRATION GUIDE: Adapting Rnxv3Obs for sid Structure
    ============================================================

    To integrate the new sid functionality into your existing Rnxv3Obs class:

    1. ADD THE SIGNAL_ID_MAPPER CLASS:
       - Copy the SignalIDMapper class to your rinex_reader.py file
       - This handles the mapping logic and band properties

    2. ADD NEW METHODS TO Rnxv3Obs CLASS:

       Method: create_rinex_netcdf_with_signal_id()
       - Copy from EnhancedRnxv3Obs.create_rinex_netcdf_with_signal_id()
       - This creates the new sid-based structure

       Method: filter_by_overlapping_groups()
       - Copy from EnhancedRnxv3Obs.filter_by_overlapping_groups()
       - Handles overlapping signal filtering (Problem A solution)

       Method: to_ds()
       - Copy from EnhancedRnxv3Obs.to_ds()
       - Main interface for creating sid datasets

       Method: create_legacy_compatible_dataset()
       - Copy from EnhancedRnxv3Obs.create_legacy_compatible_dataset()
       - Provides backward compatibility

    3. UPDATE THE __init__ METHOD:
       Add: self.signal_mapper = SignalIDMapper()

    4. MODIFY EXISTING METHODS:
       - Keep existing create_rinex_netcdf_with_oft() for OFT compatibility
       - Add sid option to your main interface methods
       - Update data handlers to support sid dimension

    5. UPDATE DATA_HANDLER/RNX_PARSER.PY:
       - Modify concatenate_datasets() to handle sid dimension
       - Add sid detection alongside OFT detection
       - Update encoding to handle sid string coordinates

    6. UPDATE PROCESSOR/PROCESSOR.PY:
       - Add sid support to create_common_space_datatree()
       - Handle both OFT and sid structures in alignment logic

    BENEFITS OF THIS STRUCTURE:
    ===========================

    ✓ Solves Problem A: Bandwidth overlap handling
      - Overlapping signals kept separate with metadata for filtering
      - band properties include bandwidth information

    ✓ Solves Problem B: code-specific performance differences
      - Each sv|band|code combination gets unique sid
      - No more priority-based LUT - all combinations preserved

    ✓ Maintains compatibility:
      - Legacy conversion available
      - OFT structure still supported
      - Existing code continues to work

    ✓ Enhanced filtering capabilities:
      - Filter by system, band, code independently
      - Complex filtering with multiple criteria
      - Overlap group filtering for analysis

    MIGRATION PATH:
    ===============

    Phase 1: Add sid methods alongside existing OFT methods
    Phase 2: Update data handlers to support both structures
    Phase 3: Gradually migrate analysis code to use sid
    Phase 4: Deprecate old frequency-mapping approach (optional)

    EXAMPLE USAGE AFTER INTEGRATION:
    =================================

    # Create datasets with different structures
    ds_oft = rnx.create_rinex_netcdf_with_oft()           # Current OFT structure
    ds_signal = rnx.create_rinex_netcdf_with_signal_id()  # New sid structure
    ds_legacy = rnx.create_rinex_netcdf(mapped_epochs)    # Legacy structure

    # Advanced sid usage
    ds_enhanced = rnx.to_ds(
        keep_data_vars=["SNR", "Phase"],
        apply_overlap_filter=True,
        overlap_preferences={'L1_E1_B1I': 'L1'}  # Prefer GPS L1 over Galileo E1
    )
    """
