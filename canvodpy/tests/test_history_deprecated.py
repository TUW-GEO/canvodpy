"""history_entry() is deprecated: the history of a store is its commit log."""

import pytest
from canvodpy.utils.history import history_entry


def test_history_entry_warns_and_still_works():
    with pytest.warns(FutureWarning, match="commit log"):
        entry = history_entry("2026-01-01T00:00:00Z", "Ingest", {"canopy_01": "none"})
    assert entry.startswith("2026-01-01T00:00:00Z: Ingest (canvodpy ")
