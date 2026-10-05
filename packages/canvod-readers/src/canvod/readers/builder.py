"""Guided builder for constructing valid GNSSDataReader output Datasets.

Handles coordinate arrays, dtype enforcement, frequency resolution,
and contract validation automatically.

Examples
--------
>>> builder = DatasetBuilder(reader, time_system="GPS")
>>> for epoch in reader.iter_epochs():
...     ei = builder.add_epoch(epoch.timestamp)
...     for obs in epoch.observations:
...         sig = builder.add_signal(sv="G01", band="L1", code="C")
...         builder.set_value(ei, sig, "SNR", 42.0)
>>> ds = builder.build()   # validated Dataset
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

from canvod.readers.base import SignalID, validate_dataset
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
    SNR_METADATA,
    epoch_coord_attrs,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper

if TYPE_CHECKING:
    from canvod.readers.base import GNSSDataReader

# Metadata lookup for data variables
_VAR_METADATA: dict[str, dict] = {
    "SNR": dict(SNR_METADATA),
    "CN0": dict(CN0_METADATA),
    "Pseudorange": dict(OBSERVABLES_METADATA["Pseudorange"]),
    "Phase": dict(OBSERVABLES_METADATA["Phase"]),
    "Doppler": dict(OBSERVABLES_METADATA["Doppler"]),
    "LLI": dict(OBSERVABLES_METADATA["LLI"]),
    "SSI": dict(OBSERVABLES_METADATA["SSI"]),
}


def sid_coords(
    signals: list[SignalID], *, mapper: SignalIDMapper
) -> dict[str, xr.DataArray | tuple]:
    """Coordinates of the ``sid`` dimension for the given signals.

    ``sid`` and its per-signal coordinates (``sv``, ``system``, ``band``,
    ``code``, ``freq_center``, ``freq_min``, ``freq_max``) as required by
    :data:`~canvod.readers.base.REQUIRED_COORDS`, with their metadata.
    Frequencies come from the band; a band without a known frequency gets
    NaN.

    Parameters
    ----------
    signals : list of SignalID
        Signals in the order of the ``sid`` dimension.
    mapper : SignalIDMapper
        Band lookup for the frequencies.

    Returns
    -------
    dict
        Coordinates to pass to :class:`xarray.Dataset`.
    """
    freq_center = np.array(
        [mapper.get_band_frequency(sig.band) or np.nan for sig in signals],
        dtype=np.float32,
    )
    bandwidths = np.array(
        [mapper.get_band_bandwidth(sig.band) or 0.0 for sig in signals],
        dtype=np.float32,
    )

    def _strings(values: list[str]) -> np.ndarray:
        return np.array(values, dtype=object)

    return {
        "sid": xr.DataArray(
            _strings([sig.sid for sig in signals]),
            dims=["sid"],
            attrs=COORDS_METADATA["sid"],
        ),
        "sv": ("sid", _strings([sig.sv for sig in signals]), COORDS_METADATA["sv"]),
        "system": (
            "sid",
            _strings([sig.system for sig in signals]),
            COORDS_METADATA["system"],
        ),
        "band": (
            "sid",
            _strings([sig.band for sig in signals]),
            COORDS_METADATA["band"],
        ),
        "code": (
            "sid",
            _strings([sig.code for sig in signals]),
            COORDS_METADATA["code"],
        ),
        "freq_center": ("sid", freq_center, COORDS_METADATA["freq_center"]),
        "freq_min": (
            "sid",
            (freq_center - bandwidths / 2).astype(np.float32),
            COORDS_METADATA["freq_min"],
        ),
        "freq_max": (
            "sid",
            (freq_center + bandwidths / 2).astype(np.float32),
            COORDS_METADATA["freq_max"],
        ),
    }


class DatasetBuilder:
    """Guided builder for constructing valid GNSSDataReader output Datasets.

    Handles coordinate arrays, dtype enforcement, frequency resolution,
    and contract validation automatically.

    Parameters
    ----------
    reader : GNSSDataReader
        The reader instance (used for ``_build_attrs()`` and file hash).
    time_system : str
        Time scale of the epoch timestamps as given to :meth:`add_epoch`,
        recorded in the epoch coordinate's ``time_system`` attribute. Must be
        ``"GPS"``: canVODpy stores every epoch in GPS time, so convert other
        time scales (for example UTC, plus the leap seconds from
        :func:`canvod.readers.gnss_specs.leap_seconds.utc_to_gps`) before
        :meth:`add_epoch`. Required, since the builder cannot infer it from
        the timestamps; anything else raises ``ValueError``.
    aggregate_glonass_fdma : bool, optional
        Whether to aggregate GLONASS FDMA channels (default True).

    Examples
    --------
    >>> builder = DatasetBuilder(reader, time_system="GPS")
    >>> for epoch in reader.iter_epochs():
    ...     ei = builder.add_epoch(epoch.timestamp)
    ...     for obs in epoch.observations:
    ...         sig = builder.add_signal(sv="G01", band="L1", code="C")
    ...         builder.set_value(ei, sig, "SNR", 42.0)
    >>> ds = builder.build()   # validated Dataset
    """

    def __init__(
        self,
        reader: GNSSDataReader,
        *,
        time_system: str,
        aggregate_glonass_fdma: bool = True,
    ) -> None:
        self._reader = reader
        # Validate now, not at build() after all epochs were added.
        self._epoch_attrs = epoch_coord_attrs(time_system)
        self._mapper = SignalIDMapper(aggregate_glonass_fdma=aggregate_glonass_fdma)
        self._signals: dict[str, SignalID] = {}
        self._epochs: list[datetime] = []
        self._values: dict[str, dict[tuple[int, str], float]] = {}

    def add_epoch(self, timestamp: datetime) -> int:
        """Register an epoch timestamp. Returns epoch index."""
        self._epochs.append(timestamp)
        return len(self._epochs) - 1

    def add_signal(self, sv: str, band: str, code: str) -> SignalID:
        """Register a signal (idempotent). Returns validated SignalID."""
        sig = SignalID(sv=sv, band=band, code=code)
        self._signals[sig.sid] = sig
        return sig

    def set_value(
        self,
        epoch_idx: int,
        signal: SignalID | str,
        var: str,
        value: float,
    ) -> None:
        """Set a data value for a given epoch, signal, and variable.

        Parameters
        ----------
        epoch_idx : int
            Index returned by :meth:`add_epoch`.
        signal : SignalID or str
            Signal identifier (SignalID or 'SV|band|code' string).
        var : str
            Variable name (e.g. 'SNR', 'Pseudorange', 'Phase').
        value : float
            The observation value.
        """
        sid = str(signal)
        if var not in self._values:
            self._values[var] = {}
        self._values[var][(epoch_idx, sid)] = value

    def build(
        self,
        keep_data_vars: list[str] | None = None,
        extra_attrs: dict[str, str] | None = None,
    ) -> xr.Dataset:
        """Build, validate, and return the Dataset.

        1. Sorts signals alphabetically
        2. Resolves frequencies from band names via SignalIDMapper
        3. Constructs coordinate arrays with correct dtypes (float32 for freq)
        4. Attaches CF-compliant metadata from COORDS_METADATA
        5. Calls validate_dataset() before returning

        Parameters
        ----------
        keep_data_vars : list of str, optional
            If provided, only include these data variables.  If ``None``,
            includes all variables that had values set.
        extra_attrs : dict, optional
            Additional global attributes to merge into the Dataset.

        Returns
        -------
        xr.Dataset
            Validated Dataset with dimensions ``(epoch, sid)``.
        """
        sorted_sids = sorted(self._signals)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        n_epochs = len(self._epochs)
        n_sids = len(sorted_sids)

        # --- Coordinate arrays ---
        epoch_arr = [
            np.datetime64(ts.replace(tzinfo=None) if ts.tzinfo else ts, "ns")
            for ts in self._epochs
        ]

        # --- Determine which variables to include ---
        all_vars = set(self._values.keys())
        if keep_data_vars is not None:
            vars_to_build = [v for v in keep_data_vars if v in all_vars]
        else:
            vars_to_build = sorted(all_vars)

        # --- Data variable arrays ---
        data_vars: dict[str, tuple] = {}
        for var in vars_to_build:
            dtype = DTYPES.get(var, np.dtype("float32"))
            fill = np.nan if np.issubdtype(dtype, np.floating) else -1
            arr = np.full((n_epochs, n_sids), fill, dtype=dtype)

            for (ei, sid_str), val in self._values[var].items():
                if sid_str in sid_to_idx:
                    arr[ei, sid_to_idx[sid_str]] = val

            meta = _VAR_METADATA.get(var, {})
            data_vars[var] = (("epoch", "sid"), arr, meta)

        # --- Coordinates ---
        coords = {
            "epoch": ("epoch", epoch_arr, self._epoch_attrs),
            **sid_coords([self._signals[s] for s in sorted_sids], mapper=self._mapper),
        }

        # --- Global attributes ---
        attrs = self._reader._build_attrs()
        if extra_attrs:
            attrs.update(extra_attrs)

        ds = xr.Dataset(data_vars=data_vars, coords=coords, attrs=attrs)

        # Validate before returning
        validate_dataset(ds, required_vars=keep_data_vars)

        return ds


__all__ = ["DatasetBuilder", "sid_coords"]
