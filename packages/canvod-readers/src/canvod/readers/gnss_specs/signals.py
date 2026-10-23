"""Signal ID mapping for GNSS observations.

Maps RINEX observation codes to standardized Signal IDs with frequency
and bandwidth information. Handles all major GNSS constellations.
"""

from canvod.readers.gnss_specs.bands import Bands


class SignalIDMapper:
    """Signal ID mapper with bandwidth-aware properties.

    Provides frequency, bandwidth, and overlap-group lookups for
    GNSS signal bands.  Signal IDs are constructed directly by the
    RINEX v3 reader (``Rnxv3Obs._precompute_sids_from_header``) rather
    than through this class.

    Signal ID Format
    ----------------
    ``"SV|BAND|CODE"``
        Example: ``"G01|L1|C"`` for GPS satellite 1, L1 band, C/A code

    Parameters
    ----------
    aggregate_glonass_fdma : bool, optional
        If True, aggregate GLONASS FDMA channels into G1/G2 bands.
        If False, keep individual FDMA channels separate. Default is True.

    Attributes
    ----------
    SYSTEM_BANDS : dict[str, dict[str, str]]
        Mapping of GNSS system codes to band names.
    BAND_PROPERTIES : dict[str, dict[str, float | str | bool]]
        Band properties including frequency, bandwidth, system.
    OVERLAPPING_GROUPS : dict[str, list[str]]
        Groups of overlapping frequency bands.

    Examples
    --------
    >>> mapper = SignalIDMapper()
    >>> freq = mapper.get_band_frequency("L1")
    >>> freq
    1575.42

    """

    def __init__(
        self,
        aggregate_glonass_fdma: bool = True,
    ) -> None:
        """Initialize SignalIDMapper."""
        self.aggregate_glonass_fdma = aggregate_glonass_fdma
        self._bands = Bands(aggregate_glonass_fdma=self.aggregate_glonass_fdma)
        self.SYSTEM_BANDS: dict[str, dict[str, str]] = self._bands.SYSTEM_BANDS
        self.BAND_PROPERTIES: dict[str, dict[str, float | str | bool]] = (
            self._bands.BAND_PROPERTIES
        )
        self.OVERLAPPING_GROUPS: dict[str, list[str]] = self._bands.OVERLAPPING_GROUPS

    def get_band_frequency(self, band_name: str) -> float | None:
        """Get central frequency for a band.

        Parameters
        ----------
        band_name : str
            Band identifier (e.g., "L1", "E5a", "B2b").

        Returns
        -------
        float or None
            Central frequency in MHz, or None if band not found.

        Examples
        --------
        >>> mapper = SignalIDMapper()
        >>> mapper.get_band_frequency("L1")
        1575.42

        >>> mapper.get_band_frequency("E5a")
        1176.45

        """
        freq = self.BAND_PROPERTIES.get(band_name, {}).get("freq")
        return float(freq) if isinstance(freq, (int, float)) else None

    def get_band_bandwidth(self, band_name: str) -> float | list[float] | None:
        """Get bandwidth for a band.

        Parameters
        ----------
        band_name : str
            Band identifier (e.g., "L1", "E5a", "B2b").

        Returns
        -------
        float or list of float or None
            Bandwidth in MHz. Returns list for bands with multiple
            components. Returns None if band not found.

        Examples
        --------
        >>> mapper = SignalIDMapper()
        >>> mapper.get_band_bandwidth("L1")
        30.69

        >>> mapper.get_band_bandwidth("UnknownBand")
        None

        """
        bandwidth = self.BAND_PROPERTIES.get(band_name, {}).get("bandwidth")
        if isinstance(bandwidth, (int, float)):
            return float(bandwidth)
        if isinstance(bandwidth, list):
            return [float(v) for v in bandwidth if isinstance(v, (int, float))]
        return None

    def get_overlapping_group(self, band_name: str) -> str | None:
        """Get overlapping group for a band.

        Bands in the same overlapping group have frequency overlap
        and may cause interference.

        Parameters
        ----------
        band_name : str
            Band identifier (e.g., "L1", "E1", "B1I").

        Returns
        -------
        str or None
            Group identifier (e.g., "group_1"), or None if not in any group.

        Examples
        --------
        >>> mapper = SignalIDMapper()
        >>> mapper.get_overlapping_group("L1")
        'group_1'

        >>> mapper.get_overlapping_group("E1")
        'group_1'

        """
        for group, bands in self.OVERLAPPING_GROUPS.items():
            if band_name in bands:
                return group
        return None
