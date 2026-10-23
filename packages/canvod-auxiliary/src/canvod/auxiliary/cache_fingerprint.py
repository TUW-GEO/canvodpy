"""Fingerprinting for the network-wide aux (SP3/CLK Hermite) cache.

The aux cache is keyed by a fingerprint that is
deliberately site-independent -- ephemeris products are satellite-based, not
site-based, so the same fingerprint should hit for every site sharing the
same agency/product/ephemeris-source config on the same date, regardless of
which site's pipeline run happens to populate it first.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Target epoch grid spacing for the shared cache, independent of any single
# site's own sampling interval (finer than any real deployment's rate, so
# the consumer's nearest-neighbor `.sel()` always lands close). Included in
# the fingerprint, so bumping it later orphans old entries instead of
# silently misreading them against a coarser grid.
CANONICAL_AUX_GRID_SECONDS = 1.0

# Version of the cached content. Bump it when the computed values change for
# the same input files, so entries written by older code are not reused.
# 2: CLK clock bias read in seconds (was divided by 1e6).
AUX_CACHE_FORMAT_VERSION = 2


def compute_aux_cache_fingerprint(
    *,
    agency: str,
    product_type: str,
    ephemeris_source: str,
    canonical_grid_seconds: float,
    source_file_paths: dict[str, Path | None],
    aggregate_glonass_fdma: bool,
) -> str:
    """Compute a stable fingerprint for one day's aux cache entry.

    Deliberately excludes anything site-specific (``keep_sids``,
    ``keep_gnss_observables``, ``sampling_interval``, site identity) --
    consumers already filter the cached aux data down to their own SID/epoch
    needs at read time (see ``preprocess_with_hermite_aux`` step 2-3), so a
    broader/denser shared cache entry is always a valid superset.

    ``aggregate_glonass_fdma`` is included because it changes the GLONASS
    signal IDs of the cached data.

    Source file mtimes are included so a silent upstream reprocessing (e.g.
    rapid orbit revised to final) produces a new fingerprint rather than
    reusing a stale cache entry.
    """
    sections = {
        "format_version": AUX_CACHE_FORMAT_VERSION,
        "agency": agency,
        "product_type": product_type,
        "ephemeris_source": ephemeris_source,
        "canonical_grid_seconds": canonical_grid_seconds,
        "aggregate_glonass_fdma": aggregate_glonass_fdma,
        "source_files": {
            name: (
                {"path": str(path), "mtime": path.stat().st_mtime}
                if path is not None and path.exists()
                else None
            )
            for name, path in sorted(source_file_paths.items())
        },
    }
    return hashlib.sha256(
        json.dumps(sections, sort_keys=True, default=str).encode()
    ).hexdigest()
