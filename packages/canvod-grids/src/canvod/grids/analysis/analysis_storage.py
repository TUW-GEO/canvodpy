"""Old location of ``AnalysisStorage``, which now lives in canvod-store.

``canvod.grids.analysis.AnalysisStorage`` calls
``canvod.store.AnalysisStorage`` and needs ``canvod-store`` installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canvod.utils.tools import deprecated

if TYPE_CHECKING:
    from canvod.store.analysis_storage import (
        AnalysisStorage as AnalysisStorageType,
    )


@deprecated(
    "canvod.grids.analysis.AnalysisStorage is left over from development and "
    "will be removed with the next major version. Use "
    "canvod.store.AnalysisStorage instead."
)
def AnalysisStorage(store_path: Path | str) -> AnalysisStorageType:
    """Return ``canvod.store.AnalysisStorage(store_path)``.

    Parameters
    ----------
    store_path : Path or str
        Path to the VOD Icechunk store.

    Returns
    -------
    canvod.store.AnalysisStorage
        Storage of the analysis results in that store.
    """
    from canvod.store.analysis_storage import AnalysisStorage as _AnalysisStorage

    return _AnalysisStorage(store_path)
