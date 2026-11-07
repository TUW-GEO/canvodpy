"""The release script prints the tag pushes that start the release workflow.

GitHub creates no push event for tags when more than three tags are pushed
at once, so pushing every tag together never drafted the GitHub release of
canvodpy v1.0.0. The canvodpy tag goes in a push of its own, and every push
has --no-follow-tags: with push.followTags, git adds the other annotated tags
of the commit to the first push, as it did for v1.1.0.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_release():
    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


release = _load_release()

PACKAGE_TAGS = [
    "canvod-auxiliary-v1.0.0",
    "canvod-config-v1.0.0",
    "canvod-grids-v1.0.0",
    "canvod-store-v1.0.0",
]


def test_the_canvodpy_tag_is_pushed_on_its_own_first() -> None:
    commands = release._push_commands(["v1.0.0", *PACKAGE_TAGS])

    assert commands == [
        "git push --no-follow-tags origin v1.0.0",
        "git push --no-follow-tags origin " + " ".join(PACKAGE_TAGS),
    ]


def test_the_canvodpy_tag_comes_first_wherever_it_is_listed() -> None:
    commands = release._push_commands([*PACKAGE_TAGS[:2], "v1.1.0", *PACKAGE_TAGS[2:]])

    assert commands[0] == "git push --no-follow-tags origin v1.1.0"
    assert commands[1] == "git push --no-follow-tags origin " + " ".join(PACKAGE_TAGS)


def test_package_tags_alone_are_one_push() -> None:
    assert release._push_commands(PACKAGE_TAGS) == [
        "git push --no-follow-tags origin " + " ".join(PACKAGE_TAGS)
    ]


def test_the_canvodpy_tag_alone_is_one_push() -> None:
    assert release._push_commands(["v1.0.1"]) == [
        "git push --no-follow-tags origin v1.0.1"
    ]


def test_a_package_whose_name_starts_with_v_is_a_package_tag() -> None:
    assert release._push_commands(["v1.2.0", "vortex-v1.0.0"]) == [
        "git push --no-follow-tags origin v1.2.0",
        "git push --no-follow-tags origin vortex-v1.0.0",
    ]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def tagged_main(tmp_path: Path) -> Path:
    """A clone of a bare origin whose main is a release commit, tagged locally."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root = tmp_path / "canvodpy"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "J. R. R. Tolkien")
    _git(root, "config", "user.email", "jrrt@fangorn.example")
    _git(root, "config", "push.followTags", "true")
    _git(root, "remote", "add", "origin", str(origin))
    for folder, name in (
        ("canvodpy", "canvodpy"),
        *((f"packages/canvod-{n}", f"canvod-{n}") for n in ("a", "b", "c", "d")),
    ):
        (root / folder).mkdir(parents=True)
        (root / folder / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "1.1.0"\n'
        )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "bump: canvodpy 1.1.0")
    _git(root, "push", "-q", "--no-follow-tags", "origin", "main")
    _git(root, "branch", "-q", "--set-upstream-to", "origin/main")
    assert release.main(["tag"], root=root) == 0
    return root


def _origin_tags(root: Path) -> set[str]:
    lines = _git(root, "ls-remote", "--tags", "origin").splitlines()
    return {line.split("refs/tags/", 1)[1] for line in lines if "^{}" not in line}


def test_push_sends_every_release_tag(tagged_main: Path, capsys) -> None:
    assert release.main(["push"], root=tagged_main) == 0

    out = capsys.readouterr().out
    assert "git push --no-follow-tags origin v1.1.0\n" in out
    assert _origin_tags(tagged_main) == {
        "v1.1.0",
        *(f"canvod-{n}-v1.1.0" for n in "abcd"),
    }


def test_push_sends_only_the_tags_origin_lacks(tagged_main: Path, capsys) -> None:
    _git(tagged_main, "push", "-q", "--no-follow-tags", "origin", "v1.1.0")

    assert release.main(["push"], root=tagged_main) == 0

    out = capsys.readouterr().out
    assert "origin v1.1.0" not in out
    assert len(_origin_tags(tagged_main)) == 5


def test_push_refuses_a_commit_that_is_not_origin_main(
    tagged_main: Path, capsys
) -> None:
    _git(tagged_main, "commit", "-q", "--allow-empty", "-m", "docs: later")

    assert release.main(["push"], root=tagged_main) == 1

    assert "HEAD is not origin/main" in capsys.readouterr().out
    assert _origin_tags(tagged_main) == set()


def test_git_finds_the_project_environment_first(tmp_path: Path) -> None:
    """The hooks of git switch and commit find pre-commit in .venv."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)

    path = release._git_env(tmp_path)["PATH"]

    assert path.split(os.pathsep)[0] == str(tmp_path / ".venv" / "bin")
