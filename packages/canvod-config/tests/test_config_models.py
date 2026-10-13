"""Unit tests for canvod.config.models Pydantic validators.

Tests the validation logic, cross-field constraints, and helper methods
on the configuration models. No YAML files or filesystem config required.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from canvod.config.models import (
    AuxDataConfig,
    CanvodConfig,
    ChunkStrategies,
    ChunkStrategy,
    CompressionConfig,
    CredentialsConfig,
    FundingRef,
    IcechunkConfig,
    MetadataConfig,
    ProcessingConfig,
    ProcessingParams,
    ReceiverConfig,
    ReferencesConfig,
    SidsConfig,
    SiteConfig,
    SitesConfig,
    StorageConfig,
    VodAnalysisConfig,
    reference_store_group,
)
from canvod.utils import testing

# ===================================================================
# MetadataConfig
# ===================================================================


class TestMetadataConfig:
    def test_valid_metadata(self):
        m = MetadataConfig(
            author="Test User",
            email="test@example.com",
            institution="Test Uni",
        )
        assert m.author == "Test User"

    def test_store_description_defaults_to_none(self):
        m = MetadataConfig(
            author="Test User",
            email="test@example.com",
            institution="Test Uni",
        )
        assert m.store_description is None

    def test_store_description_is_deprecated_but_still_read(self):
        with pytest.warns(FutureWarning, match=r"sites\.<name>\.store_description"):
            m = MetadataConfig(
                author="Test User",
                email="test@example.com",
                institution="Test Uni",
                store_description="A reference store for TestSite.",
            )
        assert m.store_description == "A reference store for TestSite."

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError, match="email"):
            MetadataConfig(
                author="Test",
                email="not-an-email",
                institution="Uni",
            )

    def test_to_attrs_dict_required_fields(self):
        m = MetadataConfig(
            author="Alice",
            email="alice@uni.edu",
            institution="Uni",
        )
        d = m.to_attrs_dict()
        assert d["author"] == "Alice"
        assert d["email"] == "alice@uni.edu"
        assert d["institution"] == "Uni"

    def test_to_attrs_dict_optional_fields_excluded_when_none(self):
        m = MetadataConfig(
            author="A",
            email="a@b.com",
            institution="U",
        )
        d = m.to_attrs_dict()
        assert "department" not in d
        assert "research_group" not in d
        assert "website" not in d

    def test_to_attrs_dict_optional_fields_included_when_set(self):
        m = MetadataConfig(
            author="A",
            email="a@b.com",
            institution="U",
            department="Dept",
            research_group="Group",
            website="https://example.com",
        )
        d = m.to_attrs_dict()
        assert d["department"] == "Dept"
        assert d["research_group"] == "Group"
        assert d["website"] == "https://example.com"


# ===================================================================
# ReferencesConfig
# ===================================================================


class TestReferencesConfig:
    def test_defaults_empty(self):
        r = ReferencesConfig()
        assert r.software_repository is None
        assert r.documentation is None
        assert r.access_url is None
        assert r.related_stores == []
        assert r.publications == []
        assert r.funding == []

    def test_accepts_software_repository_and_documentation(self):
        r = ReferencesConfig(
            software_repository=testing.REPOSITORY,
            documentation=testing.DOCUMENTATION,
            access_url="https://example.org/store",
            related_stores=["fangorn/vod_store"],
        )
        assert r.software_repository == testing.REPOSITORY
        assert r.documentation == testing.DOCUMENTATION
        assert r.access_url == "https://example.org/store"
        assert r.related_stores == ["fangorn/vod_store"]

    def test_accepts_funding(self):
        r = ReferencesConfig(
            funding=[
                FundingRef(
                    funder="Austrian Science Fund (FWF)",
                    funder_ror="https://ror.org/013tf3c58",
                    grant_number="I 4489-N",
                    award_title="CONSOLIDATION",
                )
            ]
        )
        assert r.funding[0].funder == "Austrian Science Fund (FWF)"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            ReferencesConfig(not_a_real_field="x")


# ===================================================================
# ProcessingParams — resource_mode validator
# ===================================================================


class TestProcessingParams:
    def test_auto_mode_defaults(self):
        p = ProcessingParams()
        assert p.resource_mode == "auto"
        assert p.n_max_threads is None

    def test_manual_mode_requires_n_max_threads(self):
        with pytest.raises(ValidationError, match="n_max_threads is required"):
            ProcessingParams(resource_mode="manual")

    def test_manual_mode_with_threads(self):
        p = ProcessingParams(resource_mode="manual", n_max_threads=4)
        assert p.n_max_threads == 4

    def test_auto_mode_with_threads_warns(self):
        with pytest.warns(UserWarning, match="ignores n_max_threads"):
            ProcessingParams(resource_mode="auto", n_max_threads=4)

    def test_n_max_threads_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(resource_mode="manual", n_max_threads=0)  # ge=1
        with pytest.raises(ValidationError):
            ProcessingParams(resource_mode="manual", n_max_threads=101)  # le=100

    def test_days_per_batch_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(days_per_batch=0)  # ge=1
        with pytest.raises(ValidationError):
            ProcessingParams(days_per_batch=31)  # le=30

    def test_nice_priority_bounds(self):
        with pytest.raises(ValidationError):
            ProcessingParams(nice_priority=-21)  # ge=-20
        with pytest.raises(ValidationError):
            ProcessingParams(nice_priority=20)  # le=19

    def test_resolve_resources_auto(self):
        import os

        p = ProcessingParams(resource_mode="auto")
        r = p.resolve_resources()
        assert r["n_workers"] == max(1, (os.cpu_count() or 2) - 2)
        assert r["max_memory_gb"] is None
        assert r["nice_priority"] == -5

    def test_resolve_resources_auto_uncapped(self):
        p = ProcessingParams(resource_mode="auto", auto_uncapped=True)
        r = p.resolve_resources()
        assert r["n_workers"] is None

    def test_resolve_resources_manual(self):
        p = ProcessingParams(
            resource_mode="manual",
            n_max_threads=8,
            nice_priority=10,
        )
        r = p.resolve_resources()
        assert r["n_workers"] == 8
        assert r["nice_priority"] == 10

    def test_max_memory_gb_deprecated(self):
        with pytest.warns(FutureWarning, match="'max_memory_gb' is left over"):
            ProcessingParams(max_memory_gb=32.0)

    def test_max_memory_gb_unset_no_warning(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            ProcessingParams()

    def test_default_keep_gnss_observables(self):
        p = ProcessingParams()
        assert p.keep_gnss_observables == ["SNR"]


# ===================================================================
# AuxDataConfig
# ===================================================================


class TestAuxDataConfig:
    def test_defaults(self):
        a = AuxDataConfig()
        assert a.agency == "COD"
        assert a.product_type == "final"
        assert a.fetch_clock is True

    def test_fetch_clock_can_be_disabled(self):
        a = AuxDataConfig(fetch_clock=False)
        assert a.fetch_clock is False

    def test_invalid_product_type(self):
        with pytest.raises(ValidationError, match="product_type"):
            AuxDataConfig(product_type="invalid")

    def test_ftp_servers_with_cddis(self):
        a = AuxDataConfig()
        servers = a.get_ftp_servers("user@nasa.gov")
        assert len(servers) == 2
        assert "nasa" in servers[0][0]
        assert servers[0][1] == "user@nasa.gov"
        assert "esa" in servers[1][0]
        assert servers[1][1] is None

    def test_ftp_servers_without_cddis(self):
        a = AuxDataConfig()
        servers = a.get_ftp_servers(None)
        assert len(servers) == 1
        assert "esa" in servers[0][0]


# ===================================================================
# ReceiverConfig — paired_canopies validation
# ===================================================================


class TestReceiverConfig:
    def test_canopy_without_paired_canopies(self):
        rc = ReceiverConfig(type="canopy", directory="can/raw")
        assert rc.paired_canopies is None

    def test_reader_format_accepts_every_reader(self):
        for fmt in ("auto", "rinex3", "rinex3_stripped", "rinex2", "sbf", "nmea"):
            rc = ReceiverConfig(type="canopy", directory="can/raw", reader_format=fmt)
            assert rc.reader_format == fmt

    def test_unknown_reader_format_raises(self):
        """A typo fails when the settings load, not later in a run."""
        with pytest.raises(ValidationError, match="reader_format"):
            ReceiverConfig(type="canopy", directory="can/raw", reader_format="rinex")

    def test_canopy_with_paired_canopies_raises(self):
        with pytest.raises(ValidationError, match="must not be set for canopy"):
            ReceiverConfig(type="canopy", directory="can/raw", paired_canopies="all")

    def test_reference_requires_paired_canopies(self):
        with pytest.raises(ValidationError, match="required for reference"):
            ReceiverConfig(type="reference", directory="ref/raw")

    def test_reference_with_paired_canopies_all(self):
        rc = ReceiverConfig(
            type="reference", directory="ref/raw", paired_canopies="all"
        )
        assert rc.paired_canopies == "all"

    def test_reference_with_paired_canopies_list(self):
        rc = ReceiverConfig(
            type="reference",
            directory="ref/raw",
            paired_canopies=["canopy_01", "canopy_02"],
        )
        assert rc.paired_canopies == ["canopy_01", "canopy_02"]

    def test_scs_from_deprecated_migrates(self):
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rc = ReceiverConfig(type="reference", directory="ref/raw", scs_from="all")
        assert any(issubclass(x.category, FutureWarning) for x in w)
        assert rc.paired_canopies == "all"

    def test_recipe_only_is_valid(self):
        rc = ReceiverConfig(type="canopy", directory="can/raw", recipe="fangorn_canopy")
        assert rc.recipe == "fangorn_canopy"
        assert rc.naming is None

    def test_naming_is_deprecated(self):
        with pytest.warns(FutureWarning, match="receiver setting 'naming'.*recipe"):
            rc = ReceiverConfig(
                type="canopy", directory="can/raw", naming={"source_pattern": "auto"}
            )
        assert rc.naming == {"source_pattern": "auto"}
        assert rc.recipe is None

    def test_site_naming_is_deprecated(self):
        with pytest.warns(FutureWarning, match="site setting 'naming'.*recipe"):
            SiteConfig(
                gnss_site_data_root="/data",
                receivers={"canopy_01": {"type": "canopy", "directory": "c"}},
                naming={"site_id": testing.SITE_ID, "agency": testing.AGENCY},
            )


# ===================================================================
# SiteConfig — cross-receiver validation
# ===================================================================


class TestSiteConfig:
    def test_store_description_per_site(self):
        site = self._make_site(store_description=testing.SITE_DESCRIPTION)
        assert site.store_description == testing.SITE_DESCRIPTION

    def _make_site(self, **overrides):
        defaults = {
            "gnss_site_data_root": "/data/site",
            "receivers": {
                "canopy_01": ReceiverConfig(type="canopy", directory="can/raw"),
                "reference_01": ReceiverConfig(
                    type="reference", directory="ref/raw", paired_canopies="all"
                ),
            },
        }
        defaults.update(overrides)
        return SiteConfig(**defaults)

    def test_valid_site(self):
        site = self._make_site()
        assert site.get_base_path() == Path("/data/site")

    def test_get_canopy_receiver_names(self):
        site = self._make_site()
        assert site.get_canopy_receiver_names() == ["canopy_01"]

    def test_resolve_paired_canopies_all(self):
        site = self._make_site()
        result = site.resolve_paired_canopies("reference_01")
        assert result == ["canopy_01"]

    def test_resolve_paired_canopies_specific_list(self):
        site = SiteConfig(
            gnss_site_data_root="/data",
            receivers={
                "c1": ReceiverConfig(type="canopy", directory="c1"),
                "c2": ReceiverConfig(type="canopy", directory="c2"),
                "r1": ReceiverConfig(
                    type="reference", directory="r1", paired_canopies=["c1"]
                ),
            },
        )
        assert site.resolve_paired_canopies("r1") == ["c1"]

    def test_resolve_paired_canopies_on_canopy_raises(self):
        site = self._make_site()
        with pytest.raises(ValueError, match="only applies to reference"):
            site.resolve_paired_canopies("canopy_01")

    def test_resolve_scs_from_deprecated(self):
        import warnings

        site = self._make_site()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = site.resolve_scs_from("reference_01")
        assert any(issubclass(x.category, FutureWarning) for x in w)
        assert result == ["canopy_01"]

    def test_paired_canopies_references_nonexistent_canopy_raises(self):
        with pytest.raises(ValidationError, match="not a canopy receiver"):
            SiteConfig(
                gnss_site_data_root="/data",
                receivers={
                    "c1": ReceiverConfig(type="canopy", directory="c1"),
                    "r1": ReceiverConfig(
                        type="reference",
                        directory="r1",
                        paired_canopies=["nonexistent"],
                    ),
                },
            )

    def test_get_reference_canopy_pairs(self):
        site = SiteConfig(
            gnss_site_data_root="/data",
            receivers={
                "c1": ReceiverConfig(type="canopy", directory="c1"),
                "c2": ReceiverConfig(type="canopy", directory="c2"),
                "r1": ReceiverConfig(
                    type="reference", directory="r1", paired_canopies="all"
                ),
            },
        )
        pairs = site.get_reference_canopy_pairs()
        assert ("r1", "c1") in pairs
        assert ("r1", "c2") in pairs

    def test_auto_derive_vod_analyses_uses_bare_reference_name(self):
        """See GH #66: reference_receiver must stay the bare receiver name
        (matches a 'receivers' key, used for directory lookups) -- never
        the paired store group name.
        """
        site = self._make_site()
        assert site.vod_analyses is not None
        cfg = site.vod_analyses["canopy_01_vs_reference_01"]
        assert cfg.reference_receiver == "reference_01"
        assert cfg.canopy_receiver == "canopy_01"

    def test_explicit_vod_analyses_not_overridden(self):
        site = self._make_site(
            vod_analyses={
                "custom": VodAnalysisConfig(
                    canopy_receiver="canopy_01", reference_receiver="reference_01"
                )
            }
        )
        assert list(site.vod_analyses) == ["custom"]

    @pytest.mark.parametrize(
        ("canopy", "reference"),
        [("sbf", "sbf"), ("rinex3", "rinex3_stripped"), ("auto", "sbf")],
    )
    def test_same_file_format_accepted(self, canopy, reference):
        """rinex3_stripped reads RINEX 3; auto is checked once detected."""
        self._make_site(
            receivers={
                "canopy_01": ReceiverConfig(
                    type="canopy", directory="c", reader_format=canopy
                ),
                "reference_01": ReceiverConfig(
                    type="reference",
                    directory="r",
                    paired_canopies="all",
                    reader_format=reference,
                ),
            }
        )

    def test_mixed_file_formats_raise(self):
        with pytest.raises(ValidationError, match="same file format"):
            self._make_site(
                receivers={
                    "canopy_01": ReceiverConfig(
                        type="canopy", directory="c", reader_format="sbf"
                    ),
                    "reference_01": ReceiverConfig(
                        type="reference",
                        directory="r",
                        paired_canopies="all",
                        reader_format="rinex3",
                    ),
                }
            )


# ===================================================================
# VodAnalysisConfig.reference_store_group
# ===================================================================


class TestReferenceStoreGroup:
    def test_function_formats_paired_name(self):
        assert reference_store_group("reference_01", "canopy_01") == (
            "reference_01_canopy_01"
        )

    def test_vod_analysis_config_property_matches_function(self):
        cfg = VodAnalysisConfig(
            canopy_receiver="canopy_01", reference_receiver="reference_01"
        )
        assert cfg.reference_store_group == "reference_01_canopy_01"
        assert cfg.reference_store_group == reference_store_group(
            cfg.reference_receiver, cfg.canopy_receiver
        )

    def test_property_stays_distinct_from_bare_receiver(self):
        cfg = VodAnalysisConfig(
            canopy_receiver="canopy_01", reference_receiver="reference_01"
        )
        assert cfg.reference_store_group != cfg.reference_receiver


# ===================================================================
# SidsConfig — mode validation
# ===================================================================


class TestSidsConfig:
    def test_mode_all_returns_none(self):
        s = SidsConfig(mode="all")
        assert s.get_sids() is None

    def test_mode_custom_returns_list(self):
        s = SidsConfig(mode="custom", custom_sids=["G01|L1|C", "E01|E1|C"])
        assert s.get_sids() == ["G01|L1|C", "E01|E1|C"]

    def test_mode_preset_explicit_none_raises(self):
        """Explicitly passing preset=None with mode='preset' triggers validator."""
        with pytest.raises(ValidationError, match="preset must be specified"):
            SidsConfig(mode="preset", preset=None)

    def test_mode_preset_without_name_raises(self):
        """mode='preset' with no preset name raises ValueError on get_sids()."""
        s = SidsConfig(mode="preset")
        assert s.preset is None
        with pytest.raises(ValueError, match="preset must be set"):
            s.get_sids()

    def test_mode_preset_with_name(self):
        s = SidsConfig(mode="preset", preset="gps_l1_only")
        assert s.preset == "gps_l1_only"


# ===================================================================
# StorageConfig
# ===================================================================


class TestStorageConfig:
    def test_store_paths(self, tmp_path):
        sc = StorageConfig(stores_root_dir=tmp_path)
        gnss = sc.get_gnss_store_path("fangorn")
        vod = sc.get_vod_store_path("fangorn")
        rollup = sc.get_rollup_store_path("fangorn")
        assert gnss == tmp_path / "fangorn" / "rinex"
        assert vod == tmp_path / "fangorn" / "vod"
        assert rollup == tmp_path / "fangorn" / "rollup"

    def test_deprecated_get_rinex_store_path(self, tmp_path):
        import warnings

        sc = StorageConfig(stores_root_dir=tmp_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = sc.get_rinex_store_path("fangorn")
        assert any(issubclass(x.category, FutureWarning) for x in w)
        assert result == tmp_path / "fangorn" / "rinex"

    def test_vod_store_strategy_deprecated(self, tmp_path):
        with pytest.warns(FutureWarning, match="'vod_store_strategy' is left over"):
            StorageConfig(stores_root_dir=tmp_path, vod_store_strategy="overwrite")

    def test_vod_store_strategy_unset_no_warning(self, tmp_path):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            sc = StorageConfig(stores_root_dir=tmp_path)
        assert sc.vod_store_strategy is None

    @pytest.mark.parametrize(
        "url", ["s3://fangorn/stores", "S3://fangorn/stores", "gs://fangorn/stores"]
    )
    def test_a_url_as_stores_root_dir_is_refused(self, url):
        """Processing writes stores to local directories only (#240)."""
        with pytest.raises(ValueError, match="local directory") as error:
            StorageConfig(stores_root_dir=url)
        assert url in str(error.value)
        assert "S3" in str(error.value)

    def test_a_string_path_is_expanded(self):
        sc = StorageConfig(stores_root_dir="~/fangorn")
        assert sc.stores_root_dir == Path.home() / "fangorn"

    def test_the_placeholder_is_refused(self):
        with pytest.raises(ValueError, match="placeholder"):
            StorageConfig(stores_root_dir="/path/to/stores")

    def test_placeholder_path_not_validated(self):
        """Placeholder paths starting with /path/ skip existence check."""
        sc = StorageConfig(stores_root_dir=Path("/path/to/stores"))
        assert sc.stores_root_dir == Path("/path/to/stores")

    def test_aux_data_dir_default_tempdir(self, tmp_path):
        sc = StorageConfig(stores_root_dir=tmp_path, aux_data_dir=None)
        aux = sc.get_aux_data_dir()
        assert aux.exists()

    def test_aux_data_dir_explicit(self, tmp_path):
        aux_dir = tmp_path / "aux"
        sc = StorageConfig(stores_root_dir=tmp_path, aux_data_dir=aux_dir)
        result = sc.get_aux_data_dir()
        assert result == aux_dir
        assert result.exists()  # should have been created


# ===================================================================
# IcechunkConfig
# ===================================================================


class TestIcechunkConfig:
    def test_defaults(self):
        ic = IcechunkConfig()
        assert ic.compression_level == 3
        assert ic.compression_algorithm == "zstd"
        assert ic.inline_chunk_threshold_bytes == 512
        assert ic.get_partial_values_concurrency == 1
        assert ic.manifest_splitting_enabled is True
        assert ic.manifest_preload_max_refs == 10_000
        assert ic.manifest_preload_max_arrays_to_scan == 500

    def test_compression_level_bounds(self):
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_level=-1)  # ge=0
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_level=23)  # le=22

    def test_invalid_algorithm(self):
        with pytest.raises(ValidationError):
            IcechunkConfig(compression_algorithm="snappy")

    def test_manifest_preload_defaults(self):
        ic = IcechunkConfig()
        assert ic.manifest_preload_enabled is False
        assert ic.manifest_preload_max_refs == 10_000
        assert ic.manifest_preload_max_arrays_to_scan == 500
        assert ic.manifest_preload_pattern == r"^(epoch|sid)$"
        assert ic.manifest_splitting_enabled is True

    def test_repo_info_rewrite_defaults_are_unset(self):
        ic = IcechunkConfig()
        assert ic.num_updates_per_repo_info_file is None
        assert ic.repo_update_max_tries is None
        assert ic.repo_update_initial_backoff_ms is None
        assert ic.repo_update_max_backoff_ms is None

    def test_num_updates_per_repo_info_file_bounds(self):
        IcechunkConfig(num_updates_per_repo_info_file=1)
        IcechunkConfig(num_updates_per_repo_info_file=65535)
        with pytest.raises(ValidationError):
            IcechunkConfig(num_updates_per_repo_info_file=0)  # ge=1
        with pytest.raises(ValidationError):
            IcechunkConfig(num_updates_per_repo_info_file=65536)  # le=65535 (u16)

    def test_repo_update_retry_bounds(self):
        with pytest.raises(ValidationError):
            IcechunkConfig(repo_update_max_tries=0)  # ge=1
        with pytest.raises(ValidationError):
            IcechunkConfig(repo_update_initial_backoff_ms=-1)  # ge=0
        with pytest.raises(ValidationError):
            IcechunkConfig(repo_update_max_backoff_ms=-1)  # ge=0

    def test_repo_update_retry_settings_roundtrip(self):
        ic = IcechunkConfig(
            repo_update_max_tries=5,
            repo_update_initial_backoff_ms=100,
            repo_update_max_backoff_ms=5_000,
        )
        assert ic.repo_update_max_tries == 5
        assert ic.repo_update_initial_backoff_ms == 100
        assert ic.repo_update_max_backoff_ms == 5_000


# ===================================================================
# CompressionConfig / ChunkStrategy
# ===================================================================


class TestCompressionConfig:
    def test_defaults(self):
        c = CompressionConfig()
        assert c.zlib is True
        assert c.complevel == 5

    def test_complevel_bounds(self):
        with pytest.raises(ValidationError):
            CompressionConfig(complevel=-1)
        with pytest.raises(ValidationError):
            CompressionConfig(complevel=10)


class TestAuxDataProductType:
    @pytest.mark.parametrize("value", ["ultra-rapid", "ultrarapid"])
    def test_ultra_rapid_refused_with_reason(self, value):
        with pytest.raises(ValidationError, match="Ultra-rapid products are not"):
            AuxDataConfig(product_type=value)

    def test_rapid_accepted(self):
        assert AuxDataConfig(product_type="rapid").product_type == "rapid"


class TestChunkStrategies:
    def test_defaults_for_both_stores(self):
        ic = IcechunkConfig()
        assert ic.chunk_strategies.gnss_store == ChunkStrategy(epoch=180, sid=-1)
        assert ic.chunk_strategies.vod_store == ChunkStrategy(epoch=17280, sid=-1)

    def test_one_store_set_keeps_the_other_default(self):
        ic = IcechunkConfig(chunk_strategies={"gnss_store": {"epoch": 720}})
        assert ic.chunk_strategies.gnss_store.epoch == 720
        assert ic.chunk_strategies.vod_store.epoch == 17280

    def test_shipped_defaults_match_the_model(self):
        import yaml

        import canvod.config

        defaults_yaml = (
            Path(canvod.config.__file__).parent / "defaults" / "processing.yaml"
        )
        shipped = yaml.safe_load(defaults_yaml.read_text())["icechunk"]
        assert (
            ChunkStrategies(**shipped["chunk_strategies"])
            == IcechunkConfig().chunk_strategies
        )

    def test_misspelled_store_rejected_with_suggestion(self):
        with pytest.raises(ValidationError) as exc:
            IcechunkConfig(chunk_strategies={"vod_stores": {"epoch": 720}})
        msg = str(exc.value)
        assert "chunk_strategies.vod_stores" in msg
        assert "Did you mean 'vod_store'?" in msg
        assert "Allowed keys: gnss_store, vod_store" in msg


class TestUnknownKeySuggestion:
    """Every settings model names the closest allowed key for a typo."""

    def test_nested_typo_names_location_and_match(self):
        with pytest.raises(ValidationError) as exc:
            IcechunkConfig(chunk_strategies={"gnss_store": {"epok": 720}})
        missing, err = exc.value.errors()
        assert missing["loc"] == ("chunk_strategies", "gnss_store", "epoch")
        assert missing["type"] == "missing"
        assert err["loc"] == ("chunk_strategies", "gnss_store", "epok")
        assert err["type"] == "extra_forbidden"
        assert "Did you mean 'epoch'?" in err["msg"]

    def test_no_close_match_lists_allowed_keys_only(self):
        with pytest.raises(ValidationError) as exc:
            ChunkStrategy(epoch=180, xyz=1)
        msg = exc.value.errors()[0]["msg"]
        assert "Did you mean" not in msg
        assert "Allowed keys: epoch, sid" in msg

    def test_other_errors_reported_alongside(self):
        with pytest.raises(ValidationError) as exc:
            IcechunkConfig(compression_level=99, compresion_level=3)
        types = {e["type"] for e in exc.value.errors()}
        assert types == {"less_than_equal", "extra_forbidden"}

    def test_typo_not_corrected(self):
        with pytest.raises(ValidationError):
            ChunkStrategy(epochs=720)


class TestChunkStrategy:
    def test_epoch_required_sid_defaults_to_unchunked(self):
        with pytest.raises(ValidationError):
            ChunkStrategy()
        assert ChunkStrategy(epoch=180).sid == -1

    def test_epoch_must_be_positive(self):
        with pytest.raises(ValidationError):
            ChunkStrategy(epoch=0)


# ===================================================================
# SitesConfig
# ===================================================================


class TestSitesConfig:
    def test_empty_sites_does_not_warn(self):
        # Config loading is a foundation-layer concern used by every
        # canvod-* package; most never touch sites at all, so an empty
        # sites dict must not warn (see GnssResearchSite.__init__ for the
        # actual actionable error, raised when a site is looked up by name).
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            SitesConfig(sites={})

    def test_valid_site(self):
        sites = SitesConfig(
            sites={
                "fangorn": SiteConfig(
                    gnss_site_data_root="/data/fangorn",
                    receivers={
                        "c1": ReceiverConfig(type="canopy", directory="c1"),
                        "r1": ReceiverConfig(
                            type="reference", directory="r1", paired_canopies="all"
                        ),
                    },
                )
            }
        )
        assert "fangorn" in sites.sites


# ===================================================================
# CanvodConfig — top-level
# ===================================================================


class TestCanvodConfig:
    def test_extra_keys_forbidden(self):
        """CanvodConfig has extra='forbid' to catch typos."""
        with pytest.raises(ValidationError, match="extra"):
            CanvodConfig(
                processing=ProcessingConfig(
                    metadata=MetadataConfig(
                        author="A", email="a@b.com", institution="U"
                    ),
                    storage=StorageConfig(stores_root_dir=Path("/path/to/stores")),
                ),
                sites=SitesConfig(
                    sites={
                        "s": SiteConfig(
                            gnss_site_data_root="/data",
                            receivers={
                                "c": ReceiverConfig(type="canopy", directory="c"),
                                "r": ReceiverConfig(
                                    type="reference",
                                    directory="r",
                                    paired_canopies="all",
                                ),
                            },
                        )
                    }
                ),
                sids=SidsConfig(),
                typo_key="oops",  # <-- extra key
            )

    def test_nasa_earthdata_accessor(self):
        cfg = CanvodConfig(
            processing=ProcessingConfig(
                metadata=MetadataConfig(author="A", email="a@b.com", institution="U"),
                credentials=CredentialsConfig(nasa_earthdata_acc_mail="user@nasa.gov"),
                storage=StorageConfig(stores_root_dir=Path("/path/to/stores")),
            ),
            sites=SitesConfig(
                sites={
                    "s": SiteConfig(
                        gnss_site_data_root="/data",
                        receivers={
                            "c": ReceiverConfig(type="canopy", directory="c"),
                            "r": ReceiverConfig(
                                type="reference", directory="r", paired_canopies="all"
                            ),
                        },
                    )
                }
            ),
            sids=SidsConfig(),
        )
        assert cfg.nasa_earthdata_acc_mail == "user@nasa.gov"
