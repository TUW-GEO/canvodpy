"""`canvodpy store maintain`/`maintain-due` on a store on S3 (#357).

Against a real S3 service, like ``canvodpy/tests/test_s3_run.py``: CI runs
them against an S3 emulator (RustFS, ``.github/workflows/test_s3.yml``).
They need ``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket that
exists) and the ``AWS_*`` variables the service needs; without the URL they
are skipped.

On S3 a store may have writers on several machines, so maintenance is a dry
run only: ``maintain --execute`` is refused (exit 1) and ``maintain-due``
reports a due store as a dry run and exits 0.
"""

from __future__ import annotations

import os
import uuid

import pytest
import yaml
import zarr
from canvodpy.cli.app import main_app
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils import testing

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

needs_s3 = pytest.mark.skipif(
    not S3_URL,
    reason=(
        "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
        "AWS_* variables to run the S3 tests (see the module docstring)."
    ),
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """load_config() is lru_cache'd on (config_dir, config_file) args only --
    it doesn't know CANVOD_CONFIG_DIR changed between tests. Clear it so each
    invoke() resolves its own config file (see test_cli_store.py)."""
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


def _write_config(config_dir, stores_root, *, dry_run_until_confirmed: bool) -> None:
    """A config whose GNSS store lives at ``stores_root/TestSite/gnss``."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": {
                        "author": testing.PERSON_NAME,
                        "email": testing.PERSON_EMAIL,
                        "institution": "B",
                    },
                    "storage": {
                        "stores_root_dir": stores_root,
                        "maintenance": {
                            "enabled": True,
                            "dry_run_until_confirmed": dry_run_until_confirmed,
                            "retention_days": 90,
                            "expire_interval_days": 45,
                            "gc_delay_days": 20,
                        },
                    },
                },
                "sites": {
                    "TestSite": {
                        "gnss_site_data_root": "/tmp/raw",
                        "receivers": {
                            "canopy_01": {
                                "type": "canopy",
                                "directory": "02_canopy",
                            },
                        },
                    },
                },
            }
        )
    )


def _make_s3_store(store_path: str, n_commits: int = 2) -> None:
    """Create a store on S3 at ``store_path`` with ``n_commits`` commits."""
    from canvod.store_metadata import open_repository

    repo = open_repository(store_path, create=True)
    for i in range(n_commits):
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="a").attrs["i"] = i
        session.commit(f"seed {i}")


def _s3_root() -> str:
    return f"{S3_URL.rstrip('/')}/maintcli-{uuid.uuid4().hex}"


def _snapshot_ids(store_path: str) -> list[str]:
    from canvod.store_metadata import open_repository

    repo = open_repository(store_path)
    return [snap.id for snap in repo.ancestry(branch="main")]


@needs_s3
def test_maintain_execute_on_s3_is_refused_and_changes_nothing(tmp_path) -> None:
    config_dir = tmp_path / "config"
    root = _s3_root()
    store_path = f"{root}/TestSite/gnss"
    _write_config(config_dir, root, dry_run_until_confirmed=True)
    _make_s3_store(store_path)
    before = _snapshot_ids(store_path)

    result = runner.invoke(
        main_app,
        ["store", "maintain", "TestSite", "--execute"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
        input="n\n",  # no confirmation prompt may appear on S3
    )

    assert result.exit_code == 1, result.output
    assert "DRY RUN" in result.output
    assert "Re-run with --execute" not in result.output
    assert "--execute is not supported on S3 yet" in result.output
    assert "Maintenance complete" not in result.output
    assert _snapshot_ids(store_path) == before


@needs_s3
def test_maintain_due_on_s3_reports_a_dry_run_and_exits_0(tmp_path) -> None:
    config_dir = tmp_path / "config"
    root = _s3_root()
    store_path = f"{root}/TestSite/gnss"
    _write_config(config_dir, root, dry_run_until_confirmed=False)
    _make_s3_store(store_path)
    before = _snapshot_ids(store_path)

    result = runner.invoke(
        main_app,
        ["store", "maintain-due", "TestSite", "--store", "gnss"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    assert (
        "DRY RUN (store on S3: maintenance on S3 is not supported yet)" in result.output
    )
    assert "Would garbage-collect" in result.output or "Would expire" in result.output
    assert _snapshot_ids(store_path) == before
