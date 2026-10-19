"""A store's folder is named by its kind, with an optional suffix (#456)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from canvod.config.models.storage import StorageConfig
from canvod.config.store_names import (
    STORE_KINDS,
    StoreNameError,
    check_store_name,
    kind_of_store_name,
    store_folder_name,
    store_kind,
)


class TestCheckStoreName:
    @pytest.mark.parametrize("kind", STORE_KINDS)
    def test_the_kind_itself_is_valid(self, kind):
        assert check_store_name(kind, kind) == kind

    @pytest.mark.parametrize(
        "name", ["vod-recompute", "vod-2024", "vod-fangorn_v2", "vod-a-b"]
    )
    def test_the_kind_with_a_suffix_is_valid(self, name):
        assert check_store_name(name, "vod") == name

    @pytest.mark.parametrize(
        "name",
        [
            "store",
            "vod_2024",
            "vodka",
            "vod-",
            "vod--x",
            "vod-x_",
            "VOD",
            "vod-X",
            "gnss",
        ],
    )
    def test_other_names_are_refused_with_the_allowed_form(self, name):
        with pytest.raises(StoreNameError, match="'vod-recompute'"):
            check_store_name(name, "vod")

    @pytest.mark.parametrize("name", ["rinex", "RINEX", "rinex_v2", "rinex-old"])
    def test_the_old_gnss_name_names_the_migrate_command(self, name):
        with pytest.raises(StoreNameError, match="canvodpy store migrate SITE"):
            check_store_name(name, "gnss")

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="Unknown store kind"):
            check_store_name("statistics", "statistics")


class TestKinds:
    def test_store_types_map_to_their_kind(self):
        assert [
            store_kind(t) for t in ("gnss_store", "vod_store", "geodesy_store")
        ] == [
            "gnss",
            "vod",
            "geodesy",
        ]

    def test_an_unknown_store_type_is_refused(self):
        with pytest.raises(ValueError, match="Unknown store type"):
            store_kind("rinex_store")

    @pytest.mark.parametrize(
        ("name", "kind"),
        [
            ("gnss", "gnss"),
            ("vod-recompute", "vod"),
            ("geodesy-x", "geodesy"),
            ("rinex", None),
        ],
    )
    def test_the_kind_of_a_folder_name(self, name, kind):
        assert kind_of_store_name(name) == kind


class TestFolderName:
    @pytest.mark.parametrize(
        "path",
        [
            Path("/stores/fangorn/vod-recompute"),
            "/stores/fangorn/vod-recompute",
            "/stores/fangorn/vod-recompute/",
            "s3://bucket/prefix/fangorn/vod-recompute",
        ],
    )
    def test_the_last_part_of_a_path_or_url(self, path):
        assert store_folder_name(path) == "vod-recompute"


class TestSettings:
    def test_the_gnss_store_folder_defaults_to_gnss(self, tmp_path):
        storage = StorageConfig(stores_root_dir=tmp_path)
        assert storage.gnss_store_name == "gnss"
        assert storage.get_gnss_store_path("fangorn") == tmp_path / "fangorn" / "gnss"

    def test_a_suffixed_store_name_is_used_as_given(self, tmp_path):
        storage = StorageConfig(
            stores_root_dir=tmp_path, vod_store_name="vod-recompute"
        )
        assert (
            storage.get_vod_store_path("fangorn")
            == tmp_path / "fangorn" / "vod-recompute"
        )

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("gnss_store_name", "rinex", "canvodpy store migrate SITE"),
            ("gnss_store_name", "observations", "'gnss-recompute'"),
            ("vod_store_name", "vod_2024", "'vod-recompute'"),
            ("vod_store_name", "gnss", "'vod-recompute'"),
        ],
    )
    def test_a_name_breaking_the_rule_is_refused_when_the_settings_load(
        self, tmp_path, field, value, message
    ):
        with pytest.raises(ValidationError, match=message):
            StorageConfig(stores_root_dir=tmp_path, **{field: value})
