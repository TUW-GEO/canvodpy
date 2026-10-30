"""Septentrio Binary Format (SBF) reader for canvod-readers.

Decodes MeasEpoch blocks from ``.sbf`` files produced by AsteRx SB3 ProBase
receivers running firmware v4.14.x.

Quick Start
-----------
>>> from canvod.readers.sbf import SbfReader
>>> from canvod.readers.sbf._registry import svid_to_sv
>>> reader = SbfReader(fpath=Path("rref213a00.25_"))
>>> print(reader.header.rx_version)
4.14.4
>>> for epoch in reader.iter_epochs():
...     for obs in epoch.observations:
...         print(f"{svid_to_sv(obs.svid)}  CN0={obs.cn0:.1f} dB-Hz")

Data Models
-----------
:class:`~canvod.readers.sbf.models.SbfHeader`
    Receiver setup metadata (from ReceiverSetup block).
:class:`~canvod.readers.sbf.models.SbfEpoch`
    One observation epoch (from MeasEpoch block).
:class:`~canvod.readers.sbf.models.SbfSignalObs`
    One decoded signal observation (physical units, DNU → ``None``).

Registry / Scaling
------------------
Internal helpers are intentionally **not** re-exported here; import them
directly from ``canvod.readers.sbf._registry`` or
``canvod.readers.sbf._scaling`` if needed.
"""

from canvod.readers.sbf.models import SbfEpoch, SbfHeader, SbfSignalObs
from canvod.readers.sbf.reader import SbfReader

__all__ = [
    "SbfEpoch",
    "SbfHeader",
    "SbfReader",
    "SbfSignalObs",
]
