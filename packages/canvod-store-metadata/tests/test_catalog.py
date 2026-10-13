"""The STAC catalog at the data root (ADR 0015)."""

from __future__ import annotations

import importlib.resources
import json
import shutil
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
    create_release,
    open_repository,
    read_metadata,
    validate_all,
    write_catalog,
    write_metadata,
)
from canvod.store_metadata.identity import stac_link, store_id
from canvod.store_metadata.schema import Publisher
from canvod.store_metadata.testing import (
    create_test_store,
    made_up_metadata,
    write_unchecked,
)

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
    mapping["https://stac-extensions.github.io/datacube/v2.2.0/schema.json"] = str(
        _SCHEMAS / "datacube-v2.2.0.json"
    )
    return mapping


def _assert_valid(path: Path) -> None:
    """Every file reachable from ``path`` validates against its schemas."""
    # stac-validator finds children by splitting the path at "/".
    validator = StacValidate(path.as_posix(), recursive=True, schema_map=_schema_map())
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
    longitude: float | None = None,
) -> Path:
    """A GNSS store holding observations per receiver.

    Of the made-up site, unless ``site`` names another one (same position,
    unless ``longitude`` moves it; another store id).
    """
    meta = made_up_metadata()
    if publisher is not None:
        meta.publisher = publisher
    if longitude is not None:
        meta.spatial.geospatial_lon = longitude
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


class TestTheCatalogLinkBeforeTheFirstCatalogWrite:
    """A new store is valid before the first catalog write (ADR 0015)."""

    @staticmethod
    def _link_issues(store: Path, *, recommended: bool) -> list[str]:
        issues = validate_all(
            read_metadata(store), recommended=recommended, store_path=store
        )
        return [
            issue
            for issues in issues.values()
            for issue in issues
            if "stac_link" in issue
        ]

    def test_a_dangling_link_is_a_warning_not_a_failure(self, data_root):
        store = data_root / testing.SITE_KEY / "gnss"

        assert self._link_issues(store, recommended=False) == []
        (warning,) = self._link_issues(store, recommended=True)
        assert warning.startswith("[warning]")
        assert "canvodpy stac write" in warning

    def test_no_warning_once_the_catalog_is_written(self, data_root):
        store = data_root / testing.SITE_KEY / "gnss"

        write_catalog(data_root)

        assert self._link_issues(store, recommended=True) == []


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
        publisher=Publisher(
            license="other", license_uri="https://the.inklings.org/data-licence"
        ),
    )

    write_catalog(root)

    _assert_valid(root / "catalog.json")
    item = _item(root)
    assert item.properties["license"] == "other"
    assert [link.href for link in item.links if link.rel == "license"] == [
        "https://the.inklings.org/data-licence"
    ]


def _old_form_store(path: Path) -> Path:
    """A store written before stores kept repository metadata (ADR 0014)."""
    import zarr

    session = open_repository(path, create=True).writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    root.attrs.update(made_up_metadata().to_root_attrs())
    _observations().to_zarr(session.store, group="canopy_01", consolidated=False)
    session.commit("data and metadata, old form")
    return path


def _files(root: Path) -> set[Path]:
    return {path for path in root.rglob("*")}


class TestStoresTheCatalogCannotDescribe:
    @pytest.fixture
    def root_with_bad_stores(self, data_root: Path) -> Path:
        """The good store of ``data_root`` and one bad store per reason."""
        broken = _gnss_store(data_root / "isengard" / "gnss", site="isengard")
        (broken / "repo").write_bytes(b"not an icechunk repository")
        _old_form_store(data_root / "moria" / "gnss")
        create_test_store(data_root / "rohan" / "gnss")
        write_unchecked(
            _gnss_store(data_root / "gondor" / "gnss", site="gondor"),
            {"spatial.geospatial_lat": None, "spatial.geospatial_lon": None},
        )
        write_unchecked(
            _gnss_store(data_root / "mordor" / "gnss", site="mordor"),
            {"publisher.license": "Apache 2"},
        )
        write_unchecked(
            _gnss_store(data_root / "shire" / "gnss", site="shire"),
            {"publisher.license": None},
        )
        # Metadata, but no data: a run that created the store and stopped.
        empty = data_root / "erebor" / "gnss"
        open_repository(empty, create=True)
        write_metadata(empty, made_up_metadata())
        return data_root

    def test_one_error_names_every_bad_store_with_its_reason(
        self, root_with_bad_stores
    ):
        with pytest.raises(ValueError) as caught:
            write_catalog(root_with_bad_stores)

        lines = str(caught.value).splitlines()

        def reason(store: str) -> str:
            return next(line for line in lines if f"{store}/gnss" in line)

        assert "cannot be opened" in reason("isengard")
        assert "needs migration" in reason("moria")
        assert "no metadata" in reason("rohan")
        assert "no site position" in reason("gondor")
        assert "'Apache 2' is not an SPDX license identifier" in reason("mordor")
        assert "no license" in reason("shire")
        assert "holds no data" in reason("erebor")
        assert not any(f"{testing.SITE_KEY}/gnss" in line for line in lines)

    def test_a_store_needing_migration_is_named_with_the_migrate_command(
        self, root_with_bad_stores
    ):
        with pytest.raises(ValueError, match="canvodpy store migrate-metadata"):
            write_catalog(root_with_bad_stores)

    def test_nothing_is_written(self, root_with_bad_stores):
        before = _files(root_with_bad_stores)

        with pytest.raises(ValueError):
            write_catalog(root_with_bad_stores)

        assert _files(root_with_bad_stores) == before


# --- Every product and every stored dataset (#244) ----------------------------

_VOD_GROUP = "tau_omega_zeroth_order/canopy_01_vs_reference_01"
_HEADER = {
    "APPROX POSITION X": testing.ECEF_X,
    "APPROX POSITION Y": testing.ECEF_Y,
    "APPROX POSITION Z": testing.ECEF_Z,
}


def _log_book(n_files: int = 1) -> xr.Dataset:
    """A log book of ``n_files`` stored files, each with the site's header position."""
    rows = range(n_files)
    return xr.Dataset(
        {
            "rinex_hash": ("row", [f"hash{i}" for i in rows]),
            "action": ("row", ["initial"] * n_files),
            "attrs": ("row", [json.dumps(_HEADER)] * n_files),
        }
    )


def _sbf_obs(n_epochs: int = 12) -> xr.Dataset:
    epochs = pd.date_range("2025-01-01", periods=n_epochs, freq="5s")
    sids = ["G01|L1|C", "E11|E1|C"]
    return xr.Dataset(
        {
            "broadcast_theta": (("epoch", "sid"), np.full((n_epochs, 2), 0.5, "f4")),
            "pdop": ("epoch", np.full(n_epochs, 1.5, "f4")),
        },
        coords={"epoch": epochs, "sid": sids, "sv": ("sid", ["G01", "E11"])},
    )


def _store(
    path: Path,
    store_type: str,
    groups: dict[str, xr.Dataset],
    *,
    naming_authority: str = testing.NAMING_AUTHORITY,
) -> Path:
    """A store of the made-up site holding ``groups``."""
    meta = made_up_metadata(store_type)
    meta.identity.naming_authority = naming_authority
    open_repository(path, create=True)
    write_metadata(path, meta)
    session = open_repository(path).writable_session("main")
    for group, ds in groups.items():
        ds.to_zarr(session.store, group=group, mode="w", consolidated=False)
    commit_with_rebase(session, "data", store_path=path)
    return path


@pytest.fixture
def every_product(tmp_path: Path) -> Path:
    """A data root with a GNSS store (with SBF metadata), a VOD store and a
    geodesy store of the made-up site."""
    root = tmp_path / "stores"
    site = root / testing.SITE_KEY
    _store(
        site / "gnss",
        "gnss_store",
        {
            "canopy_01": _observations(),
            "canopy_01/metadata/sbf_obs": _sbf_obs(),
            "canopy_01/metadata/table": _log_book(),
            "reference_01": _observations(),
            "reference_01/metadata/table": _log_book(),
        },
    )
    vod = _observations().rename({"SNR": "VOD"})
    vod["theta"] = vod["VOD"] * 0 + 0.3
    _store(
        site / "vod",
        "vod_store",
        {_VOD_GROUP: vod, f"{_VOD_GROUP}/metadata/table": _log_book()},
    )
    _store(site / "geodesy", "geodesy_store", {"canopy_01": _observations()})
    return root


def _items(root: Path) -> dict[str, pystac.Item]:
    """The items of the catalog at ``root``, by collection."""
    catalog = pystac.Catalog.from_file(root / "catalog.json")
    return {
        collection.id: next(collection.get_items())
        for collection in catalog.get_collections()
    }


class TestEveryProductAndDataset:
    def test_each_product_has_its_collection_and_the_catalog_is_valid(
        self, every_product
    ):
        _assert_valid(write_catalog(every_product))

        assert sorted(_items(every_product)) == [
            "gnss-geodesy",
            "gnss-observations",
            "vod",
        ]

    def test_gnss_assets_are_the_receivers_their_sbf_metadata_and_log_books(
        self, every_product
    ):
        write_catalog(every_product)

        assets = _items(every_product)["gnss-observations"].assets
        assert {key: asset.roles for key, asset in assets.items()} == {
            "canopy_01": ["data", "latest-version"],
            "canopy_01.sbf_obs": ["metadata", "latest-version"],
            "canopy_01.log_book": ["metadata", "latest-version"],
            "reference_01": ["data", "latest-version"],
            "reference_01.log_book": ["metadata", "latest-version"],
        }

    def test_vod_assets_are_the_analysis_and_its_log_book(self, every_product):
        write_catalog(every_product)

        assets = _items(every_product)["vod"].assets
        key = _VOD_GROUP.replace("/", ".")
        assert {k: a.roles for k, a in assets.items()} == {
            key: ["data", "latest-version"],
            f"{key}.log_book": ["metadata", "latest-version"],
        }
        ds = _open_asset(assets[key])
        assert ds.sizes == {"epoch": 12, "sid": 2}
        assert "VOD" in ds

    def test_no_key_holds_a_slash_and_the_reserved_group_is_no_asset(
        self, every_product
    ):
        write_catalog(every_product)

        keys = [k for item in _items(every_product).values() for k in item.assets]
        assert not [k for k in keys if "/" in k]
        assert not [k for k in keys if k.split(".")[0] == "canvod"]

    def test_the_log_book_and_sbf_assets_open_their_groups(self, every_product):
        write_catalog(every_product)

        assets = _items(every_product)["gnss-observations"].assets
        assert "pdop" in _open_asset(assets["canopy_01.sbf_obs"])
        assert "rinex_hash" in _open_asset(assets["canopy_01.log_book"])

    def test_a_sites_gnss_and_vod_items_are_related(self, every_product):
        write_catalog(every_product)

        items = _items(every_product)
        gnss, vod = items["gnss-observations"], items["vod"]

        def related(item: pystac.Item) -> set[str]:
            return {
                Path(link.get_absolute_href()).name
                for link in item.get_links("related")
            }

        assert f"{vod.id}.json" in related(gnss)
        assert f"{gnss.id}.json" in related(vod)

    def test_a_namesake_site_of_another_authority_is_not_related(self, tmp_path):
        root = tmp_path / "stores"
        _store(root / "a" / "gnss", "gnss_store", {"canopy_01": _observations()})
        _store(
            root / "b" / "vod",
            "vod_store",
            {_VOD_GROUP: _observations().rename({"SNR": "VOD"})},
            naming_authority="org.example.isengard",
        )

        write_catalog(root)

        assert not [
            link for item in _items(root).values() for link in item.get_links("related")
        ]

    def test_receivers_carry_their_header_position(self, every_product):
        write_catalog(every_product)

        item = _items(every_product)["gnss-observations"]
        expected = pytest.approx([testing.ECEF_X, testing.ECEF_Y, testing.ECEF_Z])
        assert item.assets["canopy_01"].extra_fields["canvod:position_ecef_m"] == (
            expected
        )
        receivers = item.properties["canvod:receivers"]
        assert receivers["canopy_01"]["position_ecef_m"] == expected
        assert receivers["canopy_01"]["type"] == "canopy"

    def test_datacube_fields_describe_dimensions_and_variables(self, every_product):
        write_catalog(every_product)

        assets = _items(every_product)["gnss-observations"].assets
        observations = assets["canopy_01"].extra_fields
        assert set(observations["cube:dimensions"]) == {"epoch", "sid"}
        assert observations["cube:dimensions"]["epoch"]["type"] == "temporal"
        assert observations["cube:variables"]["SNR"]["dimensions"] == ["epoch", "sid"]
        assert observations["cube:variables"]["SNR"]["type"] == "data"
        sbf = assets["canopy_01.sbf_obs"].extra_fields
        assert sbf["cube:variables"]["pdop"]["dimensions"] == ["epoch"]
        assert sbf["cube:variables"]["sv"] == {
            "dimensions": ["sid"],
            "type": "auxiliary",
        }
        assert "cube:dimensions" not in assets["canopy_01.log_book"].extra_fields


class TestCollections:
    def test_a_collection_extent_covers_all_its_items(self, tmp_path):
        root = tmp_path / "stores"
        _gnss_store(root / testing.SITE_KEY / "gnss")
        _gnss_store(
            root / "orthanc" / "gnss",
            site="orthanc",
            start="2025-03-01",
            longitude=testing.LONGITUDE + 1.0,
        )

        write_catalog(root)

        catalog = pystac.Catalog.from_file(root / "catalog.json")
        collection = catalog.get_child("gnss-observations")
        assert isinstance(collection, pystac.Collection)
        (interval,) = collection.extent.temporal.intervals
        starts, ends = zip(
            *(
                (item.common_metadata.start_datetime, item.common_metadata.end_datetime)
                for item in collection.get_items()
            ),
            strict=True,
        )
        assert interval == [min(starts), max(ends)]
        (bbox,) = collection.extent.spatial.bboxes
        half = len(bbox) // 2  # 2D or 3D: minima first, then maxima
        assert bbox[0] == pytest.approx(testing.LONGITUDE)
        assert bbox[half] == pytest.approx(testing.LONGITUDE + 1.0)

    def test_several_licenses_give_other_and_a_link_to_each(self, tmp_path):
        root = tmp_path / "stores"
        _gnss_store(root / testing.SITE_KEY / "gnss")  # CC-BY-4.0
        _gnss_store(
            root / "orthanc" / "gnss",
            site="orthanc",
            publisher=Publisher(
                license="other",
                license_uri="https://orthanc.example/license",
            ),
        )

        write_catalog(root)

        catalog = pystac.Catalog.from_file(root / "catalog.json")
        collection = catalog.get_child("gnss-observations")
        assert isinstance(collection, pystac.Collection)
        assert collection.license == "other"
        assert sorted(
            link.href for link in collection.get_links(pystac.RelType.LICENSE)
        ) == [
            "https://orthanc.example/license",
            "https://spdx.org/licenses/CC-BY-4.0.html",
        ]


def _catalog_files(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` outside the stores, by relative path."""
    stores = {path.parent for path in root.rglob("repo")}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not any(store in path.parents for store in stores)
    }


class TestEachWriteReplacesTheLatestCatalog:
    @pytest.fixture
    def two_sites(self, data_root: Path) -> Path:
        _gnss_store(data_root / "orthanc" / "gnss", site="orthanc")
        write_catalog(data_root)
        return data_root

    def test_a_removed_stores_item_is_gone(self, two_sites):
        removed = f"{testing.NAMING_AUTHORITY}.orthanc-gnss"
        item_folder = two_sites / "gnss-observations" / removed
        assert (item_folder / f"{removed}.json").is_file()

        shutil.rmtree(two_sites / "orthanc")
        write_catalog(two_sites)

        assert not item_folder.exists()
        catalog = pystac.Catalog.from_file(two_sites / "catalog.json")
        assert [item.id for item in catalog.get_items(recursive=True)] == [
            f"{testing.NAMING_AUTHORITY}.{testing.SITE_KEY}-gnss"
        ]

    def test_a_product_without_stores_loses_its_collection(self, two_sites):
        _store(
            two_sites / "orthanc" / "vod", "vod_store", {"canopy_01": _observations()}
        )
        write_catalog(two_sites)
        assert (two_sites / "vod" / "collection.json").is_file()

        shutil.rmtree(two_sites / "orthanc" / "vod")
        write_catalog(two_sites)

        assert not (two_sites / "vod").exists()
        catalog = pystac.Catalog.from_file(two_sites / "catalog.json")
        assert [child.id for child in catalog.get_children()] == ["gnss-observations"]

    def test_a_file_it_did_not_write_survives(self, two_sites):
        removed = f"{testing.NAMING_AUTHORITY}.orthanc-gnss"
        notes = two_sites / "gnss-observations" / "notes.txt"
        notes.write_text("Gandalf was here")
        kept = two_sites / "gnss-observations" / removed / "README.md"
        kept.write_text("Do not remove")

        shutil.rmtree(two_sites / "orthanc")
        write_catalog(two_sites)

        assert notes.read_text() == "Gandalf was here"
        assert kept.read_text() == "Do not remove"
        assert not (kept.parent / f"{removed}.json").exists()

    def test_releases_are_never_touched(self, two_sites):
        release = two_sites / "releases" / "v1"
        (release / "gnss-observations").mkdir(parents=True)
        (release / "catalog.json").write_text('{"id": "the-first-release"}')
        (release / "gnss-observations" / "collection.json").write_text("{}")
        before = _catalog_files(two_sites / "releases")

        shutil.rmtree(two_sites / "orthanc")
        write_catalog(two_sites)

        assert _catalog_files(two_sites / "releases") == before

    def test_writing_twice_without_a_change_gives_the_same_files(self, two_sites):
        before = _catalog_files(two_sites)

        write_catalog(two_sites)

        assert _catalog_files(two_sites) == before


# --- Releases (#247) -----------------------------------------------------------


def _tags(store: Path) -> dict[str, str]:
    """Each tag of a store with the snapshot it points at."""
    repo = open_repository(store)
    return {tag: repo.lookup_tag(tag) for tag in repo.list_tags()}


def _stores(root: Path) -> list[Path]:
    return sorted(path.parent for path in root.rglob("repo"))


def _release_items(root: Path, tag: str) -> list[pystac.Item]:
    catalog = pystac.Catalog.from_file(root / "releases" / tag / "catalog.json")
    return list(catalog.get_items(recursive=True))


def _open_release_asset(asset: pystac.Asset) -> xr.Dataset:
    """Open a release asset by its tag, as a data user would."""
    import icechunk

    storage = icechunk.local_filesystem_storage(asset.get_absolute_href())
    session = icechunk.Repository.open(storage).readonly_session(
        tag=asset.extra_fields["canvod:tag"]
    )
    return xr.open_dataset(session.store, **asset.extra_fields["xarray:open_kwargs"])


class TestReleases:
    @pytest.fixture
    def two_sites(self, data_root: Path) -> Path:
        _gnss_store(data_root / "orthanc" / "gnss", site="orthanc")
        return data_root

    def test_a_release_tags_every_store_and_writes_a_valid_catalog(self, every_product):
        catalog_path = create_release(every_product, "v1")

        assert catalog_path == every_product / "releases" / "v1" / "catalog.json"
        _assert_valid(catalog_path)
        stores = _stores(every_product)
        assert len(stores) == 3
        for store in stores:
            assert list(_tags(store)) == ["v1"]
        items = _release_items(every_product, "v1")
        assert len(items) == 3
        for item in items:
            for asset in item.assets.values():
                store = Path(asset.get_absolute_href())
                assert asset.extra_fields["canvod:tag"] == "v1"
                assert asset.extra_fields["canvod:snapshot_id"] == _tags(store)["v1"]
                assert "latest-version" not in asset.roles

    def test_a_release_asset_gives_the_released_data_after_new_commits(self, two_sites):
        create_release(two_sites, "v1")
        store = two_sites / testing.SITE_KEY / "gnss"
        session = open_repository(store).writable_session("main")
        _observations(n_epochs=24).to_zarr(
            session.store, group="canopy_01", mode="w", consolidated=False
        )
        commit_with_rebase(session, "more observations", store_path=store)

        item = next(
            item
            for item in _release_items(two_sites, "v1")
            if item.id.endswith(f"{testing.SITE_KEY}-gnss")
        )

        assert _open_release_asset(item.assets["canopy_01"]).sizes["epoch"] == 12
        assert _open_asset(item.assets["canopy_01"]).sizes["epoch"] == 12

    def test_a_tag_with_a_slash_is_refused_before_any_store_is_read(self, two_sites):
        broken = _gnss_store(two_sites / "isengard" / "gnss", site="isengard")
        (broken / "repo").write_bytes(b"not an icechunk repository")
        before = _files(two_sites)

        with pytest.raises(ValueError, match="'keep/v1'.*'/'") as caught:
            create_release(two_sites, "keep/v1")

        assert "isengard" not in str(caught.value)
        assert _files(two_sites) == before

    def test_a_tag_that_exists_in_one_store_is_refused_naming_it(self, two_sites):
        taken = two_sites / "orthanc" / "gnss"
        repo = open_repository(taken)
        repo.create_tag("v1", repo.lookup_branch("main"))

        with pytest.raises(ValueError, match="orthanc/gnss"):
            create_release(two_sites, "v1")

        assert _tags(two_sites / testing.SITE_KEY / "gnss") == {}
        assert not (two_sites / "releases").exists()

    def test_a_bad_store_stops_the_release_before_any_tag(self, two_sites):
        write_unchecked(
            _gnss_store(two_sites / "mordor" / "gnss", site="mordor"),
            {"publisher.license": "Apache 2"},
        )

        with pytest.raises(ValueError, match="mordor/gnss"):
            create_release(two_sites, "v1")

        assert all(_tags(store) == {} for store in _stores(two_sites))
        assert not (two_sites / "releases").exists()

    def test_a_rerun_after_tagging_writes_only_the_catalog(self, two_sites):
        for store in _stores(two_sites):
            repo = open_repository(store)
            repo.create_tag("v1", repo.lookup_branch("main"))
        tags = {store: _tags(store) for store in _stores(two_sites)}

        catalog_path = create_release(two_sites, "v1")

        _assert_valid(catalog_path)
        assert {store: _tags(store) for store in _stores(two_sites)} == tags
        assert len(_release_items(two_sites, "v1")) == 2

    def test_a_written_release_is_refused(self, two_sites):
        create_release(two_sites, "v1")
        before = _catalog_files(two_sites)

        with pytest.raises(ValueError, match="'v1' exists"):
            create_release(two_sites, "v1")

        assert _catalog_files(two_sites) == before

    def test_a_second_release_leaves_the_first_unchanged_and_openable(self, two_sites):
        create_release(two_sites, "v1")
        first = _catalog_files(two_sites / "releases" / "v1")
        _gnss_store(two_sites / "rohan" / "gnss", site="rohan")

        create_release(two_sites, "v2")
        write_catalog(two_sites)

        assert _catalog_files(two_sites / "releases" / "v1") == first
        assert len(_release_items(two_sites, "v1")) == 2
        assert len(_release_items(two_sites, "v2")) == 3
        for item in _release_items(two_sites, "v1"):
            for asset in item.assets.values():
                assert _open_release_asset(asset).sizes["epoch"] == 12

    def test_the_latest_catalog_keeps_its_latest_version_role(self, two_sites):
        create_release(two_sites, "v1")

        write_catalog(two_sites)

        for asset in _item(two_sites).assets.values():
            assert asset.roles == ["data", "latest-version"]
            assert "canvod:tag" not in asset.extra_fields
