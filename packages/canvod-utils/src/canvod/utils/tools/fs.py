"""File system helpers, shared across packages.

Nothing here knows about stores; the functions are about folders and
files. The run dashboard and the store-metadata summary both walk a
store folder to report its size, so the walk lives here once. Copied
recipes and downloaded orbit files both need the mode of a new file, so
that lives here once too.
"""

from __future__ import annotations

import os
from pathlib import Path


def _umask() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return umask


#: The mode ``open()`` gives a new file in this process (``0o666`` less the
#: umask). Files made with ``tempfile.mkstemp`` are owner-only (0600) and
#: ``os.replace`` keeps that; chmod them to this so files in a shared folder
#: stay readable. Read once at import: ``os.umask`` can only be read by
#: setting it, which is process-wide, so reading it while threads create
#: files could give one of them the wrong mode.
NEW_FILE_MODE: int = 0o666 & ~_umask()


def directory_size_bytes(path: Path) -> int:
    """The total size in bytes of the files under *path*, recursively.

    Directories count nothing themselves; only the sizes of the regular
    files below *path* are summed. A missing path (or one that is not a
    directory) sums to zero. The folder is written while it is walked, so
    a file that vanishes between the listing and its ``stat()`` is
    skipped, not an error. Symbolic links are not followed and their own
    size is not counted.
    """
    if not path.is_dir():
        return 0
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        # The entry was removed or renamed between the
                        # listing and the read, or its type could not be
                        # read; skip it.
                        continue
        except OSError:
            # The directory could not be entered (permissions, removed).
            continue
    return total
