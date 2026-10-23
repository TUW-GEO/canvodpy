"""Importing canvod.store hides only two Icechunk warnings that don't apply."""

import os
import subprocess
import sys

import icechunk
import pytest

SCRIPT = """
import icechunk
calls = []
icechunk.set_logs_filter = calls.append
import canvod.store
print(calls)
"""


def _filters_set_on_import(env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


@pytest.fixture
def env_without_icechunk_log() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "ICECHUNK_LOG"}


def test_only_two_warnings_are_hidden(env_without_icechunk_log):
    # The concurrent-commit warning (commits run under commit_lock) and the
    # lost-reply warning (local storage keeps no write metadata, no retries);
    # every other Icechunk warning is shown.
    assert _filters_set_on_import(env_without_icechunk_log) == (
        "['warn,icechunk_arrow_object_store=error,icechunk_storage::readback=error']"
    )


def test_local_storage_cannot_keep_write_metadata(tmp_path):
    """The lost-reply warning asks for a setting local storage refuses."""
    config = icechunk.RepositoryConfig.default()
    config.storage = icechunk.StorageSettings(unsafe_use_metadata=True)
    with pytest.raises(icechunk.StorageError, match="attributes"):
        icechunk.Repository.create(
            icechunk.local_filesystem_storage(str(tmp_path)), config=config
        )
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "b"))
    )
    assert repo.config.storage.unsafe_use_metadata is False
    assert repo.config.storage.retries.max_tries == 1


def test_icechunk_log_replaces_the_filter(env_without_icechunk_log):
    env = {**env_without_icechunk_log, "ICECHUNK_LOG": "icechunk=debug"}
    assert _filters_set_on_import(env) == "[]"
