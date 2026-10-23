"""GNSS constellation definitions and frequency lookup tables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import structlog

from canvod.readers.gnss_specs.constants import UREG

_log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from datetime import date


# ================================================================
# ------------ Pre-Compiled Regex for Data Validation ------------
# ================================================================

# Pre-compiled regex patterns used for better perfromance in data validation
SV_PATTERN = re.compile(r"^[GRECJSI]\d{2}$")  # e.g., G01, R12, E25
OBS_TYPE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9]?[A-Z0-9]?$")  # e.g., *1C, *5X


# ================================================================
# ------------- RINEX 2 unresolved tracking-code markers -----------
# ================================================================

# RINEX 2.11 two-character observation codes (``rinex/rinex211.txt``, Table
# A1) name the carrier band but, by the spec's own admission (section 10.1),
# cannot express the underlying ranging code or channel. RINEX 3 attributes
# are therefore only assignable where the v2 code defines them (e.g. GPS C1 =
# C/A). Everywhere else the ``code`` field of a sid carries one of these
# markers instead of a guessed RINEX 3 attribute. They are lowercase on
# purpose: RINEX observation codes are uppercase-only, so a marker can never
# collide with a real RINEX 3/4 attribute (a guessed "X" would -- it is the
# real L1C D+P / L2C M+L signal).
V2_CODE_P_FAMILY = "p"
"""GPS P1/P2: P-code family; under antispoofing the tracking technique
(RINEX 3 P/W/Y, and D on L2 only; RINEX 3.04 Table 4) is not recorded in
RINEX 2 (rinex211.txt Table A1: antispoofing observations are stored as
P2/L2)."""
V2_CODE_L2C_FAMILY = "l"
"""GPS C2: civil-code pseudorange on L2, either C/A or L2C (rinex211.txt
Table A1: "C: Pseudorange GPS: C/A, L2C"; IS-GPS-200N Sect. 3.2.3: C/A on L2
selectable by ground command); the RINEX 3 attribute (C, or L2C channel
S/L/X) is not recorded. The constant name is historical."""
V2_CODE_UNRESOLVED = "u"
"""No tracking information beyond the carrier band (v2 phase, Doppler,
signal strength, and Galileo/L5 pseudoranges)."""
V2_UNRESOLVED_CODES = (V2_CODE_P_FAMILY, V2_CODE_L2C_FAMILY, V2_CODE_UNRESOLVED)


# ================================================================
# -------------------- Base Class --------------------
# ================================================================
class ConstellationBase:
    """Base class for GNSS constellations.

    Parameters
    ----------
    constellation : str
        Name of the constellation (e.g., "GPS", "GALILEO").
    static_svs : list of str
        Static list of PRN codes for this constellation.
    aggregate_fdma : bool, optional
        If True, aggregate FDMA bands when supported (default True).

    """

    BANDS: ClassVar[dict[str, str]] = {}
    BAND_CODES: ClassVar[dict[str, list[str]]] = {}
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {}

    #: Single-letter system prefix used by SatelliteCatalog (e.g. "G", "E").
    SYSTEM_PREFIX: ClassVar[str] = ""

    def __init__(
        self,
        constellation: str,
        static_svs: list[str] | None = None,
        aggregate_fdma: bool = True,
    ) -> None:
        """Initialize the constellation base."""
        self.constellation: str = constellation
        self.svs: list[str] = static_svs or []
        self.aggregate_fdma = aggregate_fdma

    def update_svs_from_catalog(self, on_date: date) -> list[str]:
        """Update the SV list from IGS SatelliteCatalog for a given date.

        Parameters
        ----------
        on_date : date
            Query date for active PRNs.

        Returns
        -------
        list[str]
            Updated list of active PRNs.
        """
        from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog

        if not self.SYSTEM_PREFIX:
            _log.warning(
                "no_system_prefix",
                constellation=self.constellation,
                hint="Cannot query SatelliteCatalog without SYSTEM_PREFIX",
            )
            return self.svs

        catalog = SatelliteCatalog.fetch()
        self.svs = catalog.active_prns(self.SYSTEM_PREFIX, on_date)
        _log.info(
            "svs_updated_from_catalog",
            constellation=self.constellation,
            count=len(self.svs),
            date=str(on_date),
        )
        return self.svs


# ================================================================
# ------------ 1. Global Navigation Satellite Systems ------------
# ================================================================
class GALILEO(ConstellationBase):
    """Galileo constellation model.

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 6).
    - Band frequencies and bandwidths from Galileo ICD:
      https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_OS_SIS_ICD_v2.1.pdf
      (Tables 2 & 3).

    Might need adaptation for future Galileo signals and RINEX versions.

    Note 1:
    -------
    The E5a and E5b signals are part of the E5 signal in its full bandwidth.

    Note 2:
    -------
    Bandwidths specified here refer to the Receiver Reference Bandwidths.

    """

    SYSTEM_PREFIX: ClassVar[str] = "E"

    BANDS: ClassVar[dict[str, str]] = {
        "1": "E1",
        "5": "E5a",
        "7": "E5b",
        "6": "E6",
        "8": "E5",
    }
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        # Trailing lowercase entries: RINEX 2 markers (see V2_CODE_*).
        "E1": ["A", "B", "C", "X", "Z", "u"],
        "E5a": ["I", "Q", "X", "u"],
        "E5b": ["I", "Q", "X", "u"],
        "E5": ["I", "Q", "X", "u"],
        "E6": ["A", "B", "C", "X", "Z", "u"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "E1": {
            "freq": 1575.42 * UREG.MHz,
            "bandwidth": 24.552 * UREG.MHz,
            "system": "E",
        },
        "E5a": {
            "freq": 1176.45 * UREG.MHz,
            "bandwidth": 20.46 * UREG.MHz,
            "system": "E",
        },
        "E5b": {
            "freq": 1207.14 * UREG.MHz,
            "bandwidth": 20.46 * UREG.MHz,
            "system": "E",
        },
        "E6": {
            "freq": 1278.75 * UREG.MHz,
            "bandwidth": 40.92 * UREG.MHz,
            "system": "E",
        },
        "E5": {
            "freq": 1191.795 * UREG.MHz,
            "bandwidth": 51.15 * UREG.MHz,
            "system": "E",
        },
    }

    def __init__(self) -> None:
        """Initialize Galileo constellation."""
        super().__init__(
            constellation="GALILEO",
            static_svs=[f"E{x:02d}" for x in range(1, 37)],  # E01-E36
        )


class GPS(ConstellationBase):
    """GPS constellation model.

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 4).
    - L1/L2 frequencies and bandwidths from GPS L1/L2 ICD:
      https://www.gps.gov/sites/default/files/2025-07/IS-GPS-200N.pdf
      (3.3.1.1 Frequency Plan).
    - L5 frequency and bandwidth from GPS L5 ICD:
      https://www.gps.gov/sites/default/files/2025-07/IS-GPS-705J.pdf
      (3.3.1.1 Frequency Plan).

    Note:
    ----
    L1/L2 bandwidth technically depends on the GPS Block. Blocks IIR, IIR-M and
    IIF have a bandwidth of 20.46 MHz, while Block III and IIIF has a bandwidth
    of 30.69 MHz. We assume the larger bandwidth here.

    """

    SYSTEM_PREFIX: ClassVar[str] = "G"

    BANDS: ClassVar[dict[str, str]] = {"1": "L1", "2": "L2", "5": "L5"}
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        # Trailing lowercase entries: RINEX 2 markers (see V2_CODE_*).
        "L1": ["C", "S", "L", "X", "P", "W", "Y", "M", "N", "p", "u"],
        "L2": ["C", "D", "S", "L", "X", "P", "W", "Y", "M", "N", "l", "p", "u"],
        "L5": ["I", "Q", "X", "u"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "L1": {
            "freq": 1575.42 * UREG.MHz,
            "bandwidth": 30.69 * UREG.MHz,
            "system": "G",
        },
        "L2": {
            "freq": 1227.60 * UREG.MHz,
            "bandwidth": 30.69 * UREG.MHz,
            "system": "G",
        },
        "L5": {"freq": 1176.45 * UREG.MHz, "bandwidth": 24 * UREG.MHz, "system": "G"},
    }

    def __init__(self) -> None:
        """Initialize GPS constellation."""
        super().__init__(
            constellation="GPS",
            static_svs=[f"G{x:02d}" for x in range(1, 33)],
        )


class BEIDOU(ConstellationBase):
    """BeiDou constellation model.

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 9).
    - B1I (Rinex: B1-2) frequency and bandwidth from B1I ICD:
      http://en.beidou.gov.cn/SYSTEMS/ICD/201902/P020190227702348791891.pdf
      (4.2.1 Carrier Frequency, 4.2.7 Signal Bandwidth).
    - B1C (Rinex: B1) frequency and bandwidth from B1C ICD:
      http://en.beidou.gov.cn/SYSTEMS/ICD/201806/P020180608519640359959.pdf
      (4 Signal Characteristics).
    - B2b frequency and bandwidth from B2b ICD:
      http://en.beidou.gov.cn/SYSTEMS/ICD/202008/P020231201537880833625.pdf
      (4 Signal Characteristics).
    - B2a frequency and bandwidth from B2a ICD:
      http://en.beidou.gov.cn/SYSTEMS/ICD/201806/P020180608518432765621.pdf
      (4 Signal Characteristics).
    - B3I (Rinex B3) frequency and bandwidth from B3I ICD:
      http://en.beidou.gov.cn/SYSTEMS/ICD/201806/P020180608516798097666.pdf
      (4.2.1 Carrier Frequency, 4.2.7 Signal Bandwidth).

    Note 1:
    -------
    Band names used here do not refer to the Rinex band names, but to the
    BeiDou signal names.

    Note 2:
    -------
    No ICD for the combined B2 band was found. The center frequency is taken
    from the Rinex v3.04 Guide, perfectly centered between B2a and B2b. The
    bandwidth is speculative, assumed to cover both B2a and B2b signals and
    their bandwidths.

    Notes
    -----
    This class fetches the current satellite list from Wikipedia.

    """

    BANDS: ClassVar[dict[str, str]] = {
        "2": "B1I",
        "1": "B1C",
        "5": "B2a",
        "7": "B2b",
        "6": "B3I",
        "8": "B2",
    }
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "B1I": ["I", "Q", "X"],
        "B1C": ["D", "P", "X", "A", "N"],
        "B2a": ["D", "P", "X"],
        "B2b": ["I", "Q", "X", "D", "P", "Z"],
        "B3I": ["I", "Q", "X", "A"],
        "B2": ["D", "P", "X"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "B1I": {
            "freq": 1561.098 * UREG.MHz,
            "bandwidth": 4.092 * UREG.MHz,
            "system": "C",
        },
        "B1C": {
            "freq": 1575.42 * UREG.MHz,
            "bandwidth": 32.736 * UREG.MHz,
            "system": "C",
        },
        "B2a": {
            "freq": 1176.45 * UREG.MHz,
            "bandwidth": 20.46 * UREG.MHz,
            "system": "C",
        },
        "B2b": {
            "freq": 1207.14 * UREG.MHz,
            "bandwidth": 20.46 * UREG.MHz,
            "system": "C",
        },
        "B3I": {
            "freq": 1268.52 * UREG.MHz,
            "bandwidth": 20.46 * UREG.MHz,
            "system": "C",
        },
        "B2": {
            "freq": 1191.795 * UREG.MHz,
            "bandwidth": 51.15 * UREG.MHz,  # speculative
            "system": "C",
        },
    }

    SYSTEM_PREFIX: ClassVar[str] = "C"

    def __init__(self) -> None:
        """Initialize BeiDou constellation."""
        super().__init__(
            constellation="BEIDOU",
            static_svs=[f"C{x:02d}" for x in range(1, 64)],  # C01-C63
        )


class GLONASS(ConstellationBase):
    """GLONASS constellation model (uses FDMA for L1/L2).

    SYSTEM_PREFIX is ``"R"`` for SatelliteCatalog queries.

    Notes
    -----

    References
    ----------
      - Band numbers, codes and CDMA band (G1a, G2a, G3) center frequencies
        from RINEX v3.04: http://acc.igs.org/misc/rinex304.pdf (Table 5).
        Note that Table 5 lists k = -7...+12; the channel range used here
        is the FDMA ICD's.
      - FDMA equations, channel range K = -7...+6 ("All GLONASS SVs
        launched after 2005") and per-channel bandwidth (+/-0.511 MHz, i.e.
        1.022 MHz) from the GLONASS FDMA ICD, Edition 5.1 (2008):
        https://www.unavco.org/help/glossary/docs/
        ICD_GLONASS_5.1_(2008)_en.pdf (3.3.1.1 Frequency plan, Table 3.1;
        3.3.1.4 Spurious emissions).
      - CDMA band bandwidths (7.875 MHz for G1a, G2a, G3): no source found;
        see the GitHub issue on this value.
      - GLONASS channel assignment from: see included channel file.

    G1/G2 is treated as a single band here, although it consists of sub-bands
    according to FDMA. The aggregate center frequency and bandwidth are
    derived from the current in-force GLONASS FDMA channel plan, channel
    numbers ``n`` in ``[-7, 6]`` (see channel file):

        freq(n)   = base_freq + n * spacing
        center    = (freq(n_min) + freq(n_max)) / 2
        bandwidth = freq(n_max) - freq(n_min) + subband_bandwidth

    where ``subband_bandwidth`` is 1.022 MHz (twice the GLONASS C/A chip
    rate) for both G1 and G2. So the aggregate center frequency differs
    slightly from the FDMA base value.

    Attributes
    ----------
    glonass_channel_pth : Path, optional
        Path to GLONASS channel assignment file (default:
        "GLONASS_channels.txt" in the same directory as this file).
    aggregate_fdma : bool, default True
        If True, aggregate FDMA sub-bands into single G1/G2 bands.
        If False, maintain individual FDMA channel frequencies.

    Raises
    ------
    FileNotFoundError
        If GLONASS channel file does not exist.

    """

    SYSTEM_PREFIX: ClassVar[str] = "R"

    BANDS: ClassVar[dict[str, str]] = {"3": "G3", "4": "G1a", "6": "G2a"}
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "G1": ["C", "P"],
        "G2": ["C", "P"],
        "G3": ["I", "Q", "X"],
        "G1a": ["A", "B", "X"],
        "G2a": ["A", "B", "X"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "G1a": {
            "freq": 1600.995 * UREG.MHz,
            "bandwidth": 7.875 * UREG.MHz,
            "system": "R",
        },
        "G2a": {
            "freq": 1248.06 * UREG.MHz,
            "bandwidth": 7.875 * UREG.MHz,
            "system": "R",
        },
        "G3": {
            "freq": 1202.025 * UREG.MHz,
            "bandwidth": 7.875 * UREG.MHz,
            "system": "R",
        },
    }

    AGGR_BANDS: ClassVar[dict[str, str]] = {
        "1": "G1",
        "2": "G2",
    }
    # Trailing lowercase entries: RINEX 2 markers (see V2_CODE_*).
    AGGR_BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "G1": ["C", "P", "u"],
        "G2": ["C", "P", "u"],
    }
    FDMA_BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "G1_FDMA": ["C", "P", "u"],
        "G2_FDMA": ["C", "P", "u"],
    }

    # n_min=-7, n_max=6 (see Note on G1 & G2 above):
    #   G1: freq(n) = 1602 + n*9/16   -> center=1601.71875, bandwidth=8.3345
    #   G2: freq(n) = 1246 + n*7/16   -> center=1245.78125, bandwidth=6.7095
    AGGR_G1_G2_BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "G1": {
            "freq": 1601.71875 * UREG.MHz,  # see Note on G1 & G2
            "bandwidth": 8.3345 * UREG.MHz,  # see Note on G1 & G2
            "system": "R",
        },
        "G2": {
            "freq": 1245.78125 * UREG.MHz,  # see Note on G1 & G2
            "bandwidth": 6.7095 * UREG.MHz,  # see Note on G1 & G2
            "system": "R",
        },
    }

    def __init__(
        self,
        glonass_channel_pth: Path | None = Path(__file__).parent
        / "GLONASS_channels.txt",
        aggregate_fdma: bool = True,
    ) -> None:
        """Initialize GLONASS constellation with FDMA channel assignments."""
        super().__init__(
            constellation="GLONASS",
            static_svs=[f"R{i:02d}" for i in range(1, 25)],
            aggregate_fdma=aggregate_fdma,
        )
        if glonass_channel_pth is None or not glonass_channel_pth.exists():
            msg = f"{glonass_channel_pth} does not exist"
            raise FileNotFoundError(msg)
        self.pth = glonass_channel_pth

        if self.aggregate_fdma:
            # Aggregate mode: G1 and G2 are single bands.
            # Instance attributes intentionally shadow the ClassVars for per-instance config.
            self.__dict__["BANDS"] = {**self.BANDS, **self.AGGR_BANDS}
            self.__dict__["BAND_CODES"] = {
                **self.BAND_CODES,
                **self.AGGR_BAND_CODES,
            }
            self.__dict__["BAND_PROPERTIES"] = {
                **self.BAND_PROPERTIES,
                **self.AGGR_G1_G2_BAND_PROPERTIES,
            }
        else:
            # Non-aggregate mode: Map 1/2 to FDMA bands
            # Note: Frequencies will be computed per-SV in freqs_lut
            self.__dict__["BANDS"] = {**self.BANDS, "1": "G1_FDMA", "2": "G2_FDMA"}
            self.__dict__["BAND_CODES"] = {
                **self.BAND_CODES,
                **self.FDMA_BAND_CODES,
            }
            # Add placeholder properties (actual freqs are SV-dependent)
            self.__dict__["BAND_PROPERTIES"] = {
                **self.BAND_PROPERTIES,
                "G1_FDMA": {
                    "freq": 1602.0 * UREG.MHz,  # Nominal center
                    "bandwidth": 9.0 * UREG.MHz,  # FDMA range
                    "system": "R",
                    "fdma": True,  # Flag for SV-dependent frequency
                },
                "G2_FDMA": {
                    "freq": 1246.0 * UREG.MHz,  # Nominal center
                    "bandwidth": 7.0 * UREG.MHz,  # FDMA range
                    "system": "R",
                    "fdma": True,  # Flag for SV-dependent frequency
                },
            }

    def get_channel_used_by_SV(self, sv: str) -> int:
        """Return the GLONASS channel number for a satellite.

        Parameters
        ----------
        sv : str
            GLONASS satellite identifier (e.g., "R01").

        Returns
        -------
        int
            Channel number for this satellite.

        """
        slot = int(sv[1:3])
        return self.glonass_slots_channels[slot]

    @property
    def glonass_slots_channels(self) -> dict[int, int]:
        """Parse GLONASS channel file.

        Returns
        -------
        dict
            Mapping slot → channel.

        """
        slot_channel_dict: dict[int, int] = {}
        with self.pth.open() as file:
            lines = file.readlines()
            for i in range(len(lines)):
                if "slot" in lines[i] and "Channel" in lines[i + 1]:
                    slots_line = lines[i].strip().split("|")[1:-1]
                    channels_line = lines[i + 1].strip().split("|")[1:-1]
                    for slot, channel in zip(slots_line, channels_line, strict=False):
                        if (
                            slot.strip().isdigit()
                            and channel.strip().lstrip("-").isdigit()
                        ):
                            slot_channel_dict[int(slot.strip())] = int(channel.strip())
        return slot_channel_dict


# ================================================================
# ----------- 2. Satellite-based Augmentation Systems  -----------
# ================================================================


class SBAS(ConstellationBase):
    """SBAS constellation model (WAAS, EGNOS, GAGAN, MSAS, SDCM).

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 7).
    - L5 frequency and bandwidth from GPS L5 ICD:
      https://www.gps.gov/sites/default/files/2025-07/IS-GPS-705J.pdf
      (3.3.1.1 Frequency Plan).
    - L1 frequency and bandwidth from GPS L1/L2 ICD:
      https://www.gps.gov/sites/default/files/2025-07/IS-GPS-200N.pdf
      (3.3.1.1 Frequency Plan).

    Notes
    -----
    RINEX numbers SBAS satellites ``Snn`` with nn = broadcast PRN - 100
    (``rinex/rinex211.txt`` section 9.1, RINEX 3.04 section 8.4: PRN 120 ->
    S20; QZSS SBAS-signal PRNs 183+ -> S83+). The static list therefore
    spans the full two-digit range S01-S99 the format allows, rather than an
    assignment table that goes stale: a sid outside it is silently dropped
    by ``pad_to_global_sid()`` (e.g. EGNOS PRN 148 -> S48).

    """

    BANDS: ClassVar[dict[str, str]] = {"1": "L1", "5": "L5"}
    # Trailing lowercase entry: RINEX 2 marker (see V2_CODE_*). L1 needs none:
    # C/A is its only signal, so every v2 L1 observable resolves to "C".
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "L1": ["C"],
        "L5": ["I", "Q", "X", "u"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "L1": {
            "freq": 1575.42 * UREG.MHz,
            "bandwidth": 30.69 * UREG.MHz,
            "system": "S",
        },
        "L5": {"freq": 1176.45 * UREG.MHz, "bandwidth": 24.0 * UREG.MHz, "system": "S"},
    }

    SYSTEM_PREFIX: ClassVar[str] = "S"

    def __init__(self) -> None:
        """Initialize SBAS constellation."""
        super().__init__(
            constellation="SBAS",
            static_svs=[f"S{x:02d}" for x in range(1, 100)],
        )


# ================================================================
# ----------- 3. Regional Navigation Satellite Systems  ----------
# ================================================================


class IRNSS(ConstellationBase):
    """IRNSS (NavIC) constellation model.

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 10).
    - L5 frequencies and bandwidths from NavIC ICD:
      https://www.isro.gov.in/media_isro/pdf/Publications/Vispdf/Pdf2017/1a_messgingicd_receiver_incois_approved_ver_1.2.pdf
      (Table 1).
    - S band frequency and bandwidth from Navipedia:
      https://gssc.esa.int/navipedia/index.php/IRNSS_Signal_Plan#cite_note-IRNSS_ICD-2

    """

    SYSTEM_PREFIX: ClassVar[str] = "I"

    BANDS: ClassVar[dict[str, str]] = {"5": "L5", "9": "S"}
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "L5": ["A", "B", "C", "X"],
        "S": ["A", "B", "C", "X"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "L5": {"freq": 1176.45 * UREG.MHz, "bandwidth": 24.0 * UREG.MHz, "system": "I"},
        "S": {"freq": 2492.028 * UREG.MHz, "bandwidth": 16.5 * UREG.MHz, "system": "I"},
    }

    def __init__(self) -> None:
        """Initialize IRNSS (NavIC) constellation."""
        super().__init__(
            constellation="IRNSS",
            static_svs=[f"I{x:02d}" for x in range(1, 15)],  # I01-I14
        )


class QZSS(ConstellationBase):
    """QZSS constellation model (GPS-compatible + unique L6).

    - Band numbers and codes from RINEX v3.04 Guide:
      http://acc.igs.org/misc/rinex304.pdf (Table 8).
    - L1, L2, L5 frequencies and bandwidths from QZSS ICD:
      https://qzss.go.jp/en/technical/download/pdf/ps-is-qzss/is-qzss-pnt-006.pdf?t=1757949673838
      (Table 3.1.2-1).
    - L6 frequency and bandwidth from Navipedia:
      https://gssc.esa.int/navipedia/index.php?title=QZSS_Signal_Plan

    Note:
    ----
    Bandwidth technically depends on the GPS Block. Like with `GPS`, we assume
    the larger bandwidth here.

    """

    SYSTEM_PREFIX: ClassVar[str] = "J"

    BANDS: ClassVar[dict[str, str]] = {
        "1": "L1",
        "2": "L2",
        "5": "L5",
        "6": "L6",
    }
    BAND_CODES: ClassVar[dict[str, list[str]]] = {
        "L1": ["C", "S", "L", "X", "Z"],
        "L2": ["S", "L", "X"],
        "L5": ["I", "Q", "X", "D", "P", "Z"],
        "L6": ["S", "L", "X", "E", "Z"],
    }
    BAND_PROPERTIES: ClassVar[dict[str, dict[str, Any]]] = {
        "L1": {
            "freq": 1575.42 * UREG.MHz,
            "bandwidth": 30.69 * UREG.MHz,
            "system": "J",
        },
        "L2": {
            "freq": 1227.60 * UREG.MHz,
            "bandwidth": 30.69 * UREG.MHz,
            "system": "J",
        },
        "L5": {"freq": 1176.45 * UREG.MHz, "bandwidth": 24.0 * UREG.MHz, "system": "J"},
        "L6": {"freq": 1278.75 * UREG.MHz, "bandwidth": 42.0 * UREG.MHz, "system": "J"},
    }

    def __init__(self) -> None:
        """Initialize QZSS constellation."""
        super().__init__(
            constellation="QZSS",
            static_svs=[f"J{x:02d}" for x in range(1, 11)],
        )


if __name__ == "__main__":
    gal = GALILEO()
    print("Galileo SVs:", gal.svs)
    print("Galileo Bands:", gal.BANDS)
