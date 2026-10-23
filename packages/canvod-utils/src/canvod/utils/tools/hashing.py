"""Hashing utilities for canVODpy.

The file hash identifies a file's content in the stores (deduplication,
log book). Every reader computes it here, so stored hashes stay
comparable across readers and versions.
"""

import hashlib
from pathlib import Path

#: Length of the hash: the first 16 hex digits of the SHA-256 digest.
HASH_LENGTH = 16


def _short(hexdigest: str) -> str:
    return hexdigest[:HASH_LENGTH]


def bytes_hash(data: bytes) -> str:
    """
    Compute the file hash of content already read into memory.

    Gives the same value as :func:`file_hash` on a file with this content;
    use it when a reader has the file's bytes anyway.

    Parameters
    ----------
    data : bytes
        The file's complete content.

    Returns
    -------
    str
        First 16 characters of the SHA-256 hex digest.

    Examples
    --------
    >>> bytes_hash(b"")
    'e3b0c44298fc1c14'
    """
    return _short(hashlib.sha256(data).hexdigest())


def file_hash(path: Path, chunk_size: int = 8192) -> str:
    """
    Compute SHA256 hash of a GNSS data file's content.

    Uses first 16 characters of the SHA256 hexdigest for a compact hash.

    Parameters
    ----------
    path : Path
        Path to GNSS data file.
    chunk_size : int, optional
        Size of chunks to read (default: 8192 bytes).

    Returns
    -------
    str
        First 16 characters of SHA256 hash.

    Examples
    --------
    >>> from pathlib import Path
    >>> hash_val = file_hash(Path("data.rnx"))
    >>> len(hash_val)
    16
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return _short(h.hexdigest())
