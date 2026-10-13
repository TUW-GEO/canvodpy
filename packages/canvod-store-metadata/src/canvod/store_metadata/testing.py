"""Stores with made-up repository metadata, for tests.

A store takes no data without its repository metadata (ADR 0014), and
opening a store never creates it. Tests that write to a store directly,
without a run, create it with metadata first:

    from canvod.store_metadata.testing import give_test_metadata

    store = MyIcechunkStore(give_test_metadata(tmp_path / "store"))

The metadata describes the made-up site of :mod:`canvod.utils.testing`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from canvod.utils import testing

from .identity import stac_link
from .io import _set_field, commit_with_rebase, ensure_metadata
from .location import open_repository
from .schema import (
    Creator,
    Instruments,
    Publisher,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
    VodAnalysisInfo,
)

_SUFFIX = {"gnss_store": "gnss", "vod_store": "vod", "geodesy_store": "geodesy"}

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
        ``"gnss_store"``, ``"vod_store"`` or ``"geodesy_store"``.
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
            stac_link=stac_link(testing.NAMING_AUTHORITY, store_id, store_type),
            title=f"{testing.CANOPY_SITE} {suffix.upper()} store",
            store_type=store_type,
            source_format="rinex3",
        ),
        creator=Creator(
            name=testing.PERSON_NAME,
            email=testing.PERSON_EMAIL,
            institution=testing.INSTITUTION,
        ),
        publisher=Publisher(name=testing.PUBLISHER, license="CC-BY-4.0"),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z"
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name=testing.SITE_KEY),
            geospatial_lat=testing.LATITUDE,
            geospatial_lon=testing.LONGITUDE,
            geospatial_alt_m=testing.ALTITUDE_M,
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


def create_test_store(store_path: Path | str) -> Path:
    """Create an empty store at ``store_path``, without repository metadata.

    For tests that don't write data, or that test a store without
    metadata; tests that write data use :func:`give_test_metadata`.

    Returns
    -------
    Path
        ``store_path``.
    """
    path = Path(store_path)
    open_repository(path, create=True)
    return path


def give_test_metadata(
    store_path: Path | str,
    store_type: str = "gnss_store",
    *,
    receivers: Mapping[str, str] = RECEIVERS,
    vod_analyses: Mapping[str, tuple[str, str]] = VOD_ANALYSES,
) -> Path:
    """Give a store the made-up site's repository metadata.

    Creates the store if there is none at ``store_path``, the way a run
    does (:func:`~.io.ensure_metadata`); a store that already has
    repository metadata keeps it.

    Returns
    -------
    Path
        ``store_path``.
    """
    path = Path(store_path)
    ensure_metadata(
        path,
        lambda: made_up_metadata(
            store_type, receivers=receivers, vod_analyses=vod_analyses
        ),
        site_name=testing.SITE_KEY,
        store_type=store_type,
    )
    return path


def write_unchecked(store_path: Path | str, changes: Mapping[str, Any]) -> Path:
    """Change repository metadata fields without the model's rules.

    For tests of stores that hold values a rule now refuses, as written by
    an older canvodpy or edited by hand: the changes are committed and
    recorded like an amendment, but not checked.

    Parameters
    ----------
    store_path
        The store's directory.
    changes
        New values by dotted field path, e.g. ``{"publisher.license": "x"}``.

    Returns
    -------
    Path
        ``store_path``.
    """
    path = Path(store_path)
    repo = open_repository(path)
    repository = copy.deepcopy(repo.get_metadata())
    for field, value in changes.items():
        old = _set_field(repository, field, value)
        repository["amendments"].append(
            {
                "field": field,
                "old": old,
                "new": value,
                "reason": "unchecked change (test)",
                "who": "test",
                "when": "2026-01-01T00:00:00+00:00",
            }
        )
    commit_with_rebase(
        repo.writable_session("main"),
        "Unchecked metadata change (test)",
        store_path=path,
        repository=repository,
    )
    repo.set_metadata(repository)
    return path
