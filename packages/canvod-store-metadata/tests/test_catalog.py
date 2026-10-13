"""The STAC catalog at the data root (ADR 0015)."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pystac
import pytest
import xarray as xr
from canvod.utils import testing
from stac_validator.validate import StacValidate

from canvod.store_metadata import (
    commit_with_rebase,
    open_repository,
    write_catalog,
    write_metadata,
)
from canvod.store_metadata.identity import stac_link, store_id
from canvod.store_metadata.schema import Publisher
from canvod.store_metadata.testing import made_up_metadata

_SCHEMAS = Path(__file__).parent / "stac_schemas"


def _schema_map() -> dict[str, str]:
    """Remote schema URL -> local file: validation needs no network.

    The STAC core and GeoJSON schemas come with pystac; extension schemas
    are kept in ``stac_schemas``.
    """
    pystac_schemas = importlib.resources.files("pystac.validation.jsonschemas")
    core = "https://schemas.stacspec.org/v1.1.0"
    mapping = {
        f"{core}/{name}-spec/json-schema/{name}.json": str(
            pystac_schemas / "stac-spec" / "v1.1.0" / f"{name}.json"
        )
        for name in ("item", "catalog", "collection")
    }
    mapping |= {
        f"{core}/item-spec/json-schema/{name}.json": str(
            pystac_schemas / "stac-spec" / "v1.1.0" / f"{name}.json"
        )
        for name in (
            "bands",
            "basics",
            "common",
            "data-values",
            "datetime",
            "instrument",
            "licensing",
            "provider",
        )
    }
    mapping |= {
        f"https://geojson.org/schema/{name}.json": str(
            pystac_schemas / "geojson" / f"{name}.json"
        )
        for name in ("Feature", "Geometry")
    }
    mapping["https://stac-extensions.github.io/xarray-assets/v1.0.0/schema.json"] = str(
        _SCHEMAS / "xarray-assets-v1.0.0.json"
    )
    return mapping


def _assert_valid(path: Path) -> None:
    """Every file reachable from ``path`` validates against its schemas."""
    validator = StacValidate(str(path), recursive=True, schema_map=_schema_map())
    assert validator.run(), json.dumps(validator.message, indent=2)


def _observations(n_epochs: int = 12, start: str = "2025-01-01") -> xr.Dataset:
    epochs = pd.date_range(start, periods=n_epochs, freq="5s")
    sids = ["G01|L1|C", "E11|E1|C"]
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((n_epochs, len(sids)), 40.0, "f4"))},
        coords={"epoch": epochs, "sid": sids},
    )


def _gnss_store(
    path: Path,
    receivers: tuple[str, ...] = ("canopy_01",),
    *,
    publisher: Publisher | None = None,
    site: str = testing.SITE_KEY,
    start: str = "2025-01-01",
) -> Path:
    """A GNSS store holding observations per receiver.

    Of the made-up site, unless ``site`` names another one (same position,
    another store id).
    """
    meta = made_up_metadata()
    if publisher is not None:
        meta.publisher = publisher
    if site != testing.SITE_KEY:
        meta.spatial.site.name = site
        meta.identity.id = store_id(site, "gnss_store")
        meta.identity.stac_link = stac_link(
            testing.NAMING_AUTHORITY, meta.identity.id, "gnss_store"
        )
    open_repository(path, create=True)
    write_metadata(path, meta)
    session = open_repository(path).writable_session("main")
    for receiver in receivers:
        _observations(start=start).to_zarr(
            session.store, group=receiver, mode="w", consolidated=False
        )
    commit_with_rebase(session, "observations", store_path=path)
    return path


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "stores"
    _gnss_store(root / testing.SITE_KEY / "gnss", ("canopy_01", "reference_01"))
    return root


def test_write_catalog_writes_a_valid_catalog_of_the_gnss_stores(data_root):
    _gnss_store(data_root / "orthanc" / "gnss", site="orthanc", start="2025-03-01")

    catalog_path = write_catalog(data_root)

    assert catalog_path == data_root / "catalog.json"
    _assert_valid(catalog_path)
    catalog = pystac.Catalog.from_file(catalog_path)
    collection = catalog.get_child("gnss-observations")
    assert isinstance(collection, pystac.Collection)
    assert sorted(item.id for item in collection.get_items()) == [
        f"{testing.NAMING_AUTHORITY}.{testing.SITE_KEY}-gnss",
        f"{testing.NAMING_AUTHORITY}.orthanc-gnss",
    ]
    interval = collection.extent.temporal.intervals[0]
    assert [t.isoformat() for t in interval] == [
        "2025-01-01T00:00:00+00:00",
        "2025-03-01T00:00:55+00:00",
    ]


def test_a_folder_that_only_looks_like_a_store_is_left_out(data_root):
    lookalike = data_root / "orthanc" / "gnss"
    (lookalike / "snapshots").mkdir(parents=True)
    (lookalike / "transactions").mkdir()

    catalog = pystac.Catalog.from_file(write_catalog(data_root))

    assert [item.id for item in catalog.get_items(recursive=True)] == [
        f"{testing.NAMING_AUTHORITY}.{testing.SITE_KEY}-gnss"
    ]


def _item(catalog_root: Path) -> pystac.Item:
    catalog = pystac.Catalog.from_file(catalog_root / "catalog.json")
    return next(catalog.get_items(recursive=True))


def _open_asset(asset: pystac.Asset) -> xr.Dataset:
    """Open what an asset names: its store, at its snapshot, its group."""
    import icechunk

    storage = icechunk.local_filesystem_storage(asset.get_absolute_href())
    session = icechunk.Repository.open(storage).readonly_session(
        snapshot_id=asset.extra_fields["canvod:snapshot_id"]
    )
    return xr.open_dataset(session.store, **asset.extra_fields["xarray:open_kwargs"])


def test_an_asset_names_the_store_snapshot_and_group_to_open(data_root):
    write_catalog(data_root)

    item = _item(data_root)

    assert sorted(item.assets) == ["canopy_01", "reference_01"]
    asset = item.assets["canopy_01"]
    assert asset.media_type == "application/vnd.zarr; version=3"
    assert asset.roles == ["data", "latest-version"]
    ds = _open_asset(asset)
    assert ds.sizes == {"epoch": 12, "sid": 2}
    assert "SNR" in ds


def test_the_catalog_still_works_after_copying_the_data_root(data_root, tmp_path):
    import shutil

    write_catalog(data_root)
    copy = tmp_path / "copy"
    shutil.copytree(data_root, copy)
    shutil.rmtree(data_root)

    _assert_valid(copy / "catalog.json")
    ds = _open_asset(_item(copy).assets["reference_01"])
    assert ds.sizes == {"epoch": 12, "sid": 2}


def test_each_stores_catalog_link_points_at_its_item(data_root):
    from canvod.store_metadata import read_metadata

    write_catalog(data_root)

    store = data_root / testing.SITE_KEY / "gnss"
    link = read_metadata(store).identity.stac_link
    item_file = (store / link).resolve()
    assert item_file.is_file()
    assert json.loads(item_file.read_text())["id"] == _item(data_root).id


def test_an_spdx_license_is_kept_with_a_link_to_its_text(tmp_path):
    root = tmp_path / "stores"
    _gnss_store(
        root / testing.SITE_KEY / "gnss",
        publisher=Publisher(
            license="CC-BY-4.0",
            license_uri="https://creativecommons.org/licenses/by/4.0/",
        ),
    )

    write_catalog(root)

    item = _item(root)
    assert item.properties["license"] == "CC-BY-4.0"
    assert [link.href for link in item.links if link.rel == "license"] == [
        "https://creativecommons.org/licenses/by/4.0/"
    ]


def test_a_license_outside_spdx_is_other_with_a_link_to_its_text(tmp_path):
    root = tmp_path / "stores"
    _gnss_store(
        root / testing.SITE_KEY / "gnss",
        publisher=Publisher(license_uri="https://the.inklings.org/data-licence"),
    )

    write_catalog(root)

    _assert_valid(root / "catalog.json")
    item = _item(root)
    assert item.properties["license"] == "other"
    assert [link.href for link in item.links if link.rel == "license"] == [
        "https://the.inklings.org/data-licence"
    ]
