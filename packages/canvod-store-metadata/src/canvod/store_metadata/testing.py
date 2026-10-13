"""Stores with made-up repository metadata, for tests.

A store takes no data without its repository metadata (ADR 0014). Tests
that write to a store directly, without a run, give it metadata first:

    from canvod.store_metadata.testing import give_test_metadata

    store = MyIcechunkStore(tmp_path / "store")
    give_test_metadata(store.store_path)

The metadata describes the made-up site of :mod:`canvod.utils.testing`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from pathlib import Path

from canvod.utils import testing

from .io import write_metadata
from .location import open_repository
from .schema import (
    Creator,
    Instruments,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
    VodAnalysisInfo,
)

_SUFFIX = {"gnss_store": "gnss", "vod_store": "vod"}

#: The receivers of the made-up site, by name and type.
RECEIVERS = {"canopy_01": "canopy", "reference_01": "reference"}
#: Its VOD analysis.
VOD_ANALYSES = {"canopy_01_vs_reference_01": ("canopy_01", "reference_01")}


def made_up_metadata(
    store_type: str = "gnss_store",
    *,
    receivers: Mapping[str, str] = RECEIVERS,
    vod_analyses: Mapping[str, tuple[str, str]] = VOD_ANALYSES,
) -> StoreMetadata:
    """The made-up site's store metadata.

    Parameters
    ----------
    store_type
        ``"gnss_store"`` or ``"vod_store"``.
    receivers
        Receiver name to type (``"canopy"`` or ``"reference"``).
    vod_analyses
        VOD analysis name to (canopy receiver, reference receiver); a GNSS
        store lists none.
    """
    suffix = _SUFFIX[store_type]
    store_id = f"{testing.SITE_KEY}-{suffix}"
    return StoreMetadata(
        identity=StoreIdentity(
            id=store_id,
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority=testing.NAMING_AUTHORITY,
            stac_link=f"../../{suffix}/{store_id}/{store_id}.json",
            title=f"{testing.CANOPY_SITE} {suffix.upper()} store",
            store_type=store_type,
            source_format="rinex3",
        ),
        creator=Creator(
            name=testing.PERSON_NAME,
            email=testing.PERSON_EMAIL,
            institution=testing.INSTITUTION,
        ),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z"
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name=testing.SITE_KEY),
            geospatial_lat=testing.LATITUDE,
            geospatial_lon=testing.LONGITUDE,
        ),
        instruments=Instruments(
            receivers={
                name: ReceiverInfo(type=kind, directory=name)
                for name, kind in receivers.items()
            }
        ),
        vod_analyses={
            name: VodAnalysisInfo(canopy_receiver=canopy, reference_receiver=ref)
            for name, (canopy, ref) in vod_analyses.items()
        }
        if store_type == "vod_store"
        else {},
    )


def give_test_metadata(
    store_path: Path | str,
    store_type: str = "gnss_store",
    *,
    receivers: Mapping[str, str] = RECEIVERS,
    vod_analyses: Mapping[str, tuple[str, str]] = VOD_ANALYSES,
) -> Path:
    """Give a store the made-up site's repository metadata.

    Creates the Icechunk repository if there is none at ``store_path``.

    Returns
    -------
    Path
        ``store_path``.
    """
    path = Path(store_path)
    with contextlib.suppress(FileExistsError):
        open_repository(path, create=True)
    write_metadata(
        path,
        made_up_metadata(store_type, receivers=receivers, vod_analyses=vod_analyses),
    )
    return path
