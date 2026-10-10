"""Importing canvod.store hides only Icechunk's concurrent-commit warning."""

import os
import subprocess
import sys

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


def test_only_the_concurrent_commit_warning_is_hidden(env_without_icechunk_log):
    # The warning comes from icechunk_arrow_object_store; every other
    # Icechunk warning is shown (commits run under commit_lock).
    assert _filters_set_on_import(env_without_icechunk_log) == (
        "['warn,icechunk_arrow_object_store=error']"
    )


def test_icechunk_log_replaces_the_filter(env_without_icechunk_log):
    env = {**env_without_icechunk_log, "ICECHUNK_LOG": "icechunk=debug"}
    assert _filters_set_on_import(env) == "[]"
