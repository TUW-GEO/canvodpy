"""File system size helpers, shared across packages.

Nothing here knows about stores; the functions are about folders and
files. The run dashboard and the store-metadata summary both walk a
store folder to report its size, so the walk lives here once.
"""

from __future__ import annotations

from pathlib import Path


def directory_size_bytes(path: Path) -> int:
    """The total size in bytes of the files under *path*, recursively.

    Directories count nothing themselves; only the sizes of the regular
    files below *path* are summed. A missing path sums to zero.
    """
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
