"""A run writes its stores on S3 as it writes them in a local folder (#350).

Against a real S3 service, like the store tests of canvod-store-metadata
(``packages/canvod-store-metadata/tests/test_s3_store.py``), and locally
only: they read the test data, which CI never checks out. Run them against
an S3 emulator such as RustFS (``.github/workflows/test_s3.yml`` shows the
setup). They need ``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket
that exists) and the ``AWS_*`` variables the service needs; without the URL
they are skipped.
"""

from __future__ import annotations

import os
import uuid

import pytest
import xarray as xr
import zarr
from canvodpy.run_history import RunHistory
from typer.testing import CliRunner

from canvod.store import MyIcechunkStore
from canvod.utils import testing

DAY = "2025001"
S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

pytestmark = pytest.mark.integration
needs_s3 = pytest.mark.skipif(
    not S3_URL,
    reason=(
        "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
        "AWS_* variables to run the S3 tests (see the module docstring)."
    ),
)


def _run(*extra: str, exit_code: int = 0) -> str:
    from canvodpy.cli.app import main_app

    result = CliRunner().invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--start", DAY, "--end", DAY, *extra],
    )
    assert result.exit_code == exit_code, result.output
    return result.output


def _data_groups(store: MyIcechunkStore) -> list[str]:
    """The groups that hold data (an ``epoch`` axis), nested ones included."""
    with store.readonly_session("main") as session:
        root = zarr.open_group(session.store, mode="r")
        return sorted(
            path
            for path, member in root.members(max_depth=None)
            if isinstance(member, zarr.Group) and "epoch" in member
        )


def _assert_same_data(local: MyIcechunkStore, s3: MyIcechunkStore) -> None:
    groups = _data_groups(local)
    assert groups
    assert _data_groups(s3) == groups
    for group in groups:
        expected = local.read_group(group, drop_empty=True)
        stored = s3.read_group(group, drop_empty=True)
        assert stored.sizes == expected.sizes
        for name in expected.data_vars:
            xr.testing.assert_equal(
                stored[name].reset_coords(drop=True).drop_attrs(),
                expected[name].reset_coords(drop=True).drop_attrs(),
            )


@needs_s3
def test_a_run_writes_the_same_stores_on_s3_as_in_a_local_folder(
    fangorn_site, tmp_path
) -> None:
    config, _ = fangorn_site
    storage = config.processing.storage

    _run()
    local_gnss = storage.get_gnss_store_path(testing.SITE_KEY)
    local_vod = storage.get_vod_store_path(testing.SITE_KEY)

    storage.stores_root_dir = f"{S3_URL.rstrip('/')}/run-{uuid.uuid4().hex}"
    # A log folder of its own, so the second run below is the only other
    # run in its run history.
    config.processing.logging.log_dir = tmp_path / "logs_s3"
    _run()
    s3_gnss = storage.get_gnss_store_path(testing.SITE_KEY)
    s3_vod = storage.get_vod_store_path(testing.SITE_KEY)
    assert str(s3_gnss).startswith("s3://")

    _assert_same_data(
        MyIcechunkStore(local_gnss, config=config),
        MyIcechunkStore(s3_gnss, config=config),
    )
    _assert_same_data(
        MyIcechunkStore(local_vod, store_type="vod_store", config=config),
        MyIcechunkStore(s3_vod, store_type="vod_store", config=config),
    )

    # A second run on the same day finds every file already stored.
    _run("--no-vod")
    with RunHistory.open(config.processing.logging.log_dir, read_only=True) as h:
        last = h.runs(site=testing.SITE_KEY)[0]
        results = {day.result for day in h.receiver_days(last.run_id)}
    assert results == {"skipped"}
    assert not any(disk.startswith("s3:") for disk in last.machine["disks"])
    gnss = MyIcechunkStore(s3_gnss, config=config)
    assert "skipped=" in next(iter(gnss.repo.ancestry(branch="main"))).message


def test_a_run_says_what_to_check_when_s3_cannot_be_reached(
    fangorn_site, monkeypatch
) -> None:
    config, _ = fangorn_site
    secret = "made-up-secret-of-the-ents"
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "made-up-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # Nothing listens on the discard port.
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CANVOD_S3_PATH_STYLE", "1")
    config.processing.storage.stores_root_dir = "s3://fangorn/stores"

    output = _run("--no-vod", exit_code=1)

    assert "The storage at s3://fangorn/stores/fangorn/" in output
    assert "can't be reached" in output
    assert "AWS_ENDPOINT_URL" in output
    assert secret not in output
