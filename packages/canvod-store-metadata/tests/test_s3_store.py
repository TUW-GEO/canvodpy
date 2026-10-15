"""Stores on S3, against a real S3 service (#303).

CI runs these against an S3 emulator (RustFS, ``.github/workflows/test_s3.yml``);
any S3 service with conditional writes works. They need:

- ``CANVOD_TEST_S3_URL``: ``s3://bucket/prefix``, a bucket that exists; each
  test makes a new store under the prefix.
- The ``AWS_*`` variables the service needs (credentials, ``AWS_ENDPOINT_URL``,
  ``AWS_REGION``) and, for a self-hosted service, ``CANVOD_S3_PATH_STYLE=1``.

Without ``CANVOD_TEST_S3_URL`` they are skipped.
"""

import json
import logging
import os
import threading
import uuid

import icechunk
import pytest
import zarr
from canvod.utils.testing import SITE_KEY

from canvod.store_metadata import open_repository, store_exists, store_location
from canvod.store_metadata.io import ensure_metadata, read_metadata
from canvod.store_metadata.location import S3StoreLocation, read_store_uuid
from canvod.store_metadata.show import show_metadata
from canvod.store_metadata.testing import made_up_metadata

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not S3_URL,
        reason=(
            "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
            "AWS_* variables to run the S3 tests (see the module docstring)."
        ),
    ),
]


@pytest.fixture
def location() -> S3StoreLocation:
    """A new, empty store location under ``CANVOD_TEST_S3_URL``."""
    root = store_location(S3_URL)
    assert isinstance(root, S3StoreLocation)
    return root / f"test-{uuid.uuid4().hex}"


@pytest.fixture
def with_metadata(location: S3StoreLocation) -> S3StoreLocation:
    """A store at ``location`` with the made-up site's metadata."""
    ensure_metadata(
        location, made_up_metadata, site_name=SITE_KEY, store_type="gnss_store"
    )
    return location


def test_a_store_is_created_on_s3_and_opened_again(location) -> None:
    assert not store_exists(location)

    open_repository(location, create=True)

    assert store_exists(location)
    # Opened again from its URL, as a user gives it.
    open_repository(str(location))
    with pytest.raises(FileExistsError, match=str(location)):
        open_repository(location, create=True)


def test_store_metadata_is_written_and_read_back(with_metadata) -> None:
    expected = made_up_metadata()

    meta = read_metadata(with_metadata)

    assert meta.identity.title == expected.identity.title
    assert meta.spatial.site.name == expected.spatial.site.name
    assert read_store_uuid(with_metadata)


def test_show_prints_the_metadata_of_a_store_on_s3(with_metadata, capsys) -> None:
    show_metadata(str(with_metadata), section="identity")

    out = capsys.readouterr().out
    assert made_up_metadata().identity.title in out


def test_a_second_commit_on_an_old_tip_is_refused(location) -> None:
    repo = open_repository(location, create=True)
    first = repo.writable_session("main")
    second = repo.writable_session("main")
    zarr.open_group(first.store, mode="a").attrs["writer"] = "first"
    zarr.open_group(second.store, mode="a").attrs["writer"] = "second"
    first.commit("first")

    with pytest.raises(icechunk.ConflictError):
        second.commit("second")

    tip = open_repository(location).readonly_session("main")
    assert zarr.open_group(tip.store, mode="r").attrs["writer"] == "first"


def test_racing_commits_lose_nothing_silently(location) -> None:
    # Commits that start from the same tip at the same moment: S3's
    # conditional writes let exactly one through; every other one fails
    # with a conflict instead of being overwritten without an error.
    writers = 8
    repo = open_repository(location, create=True)
    sessions = [repo.writable_session("main") for _ in range(writers)]
    for i, session in enumerate(sessions):
        zarr.open_group(session.store, mode="a").attrs["writer"] = i
    start = threading.Barrier(writers)
    committed: list[int] = []
    refused: list[int] = []

    def commit(i: int) -> None:
        start.wait()
        try:
            sessions[i].commit(f"writer {i}")
        except icechunk.ConflictError:
            refused.append(i)
        else:
            committed.append(i)

    threads = [threading.Thread(target=commit, args=(i,)) for i in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(committed) == 1
    assert sorted(committed + refused) == list(range(writers))
    history = list(open_repository(location).ancestry(branch="main"))
    assert len(history) == 2  # the repository's first snapshot and one commit
    tip = open_repository(location).readonly_session("main")
    assert zarr.open_group(tip.store, mode="r").attrs["writer"] == committed[0]


def test_no_credential_reaches_the_output(location, capsys, caplog) -> None:
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
    caplog.set_level(logging.DEBUG)

    ensure_metadata(
        location, made_up_metadata, site_name=SITE_KEY, store_type="gnss_store"
    )
    show_metadata(str(location))
    repo = open_repository(location)
    texts = [
        # What the store keeps: its repository metadata and every commit's.
        json.dumps(repo.get_metadata(), default=str),
        *(
            json.dumps(snapshot.metadata, default=str)
            for snapshot in repo.ancestry(branch="main")
        ),
        str(location),
        repr(location),
        repr(location.storage()),
        location.access_hint,
        caplog.text,
        *capsys.readouterr(),
    ]

    for text in texts:
        for credential in (secret, key_id):
            if credential:
                assert credential not in text
