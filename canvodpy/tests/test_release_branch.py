"""The release script refuses a release whose branch exists already.

``just release`` commits on the new branch ``release/v<canvodpy version>``.
When that branch exists, locally or on a remote, the refusal must come before
any file is written, not from ``git switch -c`` after all of them are.
"""

import subprocess
from pathlib import Path

import pytest
from test_release_citation import release

BRANCH = "release/v1.0.0"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.org",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    return tmp_path


def test_a_free_branch_name_is_not_taken(repo: Path) -> None:
    assert release._branch_taken(BRANCH, root=repo) is False


def test_a_local_branch_takes_the_name(repo: Path) -> None:
    _git(repo, "branch", BRANCH)
    assert release._branch_taken(BRANCH, root=repo) is True


def test_a_remote_branch_takes_the_name(repo: Path) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    _git(repo, "update-ref", f"refs/remotes/origin/{BRANCH}", head)
    assert release._branch_taken(BRANCH, root=repo) is True
