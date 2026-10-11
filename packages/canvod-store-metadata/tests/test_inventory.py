"""Test inventory/scan_stores on temp directories."""

import json

import icechunk
import zarr

from canvod.store_metadata.inventory import (
    scan_stores,
    scan_stores_as_stac,
    to_stac_collection,
    to_stac_collection_json,
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


def _create_store_with_metadata(path, store_id="test/store"):
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")

    meta = StoreMetadata(
        identity=StoreIdentity(
            id=store_id,
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="at.ac.tuwien",
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
    write_metadata(path, meta)
    return path


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
