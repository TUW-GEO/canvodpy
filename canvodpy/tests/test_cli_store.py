"""Tests for canvodpy's store CLI — list/info/log against a real synthetic store."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
import xarray as xr
import yaml
from canvodpy.cli.app import main_app
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils import testing

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """load_config() is lru_cache'd on (config_dir, config_file) args only —
    it doesn't know CANVOD_CONFIG_DIR changed between tests that all call it
    with no args. Clear the cache so each test resolves its own config."""
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


_SIDS = ["G01|L1|C", "G02|L1|C"]
_N_SIDS = len(_SIDS)


def _make_dataset(slot: int, n_epochs: int = 20) -> xr.Dataset:
    """Small synthetic (epoch, sid) dataset, one 15-minute slot per commit."""
    rng = np.random.default_rng(slot)
    base = np.datetime64("2025-01-01T00:00:00") + np.timedelta64(slot * 15, "m")
    epochs = base + np.arange(n_epochs) * np.timedelta64(5, "s")
    s1c = rng.uniform(30.0, 55.0, (n_epochs, _N_SIDS)).astype(np.float32)
    file_hash = hashlib.sha256(f"slot={slot}".encode()).hexdigest()[:16]

    return xr.Dataset(
        {"S1C": (("epoch", "sid"), s1c)},
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": _SIDS},
        attrs={"File Hash": file_hash, "station": "TST", "receiver": "canopy_01"},
    )


def _write_synthetic_store(store_path, n_slots: int = 2) -> None:
    from canvod.store import MyIcechunkStore
    from canvod.store_metadata.testing import give_test_metadata

    icestore = MyIcechunkStore(give_test_metadata(store_path), store_type="gnss_store")
    for slot in range(n_slots):
        icestore.write_or_append_group(
            _make_dataset(slot),
            "canopy_01",
            commit_message=f"slot {slot}",
        )
    # MyIcechunkStore.__init__ calls load_config() (outside any CliRunner env
    # patch) to read IcechunkConfig defaults. If the real local
    # config/canvod-settings.yaml happens to be valid, that call succeeds and
    # lru_cache caches it under the no-arg key — masking the test's own
    # CANVOD_CONFIG_DIR override in the runner.invoke() call that follows.
    # Clear it so that invoke() always resolves fresh, under its own env.
    loader_module.load_config.cache_clear()


def _write_config(
    config_dir, stores_root, naming_authority=None, initials=testing.PERSON_INITIALS
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "author": testing.PERSON_NAME,
        "email": testing.PERSON_EMAIL,
        "institution": "B",
    }
    if naming_authority is not None:
        metadata["naming_authority"] = naming_authority
    if initials is not None:
        metadata["initials"] = initials
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": metadata,
                    "storage": {"stores_root_dir": str(stores_root)},
                },
                "sites": {
                    "TestSite": {
                        "gnss_site_data_root": str(stores_root / "raw"),
                        "receivers": {
                            "canopy_01": {"type": "canopy", "directory": "02_canopy"},
                        },
                    }
                },
            }
        )
    )


def _env(config_dir):
    return {"CANVOD_CONFIG_DIR": str(config_dir)}


class TestStoreList:
    def test_lists_configured_sites_with_store_status(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex")

        result = runner.invoke(main_app, ["store", "list"], env=_env(config_dir))

        assert result.exit_code == 0, result.output
        assert "TestSite" in result.output
        assert "gnss" in result.output
        assert "vod" in result.output
        assert "not yet created" in result.output


class TestStoreInfo:
    def test_shows_tree_and_stats_for_existing_store(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex")

        result = runner.invoke(
            main_app, ["store", "info", "TestSite"], env=_env(config_dir)
        )

        assert result.exit_code == 0, result.output
        assert "gnss store" in result.output
        assert "Groups:      1" in result.output
        assert "canopy_01" in result.output
        assert "Failed to get stats" not in result.output

    def test_group_drilldown_shows_dataset_content(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex")

        result = runner.invoke(
            main_app,
            ["store", "info", "TestSite", "--group", "canopy_01"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "Dataset" in result.output
        assert "S1C" in result.output

    def test_unknown_site_exits_cleanly(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)

        result = runner.invoke(
            main_app, ["store", "info", "NoSuchSite"], env=_env(config_dir)
        )

        assert result.exit_code == 1
        assert "Unknown site" in result.output
        assert "Traceback" not in result.output

    def test_store_not_yet_created_exits_cleanly(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)

        result = runner.invoke(
            main_app, ["store", "info", "TestSite"], env=_env(config_dir)
        )

        assert result.exit_code == 1
        assert "No gnss store yet" in result.output

    def test_invalid_store_kind_rejected(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)

        result = runner.invoke(
            main_app,
            ["store", "info", "TestSite", "--store", "bogus"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "--store must be one of" in result.output


class TestStoreLog:
    def test_shows_commit_graph_by_default(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex", n_slots=2)

        result = runner.invoke(
            main_app, ["store", "log", "TestSite"], env=_env(config_dir)
        )

        assert result.exit_code == 0, result.output
        assert "slot 0" in result.output
        assert "slot 1" in result.output

    def test_shows_ops_log_with_flag(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex", n_slots=2)

        result = runner.invoke(
            main_app, ["store", "log", "TestSite", "--ops"], env=_env(config_dir)
        )

        assert result.exit_code == 0, result.output
        assert "NewCommit" in result.output


class TestStoreMaintain:
    """dev/perf_degradation_findings_2026_07_15.md, Problem B: maintain
    defaults to a dry run that deletes nothing; --execute requires
    interactive confirmation before touching anything."""

    def test_default_is_dry_run_and_deletes_nothing(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex", n_slots=2)

        result = runner.invoke(
            main_app, ["store", "maintain", "TestSite"], env=_env(config_dir)
        )

        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert "Would garbage-collect" in result.output
        assert "Nothing was deleted or expired" in result.output

        # commits from _write_synthetic_store must all still be present
        from canvod.store import MyIcechunkStore

        icestore = MyIcechunkStore(
            stores_root / "TestSite" / "rinex", store_type="gnss_store"
        )
        history = icestore.get_history()
        assert len(history) >= 2

    def test_execute_without_confirmation_aborts(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex", n_slots=2)

        result = runner.invoke(
            main_app,
            ["store", "maintain", "TestSite", "--execute"],
            input="n\n",
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "Aborted" in result.output
        assert "Maintenance complete" not in result.output

    def test_execute_with_confirmation_runs_maintenance(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "rinex", n_slots=2)

        result = runner.invoke(
            main_app,
            ["store", "maintain", "TestSite", "--execute"],
            input="y\n",
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "Maintenance complete" in result.output
        # 90-day default cutoff means nothing this fresh actually expires
        assert "Expired snapshots: 0" in result.output


class TestStoreMaintainDue:
    """Cron-safe counterpart to `maintain` -- never prompts, off by
    default (dev/todo_later.md icechunk-maintenance-scheduling gap,
    2026-07-21)."""

    def test_disabled_by_default_is_a_noop(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)  # no maintenance: block -> enabled=False
        _write_synthetic_store(stores_root / "TestSite" / "rinex")

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "TestSite"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "nothing to do" in result.output
        assert "Traceback" not in result.output

    def test_requires_exactly_one_of_site_or_all_sites(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)

        result = runner.invoke(
            main_app, ["store", "maintain-due"], env=_env(config_dir)
        )
        assert result.exit_code == 1
        assert "exactly one of" in result.output

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "TestSite", "--all-sites"],
            env=_env(config_dir),
        )
        assert result.exit_code == 1
        assert "exactly one of" in result.output

    def test_invalid_store_kind_rejected(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "TestSite", "--store", "bogus"],
            env=_env(config_dir),
        )
        assert result.exit_code == 1
        assert "must be one of" in result.output

    def test_unknown_site_exits_nonzero(self, tmp_path):
        """Regression lock: an unrecognized site must not exit 0 -- a cron
        job silently exiting clean on a real misconfiguration would never
        alert anyone."""
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "canvod-settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "processing": {
                        "metadata": {
                            "author": "A",
                            "email": "a@example.com",
                            "institution": "B",
                        },
                        "storage": {
                            "stores_root_dir": str(stores_root),
                            "maintenance": {"enabled": True},
                        },
                    },
                    "sites": {},
                }
            )
        )

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "NoSuchSite"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "Unknown site" in result.output

    def test_manifests_enabled_works_independently_of_enabled(self, tmp_path):
        """Regression lock: manifest compaction must be reachable with
        maintenance.enabled=False and maintenance.manifests_enabled=True
        -- the config's own docstring promises these are independent
        gates, and a top-level `if not mcfg.enabled: return` would
        silently defeat that (found and fixed 2026-07-21)."""
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "canvod-settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "processing": {
                        "metadata": {
                            "author": "A",
                            "email": "a@example.com",
                            "institution": "B",
                        },
                        "storage": {
                            "stores_root_dir": str(stores_root),
                            "maintenance": {
                                "enabled": False,
                                "manifests_enabled": True,
                                "manifest_count_threshold": 1,
                            },
                        },
                    },
                    "sites": {
                        "TestSite": {
                            "gnss_site_data_root": str(stores_root / "raw"),
                            "receivers": {
                                "canopy_01": {
                                    "type": "canopy",
                                    "directory": "02_canopy",
                                },
                            },
                        }
                    },
                }
            )
        )
        _write_synthetic_store(stores_root / "TestSite" / "rinex")

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "TestSite"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "nothing to do" not in result.output
        assert "Would compact manifests" in result.output
        # enabled=False must suppress expire/GC even though the manifest
        # threshold made this store "due" overall.
        assert "Would garbage-collect" not in result.output
        assert "Would expire" not in result.output


def _write_old_form_store(
    store_path,
    naming_authority="org.middle-earth",
    *,
    complete=True,
    store_type="gnss_store",
) -> None:
    """A store as canVODpy wrote it before ADR 0014: one canvod_metadata attr.

    ``complete=False`` leaves out what older stores lack: description,
    publisher, license and site position. A VOD store holds a VOD array
    with the attributes older versions wrote.
    """
    import icechunk
    import zarr

    from canvod.store_metadata.schema import (
        Creator,
        Publisher,
        SiteInfo,
        SpatialExtent,
        StoreIdentity,
        StoreMetadata,
        TemporalExtent,
    )

    kind = store_type.removesuffix("_store")
    old = StoreMetadata(
        identity=StoreIdentity(
            id=f"TestSite/{store_type}",
            title=f"TestSite {kind.title()} Store",
            description="Test site observations." if complete else None,
            keywords=["GNSS"],
            store_type=store_type,
            source_format="rinex3",
            naming_authority=naming_authority,
        ),
        creator=Creator(name="A", email="a@example.com", institution="B"),
        publisher=Publisher(name="B", license="CC-BY-4.0") if complete else Publisher(),
        temporal=TemporalExtent(created="2025-01-01T00:00:00Z", updated="x"),
        spatial=SpatialExtent(
            site=SiteInfo(name="TestSite"),
            geospatial_lat=testing.LATITUDE if complete else None,
            geospatial_lon=testing.LONGITUDE if complete else None,
        ),
    )
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(store_path))
    )
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="w")
    root.attrs.update(old.to_root_attrs())
    variable = "VOD" if store_type == "vod_store" else "SNR"
    group = (
        "tau_omega/canopy_01_vs_reference_01"
        if store_type == "vod_store"
        else "canopy_01"
    )
    xr.Dataset(
        {
            variable: (
                ("epoch", "sid"),
                np.array([[0.4, -0.1], [0.5, 1.9]]),
                # As older versions wrote VOD: SNR's and theta's attributes.
                {
                    "standard_name": "carrier_to_noise_density_ratio",
                    "valid_min": 0,
                    "valid_range": [0.0, 1.5707963267948966],
                },
            )
        },
        coords={
            "epoch": np.array(
                ["2025-01-01T00:00:00", "2025-01-01T00:00:30"], dtype="datetime64[ns]"
            ),
            "sid": ["G01|L1|C", "G02|L1|C"],
            "system": ("sid", ["G", "G"]),
        },
    ).to_zarr(session.store, group=group, consolidated=False)
    session.commit("old form")


class TestStoreMigrateMetadata:
    def _setup(self, tmp_path, naming_authority="org.middle-earth"):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, naming_authority)
        return config_dir, store_path

    def test_migrates_a_store_after_confirmation(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "testsite-gnss" in result.output
        assert "TestSite/gnss_store" in result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).identity.id == "testsite-gnss"

    def test_the_migration_records_the_initials_of_the_settings(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).migration.who == testing.PERSON_INITIALS

    def test_missing_initials_refuse_the_migration(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)
        _write_config(config_dir, tmp_path / "stores", initials=None)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1, result.output
        assert "processing.metadata.initials" in result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)

    def test_nothing_changes_without_confirmation(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss"],
            env=_env(config_dir),
            input="n\n",
        )

        assert result.exit_code == 1, result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)

    def test_a_missing_naming_authority_names_the_option(self, tmp_path):
        config_dir, _ = self._setup(tmp_path, naming_authority=None)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "--naming-authority" in result.output

    def test_the_naming_authority_can_be_given(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path, naming_authority=None)

        result = runner.invoke(
            main_app,
            [
                "store",
                "migrate-metadata",
                "TestSite",
                "--store",
                "gnss",
                "--naming-authority",
                "com.example",
                "--yes",
            ],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).identity.naming_authority == "com.example"

    def test_the_naming_authority_comes_from_the_settings(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root, naming_authority="org.example")
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, naming_authority=None)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).identity.naming_authority == "org.example"

    def test_an_invalid_naming_authority_is_replaced_by_the_settings(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root, naming_authority="org.example")
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, naming_authority="https://www.example.org")

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "org.example (from the settings" in result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).identity.naming_authority == "org.example"

    def test_an_invalid_naming_authority_without_settings_is_refused(self, tmp_path):
        config_dir, store_path = self._setup(
            tmp_path, naming_authority="https://www.example.org"
        )

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "--naming-authority" in result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).written_before_migration

    def test_the_store_keeps_its_own_naming_authority(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root, naming_authority="org.example")
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, naming_authority="org.middle-earth")

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(store_path).identity.naming_authority == "org.middle-earth"

    def test_missing_fields_refuse_the_migration_and_are_listed(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, complete=False)

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "summary" in result.output
        assert "publisher.name" in result.output
        assert "--set" in result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)

    def test_missing_fields_are_given_with_set(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "rinex"
        _write_old_form_store(store_path, complete=False)

        result = runner.invoke(
            main_app,
            [
                "store",
                "migrate-metadata",
                "TestSite",
                "--store",
                "gnss",
                "--set",
                "identity.description=Test site observations.",
                "--set",
                "publisher.name=B",
                "--set",
                "publisher.license=CC-BY-4.0",
                "--set",
                f"spatial.geospatial_lat={testing.LATITUDE}",
                "--set",
                f"spatial.geospatial_lon={testing.LONGITUDE}",
                "--yes",
            ],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata, validate_all

        meta = read_metadata(store_path)
        assert meta.identity.description == "Test site observations."
        assert not any(validate_all(meta, recommended=False).values())
        assert meta.migration.fields_given == [
            "identity.description",
            "publisher.license",
            "publisher.name",
            "spatial.geospatial_lat",
            "spatial.geospatial_lon",
        ]

    def test_vod_attributes_are_replaced(self, tmp_path):
        import icechunk
        import zarr

        from canvod.vod.calculator import VOD_ATTRS

        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "vod"
        _write_old_form_store(store_path, store_type="vod_store")

        result = runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", "vod", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(store_path))
        )
        root = zarr.open_group(repo.readonly_session(branch="main").store, mode="r")
        attrs = dict(root["tau_omega/canopy_01_vs_reference_01/VOD"].attrs)
        assert {k: attrs[k] for k in VOD_ATTRS} == VOD_ATTRS
        assert set(attrs) - set(VOD_ATTRS) <= {"_FillValue", "coordinates"}
        assert repo.get_metadata()["migration"]["variables_replaced"] == [
            "tau_omega/canopy_01_vs_reference_01/VOD"
        ]


def _write_current_store(stores_root, site="TestSite") -> None:
    """A GNSS store with repository metadata, as a run creates it."""
    import icechunk

    from canvod.store_metadata import write_metadata
    from canvod.store_metadata.schema import (
        Creator,
        Instruments,
        ReceiverInfo,
        SiteInfo,
        SpatialExtent,
        StoreIdentity,
        StoreMetadata,
        TemporalExtent,
    )

    path = stores_root / site / "rinex"
    icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))
    write_metadata(
        path,
        StoreMetadata(
            identity=StoreIdentity(
                id="testsite-gnss",
                uuid="00000000-0000-4000-8000-000000000001",
                naming_authority="com.example",
                stac_link="../../x/x/x.json",
                title="TestSite GNSS Store",
                store_type="gnss_store",
                source_format="rinex3",
            ),
            creator=Creator(name="A", email="a@example.com", institution="B"),
            temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
            spatial=SpatialExtent(site=SiteInfo(name=site)),
            instruments=Instruments(
                receivers={"canopy_01": ReceiverInfo(type="canopy", directory="c")}
            ),
        ),
    )


class TestStoreAmend:
    def _setup(self, tmp_path, receivers=None):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        if receivers:
            settings = yaml.safe_load((config_dir / "canvod-settings.yaml").read_text())
            settings["sites"]["TestSite"]["receivers"].update(receivers)
            (config_dir / "canvod-settings.yaml").write_text(yaml.safe_dump(settings))
        _write_current_store(stores_root)
        return config_dir, stores_root / "TestSite" / "rinex"

    def _amend(self, config_dir, *args, input=None):
        return runner.invoke(
            main_app,
            ["store", "amend", "TestSite", "--store", "gnss", *args],
            env=_env(config_dir),
            input=input,
        )

    def test_sets_a_field_after_showing_old_and_new(self, tmp_path):
        config_dir, path = self._setup(tmp_path)

        result = self._amend(
            config_dir,
            "--set",
            "identity.title=TestSite GNSS",
            "--reason",
            "shorter title",
            "--yes",
        )

        assert result.exit_code == 0, result.output
        assert "TestSite GNSS Store" in result.output
        from canvod.store_metadata import read_metadata

        meta = read_metadata(path)
        assert meta.identity.title == "TestSite GNSS"
        assert meta.amendments[0].reason == "shorter title"
        assert meta.amendments[0].who == testing.PERSON_INITIALS

    def test_missing_initials_refuse_the_amendment(self, tmp_path):
        config_dir, path = self._setup(tmp_path)
        _write_config(config_dir, tmp_path / "stores", initials=None)

        result = self._amend(
            config_dir,
            "--set",
            "identity.title=TestSite GNSS",
            "--reason",
            "shorter title",
            "--yes",
        )

        assert result.exit_code == 1, result.output
        assert "processing.metadata.initials" in result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(path).identity.title == "TestSite GNSS Store"

    def test_values_are_read_as_yaml(self, tmp_path):
        config_dir, path = self._setup(tmp_path)

        result = self._amend(
            config_dir,
            "--set",
            f"spatial.geospatial_lat={testing.LATITUDE + 0.01}",
            "--reason",
            "surveyed",
            "--yes",
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(path).spatial.geospatial_lat == testing.LATITUDE + 0.01

    def test_nothing_changes_without_confirmation(self, tmp_path):
        config_dir, path = self._setup(tmp_path)

        result = self._amend(
            config_dir, "--set", "identity.title=x", "--reason", "r", input="n\n"
        )

        assert result.exit_code == 1
        from canvod.store_metadata import read_metadata

        assert read_metadata(path).identity.title == "TestSite GNSS Store"

    def test_a_fixed_field_is_refused(self, tmp_path):
        config_dir, _ = self._setup(tmp_path)

        result = self._amend(
            config_dir, "--set", "identity.id=x-gnss", "--reason", "r", "--yes"
        )

        assert result.exit_code == 1
        assert "create a new one" in result.output

    def test_a_field_under_an_unset_block_is_set(self, tmp_path):
        config_dir, path = self._setup(tmp_path)

        result = self._amend(
            config_dir,
            "--set",
            "instruments.receivers.canopy_01.antenna.height_m=1.5",
            "--reason",
            "antenna height measured",
            "--yes",
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        antenna = read_metadata(path).instruments.receivers["canopy_01"].antenna
        assert antenna.height_m == 1.5

    def test_an_invalid_value_under_an_unset_block_is_refused(self, tmp_path):
        config_dir, path = self._setup(tmp_path)

        result = self._amend(
            config_dir,
            "--set",
            "instruments.receivers.canopy_01.antenna.height_m=tall",
            "--reason",
            "antenna height measured",
            "--yes",
        )

        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "height_m" in result.output
        from canvod.store_metadata import read_metadata

        assert read_metadata(path).instruments.receivers["canopy_01"].antenna is None

    def test_a_reason_is_required(self, tmp_path):
        config_dir, _ = self._setup(tmp_path)

        result = self._amend(config_dir, "--set", "identity.title=x", "--yes")

        assert result.exit_code != 0
        assert "--reason" in result.output

    def test_adds_a_receiver_from_the_settings(self, tmp_path):
        config_dir, path = self._setup(
            tmp_path,
            receivers={
                "canopy_02": {
                    "type": "canopy",
                    "directory": "03_canopy",
                    "antenna": {"model": "SEPCHOKE_B3E6"},
                }
            },
        )

        result = self._amend(
            config_dir,
            "--add-receiver",
            "canopy_02",
            "--reason",
            "second canopy receiver installed",
            "--yes",
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        receiver = read_metadata(path).instruments.receivers["canopy_02"]
        assert receiver.directory == "03_canopy"
        assert receiver.antenna.model == "SEPCHOKE_B3E6"

    def test_an_unknown_receiver_is_refused(self, tmp_path):
        config_dir, _ = self._setup(tmp_path)

        result = self._amend(
            config_dir, "--add-receiver", "canopy_09", "--reason", "r", "--yes"
        )

        assert result.exit_code == 1
        assert "canopy_09" in result.output

    def test_changes_from_a_file(self, tmp_path):
        config_dir, path = self._setup(
            tmp_path,
            receivers={"canopy_02": {"type": "canopy", "directory": "03_canopy"}},
        )
        changes = tmp_path / "amend.yaml"
        changes.write_text(
            yaml.safe_dump(
                {
                    "reason": "DOI assigned, second receiver",
                    "set": {"identity.persistent_identifier": "10.1234/abc"},
                    "add_receivers": ["canopy_02"],
                }
            )
        )

        result = self._amend(config_dir, "--from", str(changes), "--yes")

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        meta = read_metadata(path)
        assert meta.identity.persistent_identifier == "10.1234/abc"
        assert "canopy_02" in meta.instruments.receivers
        assert {a.reason for a in meta.amendments} == {"DOI assigned, second receiver"}
