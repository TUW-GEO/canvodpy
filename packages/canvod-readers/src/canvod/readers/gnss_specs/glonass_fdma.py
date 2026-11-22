"""GLONASS FDMA carrier frequencies and frequency channels.

The one place in canvod-readers that turns a GLONASS frequency channel into
a carrier frequency, and a satellite into its frequency channel:

- :func:`glonass_fdma_frequency_hz`: the FDMA frequency plan,
  ``f = frequency_base + k * channel_spacing`` for channel ``k``, with the
  band constants from
  :data:`~canvod.readers.gnss_specs.validation_constants.GLONASS_BANDS`.
- :func:`glonass_channel`: the frequency channel a GLONASS satellite (slot,
  e.g. ``"R25"``) used on a date, from the IGS satellite metadata
  (:class:`~canvod.readers.gnss_specs.satellite_catalog.SatelliteCatalog`).
  Channels change when satellites are replaced or slots reassigned, so the
  date matters.
- :func:`glonass_carrier_frequency_hz`: both together.

References
----------
GLONASS FDMA ICD, Edition 5.1 (2008), 3.3.1.1 Frequency plan, Table 3.1:
``f_K1 = 1602 MHz + K * 9/16 MHz`` and ``f_K2 = 1246 MHz + K * 7/16 MHz``.
RINEX 3.04, Table 5, lists ``K = -7...+12``.

Examples
--------
>>> from datetime import date
>>> float(glonass_fdma_frequency_hz("G1", -7))
1598062500.0
>>> glonass_carrier_frequency_hz("R25", "G2", date(2023, 1, 15))  # doctest: +SKIP
1243812500.0
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

import numpy as np

from canvod.readers.gnss_specs.validation_constants import (
    GLONASS_BANDS,
    GLONASS_FREQ_NUMBERS,
)

if TYPE_CHECKING:
    from datetime import date

    from numpy.typing import ArrayLike, NDArray

    from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog


def _mhz(value: object) -> float:
    if not isinstance(value, float | int):
        msg = f"expected a frequency in MHz, got {value!r}"
        raise TypeError(msg)
    return float(value)


#: FDMA band name -> (frequency_base, channel_spacing) in Hz.
_FDMA_BANDS_HZ: dict[str, tuple[float, float]] = {
    str(spec["name"]): (
        _mhz(spec["frequency_base"]) * 1e6,
        _mhz(spec["channel_spacing"]) * 1e6,
    )
    for spec in GLONASS_BANDS.values()
    if "channel_spacing" in spec
}

#: GLONASS FDMA band names (``"G1"``, ``"G2"``).
GLONASS_FDMA_BANDS: tuple[str, ...] = tuple(_FDMA_BANDS_HZ)


def fdma_base_and_spacing_hz(band: str) -> tuple[float, float]:
    """Return the base frequency and channel spacing of a GLONASS FDMA band.

    Parameters
    ----------
    band : str
        ``"G1"`` or ``"G2"``.

    Returns
    -------
    tuple of float
        ``(frequency_base, channel_spacing)`` in Hz.

    Raises
    ------
    ValueError
        If ``band`` is not a GLONASS FDMA band.
    """
    try:
        return _FDMA_BANDS_HZ[band]
    except KeyError:
        msg = (
            f"{band!r} is not a GLONASS FDMA band; expected one of {GLONASS_FDMA_BANDS}"
        )
        raise ValueError(msg) from None


def glonass_fdma_frequency_hz(band: str, channel: ArrayLike) -> NDArray[np.float64]:
    """Return the carrier frequency of a GLONASS FDMA channel.

    Parameters
    ----------
    band : str
        ``"G1"`` or ``"G2"``.
    channel : int or array of int
        Frequency channel ``k``, in ``-7...+12`` (RINEX 3.04, Table 5).

    Returns
    -------
    numpy.ndarray of float
        Carrier frequency in Hz, shaped like ``channel`` (0-d for a scalar).

    Raises
    ------
    ValueError
        If ``band`` is not a GLONASS FDMA band or a channel is outside
        ``-7...+12``.
    """
    base_hz, spacing_hz = fdma_base_and_spacing_hz(band)
    k = np.asarray(channel)
    if not np.issubdtype(k.dtype, np.integer):
        msg = f"GLONASS frequency channels are integers, got {k.dtype}"
        raise ValueError(msg)
    if not np.isin(k, GLONASS_FREQ_NUMBERS).all():
        msg = (
            f"GLONASS frequency channel {channel} is outside "
            f"{GLONASS_FREQ_NUMBERS[0]}...{GLONASS_FREQ_NUMBERS[-1]}"
        )
        raise ValueError(msg)
    return base_hz + k.astype(np.float64) * spacing_hz


@cache
def _default_catalog() -> SatelliteCatalog:
    from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog

    return SatelliteCatalog.load()


def glonass_channel(
    sv: str,
    on_date: date,
    catalog: SatelliteCatalog | None = None,
) -> int | None:
    """Return the frequency channel a GLONASS satellite used on a date.

    Parameters
    ----------
    sv : str
        GLONASS slot as in RINEX, e.g. ``"R25"``.
    on_date : datetime.date
        Date of the observation.
    catalog : SatelliteCatalog, optional
        Satellite metadata to use. Default: ``SatelliteCatalog.load()``,
        loaded once per process.

    Returns
    -------
    int or None
        Frequency channel ``k``, or None when the catalog has no satellite
        in this slot, or no channel for it, on that date.

    Raises
    ------
    ValueError
        If ``sv`` is not a GLONASS satellite.
    """
    if not sv.startswith("R"):
        msg = f"{sv!r} is not a GLONASS satellite"
        raise ValueError(msg)
    catalog = catalog if catalog is not None else _default_catalog()
    svn = catalog.prn_to_svn(sv, on_date)
    return None if svn is None else catalog.glonass_channel(svn, on_date)


def glonass_carrier_frequency_hz(
    sv: str,
    band: str,
    on_date: date,
    catalog: SatelliteCatalog | None = None,
) -> float | None:
    """Return a GLONASS satellite's FDMA carrier frequency on a date.

    Parameters
    ----------
    sv : str
        GLONASS slot as in RINEX, e.g. ``"R25"``.
    band : str
        ``"G1"`` or ``"G2"``.
    on_date : datetime.date
        Date of the observation.
    catalog : SatelliteCatalog, optional
        Satellite metadata to use; see :func:`glonass_channel`.

    Returns
    -------
    float or None
        Carrier frequency in Hz, or None when the satellite's channel on
        that date is unknown.

    Raises
    ------
    ValueError
        If ``sv`` is not a GLONASS satellite or ``band`` not an FDMA band.
    """
    fdma_base_and_spacing_hz(band)  # refuse a wrong band even without a channel
    channel = glonass_channel(sv, on_date, catalog)
    if channel is None:
        return None
    return float(glonass_fdma_frequency_hz(band, channel))
