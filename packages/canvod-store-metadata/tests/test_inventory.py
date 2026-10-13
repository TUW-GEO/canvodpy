"""Test inventory/scan_stores on temp directories."""

import json

import icechunk
import pytest
import zarr

from canvod.store_metadata import inventory
from canvod.store_metadata.inventory import (
    scan_stores,
    scan_stores_as_stac,
    to_stac_collection,
    to_stac_collection_json,
    write_stac_catalog,
    write_stac_collection,
)
from canvod.store_metadata.io import read_metadata, write_metadata
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)

# The old STAC functions are deprecated (#243); the tests below still check
# what they return, TestOldStacFunctionsAreDeprecated checks the warnings.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*removed with the next major version:FutureWarning"
)


def _metadata(store_id: str) -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id=store_id,
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../gnss-observations/item/item.json",
            title=f"Store {store_id}",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(name="Test", email="t@e.com", institution="U"),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        ),
        spatial=SpatialExtent(site=SiteInfo(name="Test")),
    )


def _create_store_with_metadata(path, store_id="test/store"):
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")

    write_metadata(path, _metadata(store_id))
    return path


def _create_old_store(path, store_id="old/store", *, old_metadata=True):
    """A store written before stores kept repository metadata."""
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    root.require_group("canopy_01")
    if old_metadata:
        root.attrs["canvod_metadata"] = _metadata(store_id).model_dump(mode="json")
    session.commit("data before ADR 0014")
    return path


def _create_empty_store(path):
    icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))
    return path


class TestStoresNeedingMigration:
    def test_scan_marks_a_store_needing_migration(self, tmp_path):
        _create_store_with_metadata(tmp_path / "new", "fangorn/new")
        _create_old_store(tmp_path / "old", "fangorn/old")

        df = scan_stores(tmp_path).sort("path")

        assert df["id"].to_list() == ["fangorn/new", "fangorn/old"]
        assert df["needs_migration"].to_list() == [False, True]
        assert df["migrate_command"].to_list() == [
            None,
            "canvodpy store migrate-metadata Test --store gnss",
        ]

    def test_scan_marks_a_store_with_data_but_no_metadata(self, tmp_path):
        _create_old_store(tmp_path / "old", old_metadata=False)

        (row,) = scan_stores(tmp_path).to_dicts()

        assert row["needs_migration"] is True
        assert row["migrate_command"] == "canvodpy store migrate-metadata"
        assert row["path"] == str(tmp_path / "old")

    def test_an_empty_store_needs_no_migration(self, tmp_path):
        _create_empty_store(tmp_path / "empty")

        (row,) = scan_stores(tmp_path).to_dicts()

        assert row["needs_migration"] is False
        assert row["id"] is None

    @pytest.mark.parametrize("build", [scan_stores_as_stac, write_stac_catalog])
    def test_a_catalog_refuses_a_store_needing_migration(self, tmp_path, build):
        _create_store_with_metadata(tmp_path / "new", "fangorn/new")
        _create_old_store(tmp_path / "old", "fangorn/old")

        with pytest.raises(ValueError, match="canvodpy store migrate-metadata") as e:
            build(tmp_path)

        assert str(tmp_path / "old") in str(e.value)
        assert str(tmp_path / "new") not in str(e.value)
        assert not (tmp_path / "catalog.json").exists()

    @pytest.mark.parametrize("build", [scan_stores_as_stac, write_stac_catalog])
    def test_a_catalog_refuses_a_store_without_metadata(self, tmp_path, build):
        _create_store_with_metadata(tmp_path / "new", "fangorn/new")
        _create_empty_store(tmp_path / "empty")

        with pytest.raises(ValueError, match="no metadata") as e:
            build(tmp_path)

        assert str(tmp_path / "empty") in str(e.value)

    @pytest.mark.parametrize(
        "scan", [scan_stores, scan_stores_as_stac, write_stac_catalog]
    )
    def test_metadata_that_fails_to_read_is_an_error(self, tmp_path, monkeypatch, scan):
        _create_store_with_metadata(tmp_path / "new", "fangorn/new")

        def fail(*args, **kwargs):
            msg = "broken root copy"
            raise ValueError(msg)

        monkeypatch.setattr(inventory, "read_metadata", fail)

        with pytest.raises(ValueError, match="broken root copy"):
            scan(tmp_path)

    def test_write_stac_catalog_links_every_store(self, tmp_path):
        _create_store_with_metadata(tmp_path / "a", "fangorn/a")
        _create_store_with_metadata(tmp_path / "b", "fangorn/b")

        catalog = json.loads(write_stac_catalog(tmp_path).read_text())

        assert sorted(link["href"] for link in catalog["links"]) == [
            "a/collection.json",
            "b/collection.json",
        ]


class TestInventory:
    def test_scan_empty_dir(self, tmp_path):
        df = scan_stores(tmp_path)
        assert len(df) == 0
        assert "id" in df.columns

    def test_scan_finds_store(self, tmp_path):
        _create_store_with_metadata(tmp_path / "site1" / "rinex", "site1/rinex")
        df = scan_stores(tmp_path)
        assert len(df) == 1
        assert df["id"][0] == "site1/rinex"

    def test_scan_multiple_stores(self, tmp_path):
        _create_store_with_metadata(tmp_path / "s1" / "rinex", "s1/rinex")
        _create_store_with_metadata(tmp_path / "s2" / "rinex", "s2/rinex")
        df = scan_stores(tmp_path)
        assert len(df) == 2

    def test_scan_as_stac(self, tmp_path):
        _create_store_with_metadata(tmp_path / "site" / "store", "site/store")
        catalog = scan_stores_as_stac(tmp_path)
        assert catalog["type"] == "Catalog"
        assert len(catalog["collections"]) == 1
        assert catalog["collections"][0]["id"] == "site/store"

    def test_scan_nonexistent_dir(self, tmp_path):
        df = scan_stores(tmp_path / "nope")
        assert len(df) == 0


class TestStacCollection:
    """to_stac_collection() / to_stac_collection_json() -- in-memory STAC
    conversion, no file I/O (see also write_stac_collection() in
    test_io-adjacent coverage below for the file-writing counterpart)."""

    def test_to_stac_collection_shape(self, tmp_path):
        _create_store_with_metadata(tmp_path, "site/store")
        meta = read_metadata(tmp_path)

        collection = to_stac_collection(meta)

        assert collection["type"] == "Collection"
        assert collection["stac_version"] == "1.1.0"
        assert collection["id"] == "site/store"
        assert collection["title"] == meta.identity.title
        assert collection["license"] == "proprietary"  # no license set on fixture
        assert "extent" in collection
        assert "spatial" in collection["extent"]
        assert "temporal" in collection["extent"]
        assert collection["providers"][0]["name"] == meta.creator.institution

    def test_to_stac_collection_is_pure_no_file_io(self, tmp_path):
        """Calling to_stac_collection() must not write anything to disk."""
        _create_store_with_metadata(tmp_path, "site/store")
        meta = read_metadata(tmp_path)

        to_stac_collection(meta)

        assert not (tmp_path / "collection.json").exists()

    def test_to_stac_collection_json_roundtrips(self, tmp_path):
        _create_store_with_metadata(tmp_path, "site/store")
        meta = read_metadata(tmp_path)

        as_json = to_stac_collection_json(meta)
        parsed = json.loads(as_json)

        assert parsed == to_stac_collection(meta)

    def test_to_stac_collection_json_respects_indent(self, tmp_path):
        _create_store_with_metadata(tmp_path, "site/store")
        meta = read_metadata(tmp_path)

        compact = to_stac_collection_json(meta, indent=0)
        wide = to_stac_collection_json(meta, indent=4)

        assert len(wide) > len(compact)

    def test_write_stac_collection_matches_to_stac_collection(self, tmp_path):
        """Regression guard: write_stac_collection() delegates to
        to_stac_collection() internally -- the written file's content must
        be identical to the in-memory dict, not just structurally similar."""
        _create_store_with_metadata(tmp_path, "site/store")
        meta = read_metadata(tmp_path)

        output_path = write_stac_collection(tmp_path)

        assert output_path == tmp_path / "collection.json"
        written = json.loads(output_path.read_text())
        assert written == to_stac_collection(meta)


class TestOldStacFunctionsAreDeprecated:
    """Each old STAC function still works and names its replacement."""

    @pytest.fixture
    def store(self, tmp_path):
        path = tmp_path / "site" / "store"
        _create_store_with_metadata(path, "site/store")
        return path

    def test_scan_stores_as_stac(self, store):
        with pytest.warns(FutureWarning, match="build_catalog"):
            catalog = scan_stores_as_stac(store.parent.parent)

        assert catalog["collections"][0]["id"] == "site/store"

    def test_to_stac_collection(self, store):
        meta = read_metadata(store)

        with pytest.warns(FutureWarning, match="store_item"):
            collection = to_stac_collection(meta)

        assert collection["id"] == "site/store"

    def test_to_stac_collection_json(self, store):
        meta = read_metadata(store)

        with pytest.warns(FutureWarning, match="store_item"):
            as_json = to_stac_collection_json(meta)

        assert json.loads(as_json)["id"] == "site/store"

    def test_write_stac_collection(self, store):
        with pytest.warns(FutureWarning, match="write_catalog"):
            path = write_stac_collection(store)

        assert json.loads(path.read_text())["id"] == "site/store"

    def test_write_stac_catalog(self, store):
        with pytest.warns(FutureWarning, match="write_catalog"):
            path = write_stac_catalog(store.parent.parent)

        assert json.loads(path.read_text())["type"] == "Catalog"

    def test_each_old_function_warns_once(self, store):
        with pytest.warns(FutureWarning) as record:
            write_stac_catalog(store.parent.parent)

        assert len(record) == 1

    def test_scan_stores_is_not_deprecated(self, store, recwarn):
        scan_stores(store.parent.parent)

        assert not [w for w in recwarn if w.category is FutureWarning]
