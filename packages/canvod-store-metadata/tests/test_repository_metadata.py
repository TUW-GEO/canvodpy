"""A store's identity and its repository metadata (ADR 0014, ADR 0015)."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import icechunk
import pytest
import zarr
from canvod.utils import testing

from canvod.store_metadata import collect_metadata, metadata_exists, write_metadata
from canvod.store_metadata.schema import ConfigSnapshot


def _config(naming_authority: str | None = "at.ac.tuwien") -> MagicMock:
    meta_cfg = MagicMock(
        spec=[
            "author",
            "email",
            "institution",
            "orcid",
            "institution_ror",
            "department",
            "research_group",
            "website",
            "publisher",
            "publisher_url",
            "license",
            "naming_authority",
            "store_description",
        ]
    )
    meta_cfg.author = "Test"
    meta_cfg.email = "test@example.com"
    meta_cfg.institution = "TestU"
    for name in (
        "orcid",
        "institution_ror",
        "department",
        "research_group",
        "website",
        "publisher",
        "publisher_url",
        "license",
    ):
        setattr(meta_cfg, name, None)
    meta_cfg.naming_authority = naming_authority
    meta_cfg.store_description = testing.SITE_DESCRIPTION

    proc = MagicMock(spec=["metadata", "references"])
    proc.metadata = meta_cfg
    proc.references = None
    config = MagicMock(spec=["processing", "sids"])
    config.processing = proc
    config.sids = MagicMock(spec=[])
    return config


def _site_config() -> MagicMock:
    site_cfg = MagicMock(
        spec=[
            "latitude",
            "longitude",
            "altitude_m",
            "description",
            "country",
            "receivers",
            "vod_analyses",
        ]
    )
    analysis = MagicMock(spec=["canopy_receiver", "reference_receiver"])
    analysis.canopy_receiver = "canopy_01"
    analysis.reference_receiver = "reference_01"
    site_cfg.vod_analyses = {"canopy_01_vs_reference_01": analysis}
    site_cfg.latitude = 47.7
    site_cfg.longitude = 16.3
    site_cfg.altitude_m = 400.0
    site_cfg.description = None
    site_cfg.country = None
    from canvod.config.models import ReceiverConfig

    site_cfg.receivers = {
        "canopy_01": ReceiverConfig.model_validate(
            {
                "type": "canopy",
                "directory": "c",
                "receiver_hardware": {"manufacturer": "Septentrio", "model": "PolaRx5"},
                "antenna": {
                    "model": "SEPCHOKE_B3E6",
                    "radome": "NONE",
                    "height_m": 1.5,
                    "choke_ring": True,
                    "polarization": "RHCP",
                },
            }
        )
    }
    return site_cfg


def _collect(
    site_name: str = "Rosalia",
    store_type: str = "gnss_store",
    naming_authority: str | None = "at.ac.tuwien",
):
    with patch(
        "canvod.store_metadata.collectors.collect_config_snapshot",
        return_value=ConfigSnapshot(config_hash="abc123"),
    ):
        return collect_metadata(
            config=_config(naming_authority),
            site_name=site_name,
            site_config=_site_config(),
            store_type=store_type,
            source_format="rinex3",
            store_path=Path("/tmp/test"),
        )


def _empty_store(path: Path) -> Path:
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")
    return path


def _repository_metadata(path: Path) -> dict:
    storage = icechunk.local_filesystem_storage(str(path))
    return icechunk.Repository.open(storage=storage).get_metadata()


class TestIdentity:
    def test_gnss_store_id_is_the_lowercase_site_name_and_gnss(self):
        assert _collect("Rosalia").identity.id == "rosalia-gnss"

    def test_vod_store_id_ends_in_vod(self):
        assert _collect("Rosalia", store_type="vod_store").identity.id == "rosalia-vod"

    def test_underscores_and_digits_are_kept(self):
        assert _collect("rosalia_v3_04").identity.id == "rosalia_v3_04-gnss"

    def test_each_store_gets_its_own_uuid(self):
        first, second = _collect().identity.uuid, _collect().identity.uuid
        assert uuid.UUID(first).version == 4
        assert first != second

    def test_stac_link_points_to_the_item_in_the_catalog(self):
        assert _collect("Rosalia").identity.stac_link == (
            "../../gnss-observations/at.ac.tuwien.rosalia-gnss/"
            "at.ac.tuwien.rosalia-gnss.json"
        )
        assert _collect("Rosalia", store_type="vod_store").identity.stac_link == (
            "../../vod/at.ac.tuwien.rosalia-vod/at.ac.tuwien.rosalia-vod.json"
        )

    def test_a_geodesy_store_has_its_own_id_and_collection(self):
        from canvod.store_metadata.identity import stac_link, store_id

        assert store_id(testing.CANOPY_SITE, "geodesy_store") == "fangorn-geodesy"
        assert stac_link(
            testing.NAMING_AUTHORITY, "fangorn-geodesy", "geodesy_store"
        ) == (
            "../../gnss-geodesy/org.middle-earth.fangorn-geodesy/"
            "org.middle-earth.fangorn-geodesy.json"
        )

    @pytest.mark.parametrize("site_name", ["Rosalia Forest", "", "Ros/alia", "site.a"])
    def test_a_site_name_that_gives_no_valid_id_is_refused(self, site_name):
        with pytest.raises(ValueError, match="site name") as excinfo:
            _collect(site_name)
        assert repr(site_name) in str(excinfo.value)

    def test_a_store_type_without_a_product_is_refused(self):
        with pytest.raises(ValueError, match="statistics_store"):
            _collect(store_type="statistics_store")

    def test_a_store_without_a_naming_authority_is_refused(self):
        with pytest.raises(ValueError, match=r"processing\.metadata\.naming_authority"):
            _collect(naming_authority=None)

    @pytest.mark.parametrize("authority", ["tuwien", "https://tuwien.ac.at", "AT.ac"])
    def test_a_naming_authority_that_is_not_reverse_dns_is_refused(self, authority):
        with pytest.raises(ValueError, match="reverse DNS"):
            _collect(naming_authority=authority)

    def test_a_vod_store_lists_the_vod_analyses_of_the_settings(self):
        meta = _collect("Rosalia", store_type="vod_store")
        analysis = meta.vod_analyses["canopy_01_vs_reference_01"]
        assert analysis.canopy_receiver == "canopy_01"
        assert analysis.reference_receiver == "reference_01"

    def test_a_gnss_store_lists_no_vod_analyses(self):
        assert _collect("Rosalia").vod_analyses == {}


class TestReceiverSpecs:
    def test_a_gnss_store_copies_the_receiver_and_antenna_details(self):
        receiver = _collect().instruments.receivers["canopy_01"]

        assert receiver.receiver_hardware.model == "PolaRx5"
        assert receiver.antenna.model == "SEPCHOKE_B3E6"
        assert receiver.antenna.height_m == 1.5
        assert receiver.antenna.choke_ring is True
        assert receiver.antenna.polarization == "RHCP"

    def test_the_details_reach_the_repository_metadata(self, tmp_path):
        store_path = _empty_store(tmp_path / "store")
        write_metadata(store_path, _collect())

        receiver = _repository_metadata(store_path)["instruments"]["receivers"][
            "canopy_01"
        ]
        assert receiver["receiver_hardware"]["manufacturer"] == "Septentrio"
        assert receiver["antenna"]["radome"] == "NONE"

    def test_a_vod_store_does_not_copy_them(self):
        receiver = _collect(store_type="vod_store").instruments.receivers["canopy_01"]

        assert receiver.receiver_hardware is None
        assert receiver.antenna is None


class TestRepositoryMetadata:
    def test_write_metadata_writes_the_repository_metadata(self, tmp_path):
        store_path = _empty_store(tmp_path / "store")
        meta = _collect()

        write_metadata(store_path, meta)

        stored = _repository_metadata(store_path)
        assert stored["identity"]["id"] == "rosalia-gnss"
        assert stored["identity"]["uuid"] == meta.identity.uuid
        assert stored["identity"]["naming_authority"] == "at.ac.tuwien"
        assert stored["identity"]["stac_link"] == meta.identity.stac_link
        assert stored["temporal"]["created"] == meta.temporal.created

    def test_repository_metadata_holds_no_per_write_fields(self, tmp_path):
        store_path = _empty_store(tmp_path / "store")
        write_metadata(store_path, _collect())

        stored = _repository_metadata(store_path)
        for per_write in ("processing", "environment", "config", "summaries"):
            assert per_write not in stored
        assert "updated" not in stored["temporal"]

    def test_metadata_exists_once_the_repository_metadata_is_written(self, tmp_path):
        store_path = _empty_store(tmp_path / "store")
        assert not metadata_exists(store_path)
        write_metadata(store_path, _collect())
        assert metadata_exists(store_path)

    def test_a_second_write_is_refused(self, tmp_path):
        store_path = _empty_store(tmp_path / "store")
        first = _collect()
        write_metadata(store_path, first)

        with pytest.raises(ValueError, match="already has repository metadata"):
            write_metadata(store_path, _collect())
        assert (
            _repository_metadata(store_path)["identity"]["uuid"] == first.identity.uuid
        )
