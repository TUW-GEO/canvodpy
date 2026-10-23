"""Importing canvod.store_metadata hides only two Icechunk warnings that don't apply."""

import os
import subprocess
import sys

import pytest

from canvod.store_metadata.icechunk_logs import ICECHUNK_LOG_FILTER

SCRIPT = """
import icechunk
calls = []
icechunk.set_logs_filter = calls.append
import {module}
print(calls)
"""


def _filters_set_on_import(module: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(module=module)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


@pytest.fixture
def env_without_icechunk_log() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "ICECHUNK_LOG"}


def test_importing_store_metadata_sets_the_filter_once(env_without_icechunk_log):
    # The migrate and amend commands open stores without canvod.store.
    calls = _filters_set_on_import("canvod.store_metadata", env_without_icechunk_log)
    assert calls == str([ICECHUNK_LOG_FILTER])


def test_icechunk_log_replaces_the_filter(env_without_icechunk_log):
    env = {**env_without_icechunk_log, "ICECHUNK_LOG": "icechunk=debug"}
    assert _filters_set_on_import("canvod.store_metadata", env) == "[]"
