"""``config init --from-store`` on a store in the S3 emulator (#356).

Against a real S3 service, like the store tests of canvod-store-metadata
(``packages/canvod-store-metadata/tests/test_s3_store.py``); CI runs them
against an S3 emulator (RustFS, ``.github/workflows/test_s3.yml``). They
need ``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket that exists)
and the ``AWS_*`` variables the service needs; without the URL they are
skipped.
"""

from __future__ import annotations

import os
import uuid

import pytest
import yaml
from typer.testing import CliRunner

from canvod.config import load_config
from canvod.config.models import ReceiverConfig
from canvod.store_metadata import ensure_store_metadata
from canvod.utils import testing

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

pytestmark = pytest.mark.integration
needs_s3 = pytest.mark.skipif(
    not S3_URL,
    reason=(
        "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
        "AWS_* variables to run the S3 tests (see the module docstring)."
    ),
)


@needs_s3
def test_config_init_from_store_on_s3(tmp_path) -> None:
    from canvodpy.cli.app import main_app

    folder = tmp_path / "settings"
    testing.write_settings(folder)
    config = load_config(config_dir=folder).model_copy(deep=True)
    site = config.sites.sites[testing.SITE_KEY]
    site.store_description = "GNSS-T observations below an Ent canopy"
    site.receivers["reference_01"] = ReceiverConfig(
        type="reference", directory="01_reference", paired_canopies=["canopy_01"]
    )

    root = f"{S3_URL.rstrip('/')}/cfg-{uuid.uuid4().hex}"
    store = f"{root}/{testing.SITE_KEY}/rinex"
    ensure_store_metadata(
        store,
        config=config,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=["canopy_01", "reference_01_canopy_01"],
    )

    config_dir = tmp_path / "config"
    result = CliRunner().invoke(
        main_app,
        [
            "config",
            "init",
            "--config-dir",
            str(config_dir),
            "--from-store",
            store,
            "--no-interactive",
        ],
    )
    assert result.exit_code == 0, result.output

    settings = yaml.safe_load((config_dir / "canvod-settings.yaml").read_text())
    assert str(settings["processing"]["storage"]["stores_root_dir"]).startswith("s3://")
    assert settings["processing"]["storage"]["gnss_store_name"] == "rinex"
