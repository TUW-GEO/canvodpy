"""Shared test helpers for canvod-store tests.

Importable by both conftest.py (for pytest fixtures) and build_day0_store.py
(standalone script). Kept separate from conftest.py because bare
``from conftest import ...`` in build_day0_store.py resolves to the
monorepo-root conftest when pytest is run from the repo root.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent
_FIXTURES_DIR = _TESTS_DIR / "fixtures"
DAY0_STORE_PATH = _FIXTURES_DIR / "day0_store"

TEST_DATA_ROOT = (
    Path(__file__).parents[3]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
    / "valid"
)

RINEX_CANOPY_DIR = (
    TEST_DATA_ROOT
    / "rinex_v3_04"
    / "01_Rosalia"
    / "02_canopy"
    / "01_GNSS"
    / "01_raw"
    / "25001"
)

RINEX_REFERENCE_DIR = (
    TEST_DATA_ROOT
    / "rinex_v3_04"
    / "01_Rosalia"
    / "01_reference"
    / "01_GNSS"
    / "01_raw"
    / "25001"
)

# ---------------------------------------------------------------------------
# Synthetic dataset helpers
# ---------------------------------------------------------------------------

GROUP = "canopy_01"

_SIDS = [
    f"{sv}|{band}|{code}"
    for sv in [
        "G01",
        "G02",
        "G03",
        "G04",
        "G05",
        "G06",
        "G07",
        "G08",
        "E01",
        "E02",
        "E03",
        "E04",
        "E05",
        "R01",
        "R02",
        "R03",
        "R04",
        "C01",
        "C02",
        "C03",
    ]
    for band, code in [("L1", "C"), ("L2", "W")]
]
N_SIDS = len(_SIDS)  # 40 — representative, not full 321 (keeps tests fast)


def _array_checksum(arr: np.ndarray) -> str:
    """SHA-256 of array bytes (NaN → 0 before hashing for stability)."""
    safe = np.where(np.isnan(arr.astype(float)), 0.0, arr.astype(float))
    return hashlib.sha256(safe.tobytes()).hexdigest()[:16]


def make_synthetic_dataset(
    slot: int,
    n_epochs: int = 180,
    seed: int = 0,
    day: str = "2025-01-01",
) -> xr.Dataset:
    """Return a synthetic GNSS dataset resembling real RINEX v3 output.

    Parameters
    ----------
    slot : int
        15-minute slot index (0 = 00:00, 1 = 00:15, …).
    n_epochs : int
        Number of epochs (180 = 15 min at 5 s cadence).
    seed : int
        RNG seed for reproducibility.
    day : str
        ISO date string for the epoch start.

    Returns
    -------
    xr.Dataset
        Dataset with dims ``(epoch, sid)`` and a ``"File Hash"`` attribute.
    """
    rng = np.random.default_rng(seed + slot)

    base = np.datetime64(f"{day}T{(slot * 15) // 60:02d}:{(slot * 15) % 60:02d}:00")
    epochs = base + np.arange(n_epochs) * np.timedelta64(5, "s")

    s1c = rng.uniform(30.0, 55.0, (n_epochs, N_SIDS)).astype(np.float32)
    mask = rng.random((n_epochs, N_SIDS)) > 0.8
    s1c[mask] = np.nan

    s2w = s1c - rng.uniform(1.0, 3.0, (n_epochs, N_SIDS)).astype(np.float32)
    s2w[mask] = np.nan

    raw = f"slot={slot}|seed={seed}|day={day}".encode()
    file_hash = hashlib.sha256(raw).hexdigest()[:16]

    return xr.Dataset(
        {
            "S1C": xr.DataArray(s1c, dims=["epoch", "sid"]),
            "S2W": xr.DataArray(s2w, dims=["epoch", "sid"]),
        },
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            "sid": _SIDS,
        },
        attrs={
            "File Hash": file_hash,
            "station": "FANT",
            "receiver": "canopy_01",
        },
    )


def make_synthetic_vod_dataset(
    slot: int,
    n_epochs: int = 180,
    seed: int = 0,
    day: str = "2025-01-01",
) -> xr.Dataset:
    """Return a synthetic VOD dataset meeting the VOD dataset contract.

    Same epochs and sids as :func:`make_synthetic_dataset`; ``VOD``,
    ``phi`` and ``theta`` (radians) with the full sid coordinates.
    """
    from canvod.readers.base import SignalID
    from canvod.readers.builder import sid_coords
    from canvod.readers.gnss_specs.signals import SignalIDMapper

    obs = make_synthetic_dataset(slot, n_epochs=n_epochs, seed=seed, day=day)
    rng = np.random.default_rng(seed + slot)
    vod = rng.uniform(0.0, 1.5, (n_epochs, N_SIDS))
    vod[np.isnan(obs["S1C"].values)] = np.nan
    signals = [SignalID.from_string(sid) for sid in _SIDS]
    return xr.Dataset(
        {
            "VOD": (("epoch", "sid"), vod),
            "phi": (("epoch", "sid"), rng.uniform(0, 2 * np.pi, vod.shape)),
            "theta": (("epoch", "sid"), rng.uniform(0, np.pi / 2, vod.shape)),
        },
        coords={
            "epoch": (
                "epoch",
                obs["epoch"].values.astype("datetime64[ns]"),
                {"time_system": "GPS"},
            ),
            **sid_coords(signals, mapper=SignalIDMapper()),
        },
    )


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


def new_gnss_store(path: Path):
    """A new GNSS store with the made-up site's repository metadata.

    A store takes no data without repository metadata (ADR 0014).
    """
    from canvod.store_metadata.testing import give_test_metadata

    from canvod.store import open_gnss_store

    return open_gnss_store(give_test_metadata(path, "gnss_store"))


def new_vod_store(path: Path):
    """A new VOD store with the made-up site's repository metadata."""
    from canvod.store_metadata.testing import give_test_metadata

    from canvod.store import open_vod_store

    return open_vod_store(give_test_metadata(path, "vod_store"))
