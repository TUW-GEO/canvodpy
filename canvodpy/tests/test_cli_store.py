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
        _write_synthetic_store(stores_root / "TestSite" / "gnss")

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss")

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss")

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

        result = runner.invoke(
            main_app, ["store", "log", "TestSite", "--ops"], env=_env(config_dir)
        )

        assert result.exit_code == 0, result.output
        assert "NewCommit" in result.output

    def test_opens_a_store_by_path_without_settings(self, tmp_path):
        store_path = tmp_path / "copy" / "gnss"
        _write_synthetic_store(store_path, n_slots=2)

        result = runner.invoke(
            main_app,
            ["store", "log", "--path", str(store_path)],
            env=_env(tmp_path / "no-settings"),
        )

        assert result.exit_code == 0, result.output
        assert "slot 0" in result.output
        assert "slot 1" in result.output

    def test_a_missing_path_is_refused_by_name(self, tmp_path):
        missing = tmp_path / "nowhere"

        result = runner.invoke(
            main_app,
            ["store", "log", "--path", str(missing)],
            env=_env(tmp_path / "no-settings"),
        )

        assert result.exit_code == 1
        assert "No store at" in result.output
        assert "nowhere" in result.output
        assert "Traceback" not in result.output

    def test_a_folder_without_a_store_is_refused_by_name(self, tmp_path):
        folder = tmp_path / "just-files"
        folder.mkdir()
        (folder / "notes.txt").write_text("not a store")

        result = runner.invoke(
            main_app,
            ["store", "log", "--path", str(folder)],
            env=_env(tmp_path / "no-settings"),
        )

        assert result.exit_code == 1
        assert "No store at" in result.output
        assert "just-files" in result.output

    @pytest.mark.parametrize("site_and_path", [True, False])
    def test_exactly_one_of_site_or_path(self, tmp_path, site_and_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "gnss"
        _write_synthetic_store(store_path)
        args = ["TestSite", "--path", str(store_path)] if site_and_path else []

        result = runner.invoke(main_app, ["store", "log", *args], env=_env(config_dir))

        assert result.exit_code == 1
        assert "a site or --path" in result.output

    def test_writes_the_graph_as_svg(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)
        svg = tmp_path / "graph.svg"

        result = runner.invoke(
            main_app,
            ["store", "log", "TestSite", "--branch", "main", "--svg", str(svg)],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        text = svg.read_text()
        assert text.lstrip().startswith("<svg")
        assert "slot 1" in text
        assert "graph.svg" in result.output

    def test_svg_does_not_go_with_ops(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "gnss")
        svg = tmp_path / "graph.svg"

        result = runner.invoke(
            main_app,
            ["store", "log", "TestSite", "--ops", "--svg", str(svg)],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "--ops" in result.output
        assert not svg.exists()

    def test_plain_prints_without_colors(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

        result = runner.invoke(
            main_app,
            ["store", "log", "TestSite", "--branch", "main", "--plain"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "slot 1" in result.output
        assert "\x1b[" not in result.output


class TestStoreMaintain:
    """dev/perf_degradation_findings_2026_07_15.md, Problem B: maintain
    defaults to a dry run that deletes nothing; --execute requires
    interactive confirmation before touching anything."""

    def test_default_is_dry_run_and_deletes_nothing(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

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
            stores_root / "TestSite" / "gnss", store_type="gnss_store"
        )
        history = icestore.get_history()
        assert len(history) >= 2

    def test_execute_without_confirmation_aborts(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss")

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

    def test_skips_while_a_run_is_active(self, tmp_path):
        """Maintenance never runs next to a live `canvodpy run` (#401)."""
        from canvodpy.orchestrator.resources import PipelineRunLock

        config_dir = tmp_path / "config"
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
                            "stores_root_dir": str(tmp_path / "stores"),
                            "maintenance": {"enabled": True},
                        },
                    },
                    "sites": {},
                }
            )
        )

        with PipelineRunLock():
            result = runner.invoke(
                main_app,
                ["store", "maintain-due", "--all-sites"],
                env=_env(config_dir),
            )

        assert result.exit_code == 0, result.output
        assert "A canvodpy run is active" in result.output

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
        _write_synthetic_store(stores_root / "TestSite" / "gnss")

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

    def test_dry_run_until_confirmed_false_runs_maintenance(self, tmp_path):
        """On a local store, ``dry_run_until_confirmed: false`` still runs
        the due maintenance instead of reporting it (#357)."""
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
                                "enabled": True,
                                "dry_run_until_confirmed": False,
                                "expire_interval_days": 1,
                                "gc_delay_days": 20,
                                "retention_days": 90,
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
        _write_synthetic_store(stores_root / "TestSite" / "gnss", n_slots=2)

        result = runner.invoke(
            main_app,
            ["store", "maintain-due", "TestSite"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "Expired:" in result.output
        assert "Would expire" not in result.output


def _write_old_form_store(
    store_path,
    naming_authority="org.middle-earth",
    *,
    complete=True,
    store_type="gnss_store",
    source="rinex3",
) -> None:
    """A store as canVODpy wrote it before ADR 0014: one canvod_metadata attr.

    ``complete=False`` leaves out what older stores lack: description,
    publisher, license and site position. A VOD store holds a VOD array
    with the attributes older versions wrote. As in canVODpy 0.x, the
    epochs record no time scale, and a group read from RINEX files records
    the RINEX version (``source="sbf"`` writes a group read from SBF).
    """
    import icechunk
    import zarr

    from canvod.config import load_config
    from canvod.store_metadata import collect_config_snapshot
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
    # Older versions recorded the settings of the run in the attribute too;
    # the tests keep their settings next to the stores (tmp_path/config).
    settings = collect_config_snapshot(
        load_config(config_dir=store_path.parents[2] / "config")
    )
    loader_module.load_config.cache_clear()  # a test may change them after
    old = StoreMetadata(
        config=settings,
        identity=StoreIdentity(
            id=f"TestSite/{store_type}",
            title=f"TestSite {kind.title()} Store",
            description="Test site observations." if complete else None,
            keywords=["GNSS"],
            store_type=store_type,
            source_format=source,
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
        attrs=(
            {"RINEX Version": 3.04}
            if store_type == "gnss_store" and source.startswith("rinex")
            else {}
        ),
    ).to_zarr(session.store, group=group, consolidated=False)
    session.commit("old form")


class TestStoreMigrateMetadata:
    def _setup(self, tmp_path, naming_authority="org.middle-earth"):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "gnss"
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

    def test_a_migrated_store_gets_its_content_settings(self, tmp_path):
        """ADR 0019: from the settings of the first commit (#349)."""
        from canvod.store_metadata import migrate_metadata, read_repository_metadata

        config_dir, store_path = self._setup(tmp_path)
        migrate_metadata(store_path, who=testing.PERSON_INITIALS)
        assert not read_repository_metadata(store_path).get("content_settings")
        command = ["store", "migrate-metadata", "TestSite", "--store", "gnss", "--yes"]

        result = runner.invoke(main_app, command, env=_env(config_dir))

        assert result.exit_code == 0, result.output
        assert "Content settings written" in result.output
        content = read_repository_metadata(store_path)["content_settings"]
        assert content["origin"] == "migrated"
        assert content["set_by"] == testing.PERSON_INITIALS
        again = runner.invoke(main_app, command, env=_env(config_dir))
        assert again.exit_code == 0, again.output
        assert "already migrated" in again.output

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
        store_path = stores_root / "TestSite" / "gnss"
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
        store_path = stores_root / "TestSite" / "gnss"
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
        store_path = stores_root / "TestSite" / "gnss"
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
        store_path = stores_root / "TestSite" / "gnss"
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
        store_path = stores_root / "TestSite" / "gnss"
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
        _write_old_form_store(stores_root / "TestSite" / "gnss")
        _write_old_form_store(store_path, store_type="vod_store")

        result = runner.invoke(
            main_app,
            [
                "store",
                "migrate-metadata",
                "TestSite",
                "--store",
                "vod",
                "--yes",
                "--set",
                "gnss_content_hash=" + "a" * 64,
            ],
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

    def _epoch_time_systems(self, store_path) -> dict[str, object]:
        """The time scale each data group's epochs record, by group."""
        import zarr

        from canvod.store_metadata.location import open_repository, store_location

        repo = open_repository(store_location(store_path))
        root = zarr.open_group(repo.readonly_session(branch="main").store, mode="r")
        return {
            path: node["epoch"].attrs.get("time_system")
            for path, node in root.members(max_depth=None)
            if isinstance(node, zarr.Group) and "epoch" in node
        }

    def _migrate(self, config_dir, store="gnss", *args):
        loader_module.load_config.cache_clear()
        return runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", store, "--yes", *args],
            env=_env(config_dir),
        )

    def test_rinex_epochs_are_labelled_gps_time(self, tmp_path):
        """canVODpy 0.x stored RINEX epochs as read: GPS time, unlabelled."""
        config_dir, store_path = self._setup(tmp_path)

        result = self._migrate(config_dir)

        assert result.exit_code == 0, result.output
        assert "GPS time" in result.output
        assert self._epoch_time_systems(store_path) == {"canopy_01": "GPS"}
        again = self._migrate(config_dir)
        assert again.exit_code == 0, again.output
        assert "already migrated" in again.output

    def test_sbf_epochs_refuse_the_migration(self, tmp_path):
        """canVODpy 0.x stored SBF epochs in UTC: rebuilt, never shifted."""
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "gnss"
        _write_old_form_store(store_path, source="sbf")

        result = self._migrate(config_dir)

        assert result.exit_code == 1, result.output
        assert "canopy_01" in result.output
        assert "UTC" in result.output
        assert "raw files" in result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)

    def test_vod_epochs_are_labelled_after_the_gnss_store(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_old_form_store(stores_root / "TestSite" / "gnss")
        store_path = stores_root / "TestSite" / "vod"
        _write_old_form_store(store_path, store_type="vod_store")

        result = self._migrate(
            config_dir, "vod", "--set", "gnss_content_hash=" + "a" * 64
        )

        assert result.exit_code == 0, result.output
        assert self._epoch_time_systems(store_path) == {
            "tau_omega/canopy_01_vs_reference_01": "GPS"
        }

    def test_vod_epochs_from_sbf_refuse_the_migration(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_old_form_store(stores_root / "TestSite" / "gnss", source="sbf")
        store_path = stores_root / "TestSite" / "vod"
        _write_old_form_store(store_path, store_type="vod_store")

        result = self._migrate(
            config_dir, "vod", "--set", "gnss_content_hash=" + "a" * 64
        )

        assert result.exit_code == 1, result.output
        assert "raw files" in result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)

    def test_missing_fields_come_from_the_settings(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        settings = yaml.safe_load((config_dir / "canvod-settings.yaml").read_text())
        settings["processing"]["metadata"].update(
            {
                "publisher": "B",
                "publisher_url": "https://b.example",
                "license": "CC-BY-4.0",
            }
        )
        settings["sites"]["TestSite"].update(
            {
                "store_description": "Test site observations.",
                "latitude": testing.LATITUDE,
                "longitude": testing.LONGITUDE,
            }
        )
        (config_dir / "canvod-settings.yaml").write_text(yaml.safe_dump(settings))
        store_path = stores_root / "TestSite" / "gnss"
        _write_old_form_store(store_path, complete=False)

        result = self._migrate(config_dir, "gnss", "--set", "publisher.name=C")

        assert result.exit_code == 0, result.output
        assert "from the settings" in result.output
        from canvod.store_metadata import read_metadata, validate_all

        meta = read_metadata(store_path)
        assert meta.identity.description == "Test site observations."
        assert meta.publisher.name == "C"
        assert str(meta.publisher.url).rstrip("/") == "https://b.example"
        assert meta.spatial.geospatial_lat == testing.LATITUDE
        assert not any(validate_all(meta, recommended=False).values())

    def test_the_gnss_content_hash_comes_from_the_sites_gnss_store(self, tmp_path):
        """The stores were moved: the recorded GNSS store path is gone."""
        from canvod.store_metadata import read_repository_metadata

        config_dir = tmp_path / "config"
        old_root = tmp_path / "stores"
        _write_config(config_dir, old_root)
        _write_old_form_store(old_root / "TestSite" / "gnss")
        _write_old_form_store(old_root / "TestSite" / "vod", store_type="vod_store")
        new_root = tmp_path / "moved"
        old_root.rename(new_root)
        _write_config(config_dir, new_root)
        assert self._migrate(config_dir, "gnss").exit_code == 0

        result = self._migrate(config_dir, "vod")

        assert result.exit_code == 0, result.output
        gnss = read_repository_metadata(new_root / "TestSite" / "gnss")
        vod = read_repository_metadata(new_root / "TestSite" / "vod")
        assert (
            vod["content_settings"]["gnss_content_hash"]
            == gnss["content_settings"]["hash"]
        )

    def test_a_gnss_store_without_content_settings_lists_the_hash(self, tmp_path):
        """The VOD store waits for the GNSS store's content settings."""
        from canvod.store_metadata import migrate_metadata

        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_old_form_store(stores_root / "TestSite" / "gnss")
        _write_old_form_store(stores_root / "TestSite" / "vod", store_type="vod_store")
        migrate_metadata(stores_root / "TestSite" / "gnss", who="JD")

        result = self._migrate(config_dir, "vod")

        assert result.exit_code == 1, result.output
        assert "gnss_content_hash" in result.output

    def test_preprocessing_the_data_do_not_show_is_not_recorded(self, tmp_path):
        """canVODpy 0.x recorded preprocessing settings its runs never applied."""
        from canvod.store_metadata import read_repository_metadata

        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        path = config_dir / "canvod-settings.yaml"
        plain = path.read_text()
        settings = yaml.safe_load(plain)
        settings["processing"]["preprocessing"] = {
            "temporal_aggregation": {
                "enabled": True,
                "freq": "1min",
                "method": "mean",
                "integer_method": "first",
            }
        }
        path.write_text(yaml.safe_dump(settings))
        store_path = stores_root / "TestSite" / "gnss"
        _write_old_form_store(store_path)
        path.write_text(plain)

        result = self._migrate(config_dir)

        assert result.exit_code == 0, result.output
        content = read_repository_metadata(store_path)["content_settings"]
        assert content["settings"]["processing"]["preprocessing"] is None

    def test_vod_analyses_come_from_the_groups_of_the_store(self, tmp_path):
        """canVODpy 0.x listed no VOD analyses; its groups show them."""
        from canvod.store_metadata import read_repository_metadata

        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        path = config_dir / "canvod-settings.yaml"
        settings = yaml.safe_load(path.read_text())
        settings["sites"]["TestSite"]["receivers"]["reference_01"] = {
            "type": "reference",
            "directory": "01_reference",
            "paired_canopies": ["canopy_01"],
        }
        path.write_text(yaml.safe_dump(settings))
        _write_old_form_store(stores_root / "TestSite" / "gnss")
        store_path = stores_root / "TestSite" / "vod"
        _write_old_form_store(store_path, store_type="vod_store")

        result = self._migrate(
            config_dir, "vod", "--set", "gnss_content_hash=" + "a" * 64
        )

        assert result.exit_code == 0, result.output
        assert read_repository_metadata(store_path)["vod_analyses"] == {
            "canopy_01_vs_reference_01": {
                "canopy_receiver": "canopy_01",
                "reference_receiver": "reference_01",
            }
        }

    def test_stored_variables_decide_their_switches(self, tmp_path):
        """canVODpy 0.x wrote delta_snr whatever store_delta_snr said."""
        import icechunk
        import zarr

        from canvod.store_metadata import read_repository_metadata

        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        _write_old_form_store(stores_root / "TestSite" / "gnss")
        store_path = stores_root / "TestSite" / "vod"
        _write_old_form_store(store_path, store_type="vod_store")
        repo = icechunk.Repository.open(
            icechunk.local_filesystem_storage(str(store_path))
        )
        session = repo.writable_session("main")
        group = zarr.open_group(
            session.store, mode="a", path="tau_omega/canopy_01_vs_reference_01"
        )
        vod = group["VOD"]
        group.create_array(
            "delta_snr",
            shape=vod.shape,
            dtype="f8",
            dimension_names=("epoch", "sid"),
        )
        session.commit("as canVODpy 0.x wrote it")

        result = self._migrate(
            config_dir, "vod", "--set", "gnss_content_hash=" + "a" * 64
        )

        assert result.exit_code == 0, result.output
        params = read_repository_metadata(store_path)["content_settings"]["settings"][
            "processing"
        ]["params"]
        assert params["store_delta_snr"] is True
        assert params["store_radial_diff"] is False
        # The GNSS store records the VOD switches too, as the VOD data show.
        assert self._migrate(config_dir, "gnss").exit_code == 0
        gnss = read_repository_metadata(stores_root / "TestSite" / "gnss")
        params = gnss["content_settings"]["settings"]["processing"]["params"]
        assert params["store_delta_snr"] is True
        assert params["store_radial_distance"] is False

    def test_an_empty_value_is_refused(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = self._migrate(config_dir, "gnss", "--set", "identity.description=")

        assert result.exit_code == 1, result.output
        assert "identity.description" in result.output
        assert "no value" in result.output
        from canvod.store_metadata import metadata_exists

        assert not metadata_exists(store_path)


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

    path = stores_root / site / "gnss"
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
        return config_dir, stores_root / "TestSite" / "gnss"

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

    def test_an_added_receiver_records_the_sha256_of_its_recipe(self, tmp_path):
        pytest.importorskip("canvod.filemap.recipe_files")
        import hashlib

        config_dir, path = self._setup(
            tmp_path,
            receivers={
                "canopy_02": {
                    "type": "canopy",
                    "directory": "03_canopy",
                    "recipe": "rx",
                }
            },
        )
        recipe = config_dir / "recipes" / "TestSite" / "rx.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_bytes(b"name: rx\n")

        result = self._amend(
            config_dir, "--add-receiver", "canopy_02", "--reason", "r", "--yes"
        )

        assert result.exit_code == 0, result.output
        from canvod.store_metadata import read_metadata

        receiver = read_metadata(path).instruments.receivers["canopy_02"]
        assert receiver.recipe_sha256 == hashlib.sha256(b"name: rx\n").hexdigest()

    def test_a_receiver_whose_recipe_is_missing_is_refused(self, tmp_path):
        config_dir, path = self._setup(
            tmp_path,
            receivers={
                "canopy_02": {
                    "type": "canopy",
                    "directory": "03_canopy",
                    "recipe": "rx",
                }
            },
        )

        result = self._amend(
            config_dir, "--add-receiver", "canopy_02", "--reason", "r", "--yes"
        )

        assert result.exit_code == 1
        assert "'rx'" in result.output
        from canvod.store_metadata import read_metadata

        assert "canopy_02" not in read_metadata(path).instruments.receivers

    def test_an_updated_recipe_is_recorded_and_lets_runs_through(self, tmp_path):
        pytest.importorskip("canvod.filemap.recipe_files")
        import hashlib

        from canvod.config import load_config
        from canvod.store_metadata import check_recipes, read_repository_metadata

        config_dir, path = self._setup(
            tmp_path,
            receivers={
                "canopy_01": {"type": "canopy", "directory": "c", "recipe": "rx"}
            },
        )
        recipe = config_dir / "recipes" / "TestSite" / "rx.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_bytes(b"name: rx\n")

        def check() -> None:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("CANVOD_CONFIG_DIR", str(config_dir))
                site = load_config().sites.sites["TestSite"]
                check_recipes(
                    read_repository_metadata(path), site, "TestSite", store_path=path
                )

        with pytest.raises(ValueError, match="--update-recipe canopy_01"):
            check()

        result = self._amend(
            config_dir, "--update-recipe", "canopy_01", "--reason", "rx", "--yes"
        )

        assert result.exit_code == 0, result.output
        receiver = read_repository_metadata(path)["instruments"]["receivers"][
            "canopy_01"
        ]
        assert receiver["recipe"] == "rx"
        assert receiver["recipe_sha256"] == hashlib.sha256(b"name: rx\n").hexdigest()
        check()

    def test_a_recipe_of_a_receiver_the_store_lacks_is_refused(self, tmp_path):
        config_dir, path = self._setup(
            tmp_path,
            receivers={
                "canopy_02": {"type": "canopy", "directory": "c2", "recipe": "rx"}
            },
        )

        result = self._amend(
            config_dir, "--update-recipe", "canopy_02", "--reason", "rx", "--yes"
        )

        assert result.exit_code == 1
        assert "--add-receiver canopy_02" in result.output
        from canvod.store_metadata import read_metadata

        assert "canopy_02" not in read_metadata(path).instruments.receivers

    def test_a_recipe_is_not_recorded_in_the_vod_store(self, tmp_path):
        import icechunk

        config_dir, path = self._setup(tmp_path)
        vod = path.parent / "vod"
        icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(vod)))

        result = runner.invoke(
            main_app,
            [
                "store",
                "amend",
                "TestSite",
                "--store",
                "vod",
                "--update-recipe",
                "canopy_01",
                "--reason",
                "rx",
                "--yes",
            ],
            env=_env(config_dir),
        )

        assert result.exit_code == 1
        assert "--store gnss" in result.output

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


class TestStoreMigrateLayout:
    def _setup(self, tmp_path):
        config_dir = tmp_path / "config"
        stores_root = tmp_path / "stores"
        _write_config(config_dir, stores_root)
        store_path = stores_root / "TestSite" / "gnss"
        _write_synthetic_store(store_path)
        return config_dir, store_path

    def _is_day_blocks(self, store_path) -> bool:
        import zarr

        from canvod.store_metadata.layout import is_day_block_group
        from canvod.store_metadata.location import open_repository, store_location

        repo = open_repository(store_location(store_path))
        session = repo.readonly_session(branch="main")
        group = zarr.open_group(session.store, mode="r", path="canopy_01")
        return is_day_block_group(group.attrs)

    def test_shows_the_plan_and_moves_after_confirmation(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = runner.invoke(
            main_app,
            ["store", "migrate-layout", "TestSite", "--store", "gnss", "--yes"],
            env=_env(config_dir),
        )

        assert result.exit_code == 0, result.output
        assert "canopy_01" in result.output
        assert "rewrite" in result.output
        assert "Moved to day blocks" in result.output
        assert self._is_day_blocks(store_path)

    def test_declining_leaves_the_store_as_it_is(self, tmp_path):
        config_dir, store_path = self._setup(tmp_path)

        result = runner.invoke(
            main_app,
            ["store", "migrate-layout", "TestSite", "--store", "gnss"],
            env=_env(config_dir),
            input="n\n",
        )

        assert result.exit_code == 1
        assert not self._is_day_blocks(store_path)

    def test_a_moved_store_is_named_as_such(self, tmp_path):
        config_dir, _ = self._setup(tmp_path)
        command = ["store", "migrate-layout", "TestSite", "--store", "gnss", "--yes"]
        runner.invoke(main_app, command, env=_env(config_dir))
        loader_module.load_config.cache_clear()

        result = runner.invoke(main_app, command, env=_env(config_dir))

        assert result.exit_code == 0, result.output
        assert "day blocks already" in result.output
