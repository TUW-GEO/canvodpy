"""Mapping between RINEX observation codes and canvodpy signal IDs.

A signal ID (sid) is ``"SV|BAND|CODE"``, e.g. ``"G01|L1|C"``. A RINEX
observation code names the observation type, the frequency number and,
from RINEX 3 on, the tracking code: ``"S1C"`` (RINEX 3.04, Section 5.1) or
``"S1"`` (RINEX 2.11, Table A1). The frequency number maps to the band of
the satellite system through :class:`SignalIDMapper`'s ``SYSTEM_BANDS``;
RINEX 2 tracking codes resolve as in the RINEX v2.11 reader (lowercase
markers where RINEX 2 does not define the code).

These are the rules the RINEX readers apply; tools that exchange data in
RINEX observation-code terms use the same functions.
"""

from canvod.readers.gnss_specs.constellations import (
    GALILEO,
    GLONASS,
    GPS,
    SBAS,
    V2_CODE_L2C_FAMILY,
    V2_CODE_P_FAMILY,
    V2_CODE_UNRESOLVED,
    V2_UNRESOLVED_CODES,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper

# RINEX v2 -> RINEX 3 tracking-code resolution (see _v2_tracking_code()).
# Per-system RINEX 3 code lists, keyed by the band names SignalIDMapper
# produces for v2 frequency numbers. GLONASS FDMA bands carry the same codes
# as the aggregated G1/G2 bands.
_V2_SYSTEM_BAND_CODES: dict[str, dict[str, list[str]]] = {
    "G": GPS.BAND_CODES,
    "R": {**GLONASS.AGGR_BAND_CODES, **GLONASS.FDMA_BAND_CODES},
    "E": GALILEO.BAND_CODES,
    "S": SBAS.BAND_CODES,
}

# v2 pseudorange codes P1/P2 map to obs-type "C" (pseudorange) in v3.
_V2_OBS_TYPE_REMAP: dict[str, str] = {"P": "C"}


def _parse_v2_obs_code(obs_code_v2: str) -> tuple[str, str]:
    """Parse a RINEX v2 2-char obs code into (obs_type, freq_num).

    Parameters
    ----------
    obs_code_v2 : str
        Two-character RINEX v2 observation code (e.g. "L1", "P2", "C5").

    Returns
    -------
    tuple[str, str]
        (obs_type, freq_num) where obs_type is the v3 observation type
        character ("C", "L", "D", "S"; v2 "P" pseudoranges become "C") and
        freq_num the frequency number as string ("1", "2", "5", "6", "7", "8").
    """
    raw_type = obs_code_v2[0]  # C, P, L, D, S
    freq_num = obs_code_v2[1]  # 1, 2, 5, 6, 7, 8
    return _V2_OBS_TYPE_REMAP.get(raw_type, raw_type), freq_num


def _v2_tracking_code(system: str, obs_code_v2: str, band: str | None) -> str:
    """Resolve the sid tracking code of a RINEX v2 observable.

    Assigns a RINEX 3 attribute only where RINEX 2.11 itself defines the
    ranging code (``rinex211.txt`` Table A1: "C: Pseudorange GPS: C/A, L2C;
    Glonass: C/A; Galileo: All" and "P: Pseudorange GPS and Glonass: P
    code"), and otherwise returns one of the lowercase
    ``V2_CODE_*`` markers -- RINEX 2 cannot express the underlying code or
    channel (spec section 10.1), so any RINEX 3 attribute beyond that would
    be a guess.

    Rules, in order:

    1. A band carrying exactly one RINEX 3 signal (SBAS L1: C/A only)
       resolves every observable to that signal's code.
    2. GPS: C1 -> ``C`` (C/A); C2 -> ``l`` (C/A or L2C on L2; C/S/L/X unknown);
       P1/P2 -> ``p`` (P code; under antispoofing P/W/Y, and D on L2,
       unknown; RINEX 3.04 Table 4).
    3. GLONASS: C -> ``C`` (C/A), P -> ``P`` (RINEX 3.04 Table 5 defines a
       single P-code attribute for GLONASS, so no ambiguity).
    4. Everything else -> ``u``: phase, Doppler and signal strength (the spec
       ties signal strength to "the respective phase observations", so it
       shares their sid), Galileo pseudoranges ("All" codes), and L5.
    """
    band_codes = _V2_SYSTEM_BAND_CODES.get(system, {}).get(band or "", [])
    signal_codes = [code for code in band_codes if code not in V2_UNRESOLVED_CODES]
    if len(signal_codes) == 1:
        return signal_codes[0]

    raw_type = obs_code_v2[0]
    if system == "G":
        if obs_code_v2 == "C1":
            return "C"
        if obs_code_v2 == "C2":
            return V2_CODE_L2C_FAMILY
        if raw_type == "P":
            return V2_CODE_P_FAMILY
    elif system == "R" and raw_type in ("C", "P"):
        return raw_type
    return V2_CODE_UNRESOLVED


def _system_bands(system: str, aggregate_glonass_fdma: bool) -> dict[str, str]:
    """Frequency number to band name for one satellite system."""
    bands = SignalIDMapper(
        aggregate_glonass_fdma=aggregate_glonass_fdma
    ).SYSTEM_BANDS.get(system)
    if bands is None:
        msg = f"Unknown satellite system {system!r}"
        raise ValueError(msg)
    return bands


def sid_for_obs_code(
    sv: str, obs_code: str, *, aggregate_glonass_fdma: bool = True
) -> str:
    """Signal ID of an observation code of a satellite.

    Parameters
    ----------
    sv : str
        Satellite, e.g. ``"G01"``.
    obs_code : str
        RINEX 3 observation code (``"S1C"``) or RINEX 2 code (``"S1"``,
        ``"P2"``).
    aggregate_glonass_fdma : bool, default True
        GLONASS FDMA bands as aggregated ``G1``/``G2`` (as the readers).

    Returns
    -------
    str
        Signal ID ``"SV|BAND|CODE"``, e.g. ``"G01|L1|C"``.

    Raises
    ------
    ValueError
        If the code has neither 2 nor 3 characters, or the system has no
        band for its frequency number.
    """
    system = sv[0]
    bands = _system_bands(system, aggregate_glonass_fdma)
    if len(obs_code) == 3:
        freq_num, code = obs_code[1], obs_code[2]
        band = bands.get(freq_num)
    elif len(obs_code) == 2:
        _, freq_num = _parse_v2_obs_code(obs_code)
        band = bands.get(freq_num)
        code = _v2_tracking_code(system, obs_code, band)
    else:
        msg = f"Not a RINEX observation code: {obs_code!r}"
        raise ValueError(msg)
    if band is None:
        msg = f"System {system!r} has no band for frequency number {freq_num!r}"
        raise ValueError(msg)
    return f"{sv}|{band}|{code}"


def obs_code_for_sid(
    sid: str, obs_type: str = "S", *, aggregate_glonass_fdma: bool = True
) -> str:
    """RINEX observation code of a signal ID.

    The inverse of :func:`sid_for_obs_code` for RINEX 3 codes. A sid with a
    lowercase RINEX 2 marker as its code (the tracking code is not known)
    gives the RINEX 2 code without tracking code, e.g. ``"S1"``.

    Parameters
    ----------
    sid : str
        Signal ID ``"SV|BAND|CODE"``.
    obs_type : str, default "S"
        Observation type: ``"C"``, ``"L"``, ``"D"`` or ``"S"``.
    aggregate_glonass_fdma : bool, default True
        GLONASS FDMA bands as aggregated ``G1``/``G2`` (as the readers).

    Returns
    -------
    str
        Observation code, e.g. ``"S1C"``.

    Raises
    ------
    ValueError
        If the sid is malformed or its band is not a band of its system.
    """
    parts = sid.split("|")
    if len(parts) != 3:
        msg = f"Not a signal ID: {sid!r}"
        raise ValueError(msg)
    sv, band, code = parts
    bands = _system_bands(sv[0], aggregate_glonass_fdma)
    freq_nums = [num for num, name in bands.items() if name == band]
    if len(freq_nums) != 1:
        msg = f"Band {band!r} is not a band of system {sv[0]!r}"
        raise ValueError(msg)
    if code in V2_UNRESOLVED_CODES:
        return f"{obs_type}{freq_nums[0]}"
    return f"{obs_type}{freq_nums[0]}{code}"
