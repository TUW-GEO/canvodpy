"""`canvodpy store log --path s3://...` on a store on S3 (#477).

Against a real S3 service, like ``canvodpy/tests/test_s3_maintenance_cli.py``:
CI runs them against an S3 emulator (RustFS, ``.github/workflows/test_s3.yml``).
They need ``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket that
exists) and the ``AWS_*`` variables the service needs; without the URL they
are skipped.
"""

from __future__ import annotations

import os
import uuid

import pytest
import zarr
from canvodpy.cli.app import main_app
from typer.testing import CliRunner

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

pytestmark = pytest.mark.skipif(
    not S3_URL,
    reason=(
        "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
        "AWS_* variables to run the S3 tests (see the module docstring)."
    ),
)

runner = CliRunner()


def _store_url() -> str:
    return f"{S3_URL.rstrip('/')}/logcli-{uuid.uuid4().hex}/gnss"


def test_log_opens_a_store_on_s3_by_its_url(tmp_path) -> None:
    from canvod.store_metadata import open_repository

    url = _store_url()
    repo = open_repository(url, create=True)
    for i in range(2):
        session = repo.writable_session("main")
        zarr.open_group(session.store, mode="a").attrs["i"] = i
        session.commit(f"seed {i}")

    result = runner.invoke(
        main_app,
        ["store", "log", "--path", url, "--plain"],
        env={"CANVOD_CONFIG_DIR": str(tmp_path / "no-settings")},
    )

    assert result.exit_code == 0, result.output
    assert "seed 0" in result.output
    assert "seed 1" in result.output


def test_log_refuses_an_s3_url_without_a_store(tmp_path) -> None:
    url = _store_url()

    result = runner.invoke(
        main_app,
        ["store", "log", "--path", url],
        env={"CANVOD_CONFIG_DIR": str(tmp_path / "no-settings")},
    )

    assert result.exit_code == 1
    assert "No store at" in result.output
    assert url in result.output
