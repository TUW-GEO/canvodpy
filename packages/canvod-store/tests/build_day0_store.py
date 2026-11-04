"""Write the day 0 regression baseline, ``fixtures/day0_snapshot.json``.

``test_store_regression.py`` builds a fresh store with :func:`build_store`
and compares it with this committed JSON.

    uv run python packages/canvod-store/tests/build_day0_store.py

Re-run it only for a deliberate change of the stored output (a behavioral
change of MyIcechunkStore, a new Icechunk storage format), and say why in
the commit. Do NOT re-run it during a refactor: the point is that the
baseline stays frozen, so the tests show whether the output changed.
"""

from __future__ import annotations

import hashlib  # still needed for epoch checksum
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

_TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_TESTS_DIR))

from _helpers import (  # noqa: E402
    _FIXTURES_DIR,
    GROUP,
    _array_checksum,
    make_synthetic_dataset,
)


def build_store(store_path: Path) -> dict:
    """Build a day 0 store from synthetic datasets and return a snapshot dict."""
    from canvod.store_metadata.testing import give_test_metadata

    from canvod.store import MyIcechunkStore

    if store_path.exists():
        shutil.rmtree(store_path)

    # A store takes no data without repository metadata (ADR 0014); its
    # commit is the first of the history.
    store = MyIcechunkStore(give_test_metadata(store_path))
    datasets = [make_synthetic_dataset(slot=i) for i in range(4)]

    # Write slot 0 as initial, append slots 1-3.
    # Pass explicit commit_message to work around Bug B4 (inverted branch means
    # action="append" produces None commit_message → session.commit(None) fails).
    # Once B4 is fixed this will no longer be necessary.
    store.write_initial_group(datasets[0], group_name=GROUP)
    for i, ds in enumerate(datasets[1:], start=1):
        store.append_to_group(
            ds,
            group_name=GROUP,
            action="append",
            commit_message=f"[day0] append slot {i}",
        )

    # --- Read back and capture snapshot ---
    ds_full = store.read_group(GROUP).compute()

    snapshot: dict = {
        "group": GROUP,
        "shape": {dim: int(sz) for dim, sz in ds_full.sizes.items()},
        "variables": {},
        "metadata_table": {},
        "history_count": len(store.get_history()),
        "branches": store.get_branch_names(),
    }

    for var in ds_full.data_vars:
        arr = ds_full[var].values
        snapshot["variables"][var] = {
            "dtype": str(arr.dtype),
            "shape": list(arr.shape),
            "checksum": _array_checksum(arr),
            "nan_fraction": float(np.isnan(arr).mean()),
        }

    # Epoch coordinate
    epoch_vals = ds_full.epoch.values.astype("int64")
    snapshot["epoch_checksum"] = hashlib.sha256(epoch_vals.tobytes()).hexdigest()[:16]
    snapshot["epoch_start"] = str(ds_full.epoch.values[0])
    snapshot["epoch_end"] = str(ds_full.epoch.values[-1])
    snapshot["n_epochs"] = int(ds_full.sizes["epoch"])

    # Metadata table
    with store.readonly_session() as session:
        try:
            df = store.load_metadata(session.store, GROUP)
            snapshot["metadata_table"] = {
                "n_rows": df.height,
                "hashes": df["rinex_hash"].to_list(),
                "actions": df["action"].to_list(),
            }
        except Exception as e:
            snapshot["metadata_table"] = {"error": str(e)}

    return snapshot


def main() -> None:
    from canvod.utils import testing

    with tempfile.TemporaryDirectory() as tmp:
        # The made-up settings of the tests, never the user's own.
        os.environ["CANVOD_CONFIG_DIR"] = str(Path(tmp) / "settings")
        os.environ.pop("CANVOD_CONFIG_FILE", None)
        testing.write_settings(Path(tmp) / "settings")
        snapshot = build_store(Path(tmp) / "day0_store")

    snapshot_path = _FIXTURES_DIR / "day0_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"  Snapshot: {snapshot_path}")
    print(f"  Shape:    {snapshot['shape']}")
    print(f"  History:  {snapshot['history_count']} commits")
    print(f"  Rows:     {snapshot['metadata_table'].get('n_rows', 'n/a')}")


if __name__ == "__main__":
    main()
