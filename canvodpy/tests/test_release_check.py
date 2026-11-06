"""``release.py check`` says whether the repository is ready for a release.

It reads the repository and its two submodules (the demo notebooks and the
test data) and asks a remote for what only GitHub knows: the newest commit
of each ``main`` and the state of CI. It writes nothing. Each check prints
one line (✓ pass, ✗ fail, ⚠ warning); any ✗ makes it exit 1.

The tests build a small repository in a temporary folder: canvodpy 1.0.0,
released and tagged, pinning canvod-store 1.0.0, with a demo submodule of two
notebooks and a test-data submodule, followed by one feature commit and the
release notebook of v1.1.0. A fake remote answers for GitHub.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from test_release_citation import release

CANVODPY_URL = "https://github.com/TUW-GEO/canvodpy.git"
DEMO_URL = "https://github.com/TUW-GEO/canvodpy-demo.git"
TEST_DATA_URL = "https://github.com/TUW-GEO/canvodpy-test-data.git"
TEST_DATA_PATH = "packages/canvod-readers/tests/test_data"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=JRRT", "-c", "user.email=jrrt@fangorn.example", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def notebook(pins: list[str]) -> str:
    """A marimo notebook whose script header pins ``pins``."""
    lines = "\n".join(f'#   "{pin}",' for pin in [*pins, "marimo>=0.23.9"])
    return (
        "# /// script\n"
        '# requires-python = ">=3.14"\n'
        "# dependencies = [\n"
        f"{lines}\n"
        "# ]\n"
        "# ///\n\n"
        "import marimo\n\n"
        "app = marimo.App()\n"
    )


@dataclass
class FakeRemote:
    """GitHub as the tests see it: each repository's main, tags and CI."""

    mains: dict[str, str] = field(default_factory=dict)
    tags: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)

    def main_head(self, url: str) -> str | None:
        return self.mains.get(url)

    def tags_at(self, url: str, sha: str) -> list[str]:
        return self.tags.get(url, {}).get(sha, [])

    def ci(self, sha: str) -> str:
        return self.checks.get(sha, "none")


@dataclass
class Repo:
    root: Path
    demo: Path
    test_data: Path
    remote: FakeRemote

    def check(self, version: str, capsys) -> tuple[int, str]:
        code = release.main(["check", version], root=self.root, remote=self.remote)
        return code, capsys.readouterr().out

    def commit(self, message: str) -> str:
        """Commit in canvodpy and make it the remote main, with CI passed."""
        sha = _commit(self.root, message)
        self.remote.mains[CANVODPY_URL] = sha
        self.remote.checks[sha] = "success"
        return sha

    def set_pointer(self, path: str, sha: str) -> None:
        _git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")


def _submodule(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    origin = tmp_path / name
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    for path, text in files.items():
        _write(origin, path, text)
    _commit(origin, "init")
    return origin


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    v100 = ["canvodpy==1.0.0", "canvod-store==1.0.0"]
    demo_origin = _submodule(
        tmp_path,
        "demo-origin",
        {
            "01_reading.py": notebook(v100),
            "02_store.py": notebook([*v100, "numpy==2.5.4"]),
            "scripts/helper.py": "print('not a notebook')\n",
        },
    )
    data_origin = _submodule(tmp_path, "data-origin", {"README.md": "test data\n"})

    root = tmp_path / "canvodpy"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", CANVODPY_URL)
    _write(root, "pyproject.toml", '[project]\nname = "canvodpy-workspace"\n')
    _write(
        root,
        "canvodpy/pyproject.toml",
        '[project]\nname = "canvodpy"\nversion = "1.0.0"\n'
        'dependencies = ["canvod-store==1.0.0"]\n',
    )
    _write(
        root,
        "packages/canvod-store/pyproject.toml",
        '[project]\nname = "canvod-store"\nversion = "1.0.0"\n',
    )
    _write(root, "CHANGELOG.md", "# Changelog\n")
    _write(
        root,
        ".gitmodules",
        f'[submodule "demo"]\n\tpath = demo\n\turl = {DEMO_URL}\n'
        f'[submodule "{TEST_DATA_PATH}"]\n\tpath = {TEST_DATA_PATH}\n'
        f"\turl = {TEST_DATA_URL}\n",
    )
    _git(tmp_path, "clone", "-q", str(demo_origin), str(root / "demo"))
    _git(tmp_path, "clone", "-q", str(data_origin), str(root / TEST_DATA_PATH))
    _git(
        root,
        "add",
        "pyproject.toml",
        "canvodpy",
        "packages/canvod-store/pyproject.toml",
    )
    _git(root, "add", "CHANGELOG.md", ".gitmodules")
    remote = FakeRemote()
    repo = Repo(root, root / "demo", root / TEST_DATA_PATH, remote)
    demo_sha = _git(repo.demo, "rev-parse", "HEAD")
    data_sha = _git(repo.test_data, "rev-parse", "HEAD")
    repo.set_pointer("demo", demo_sha)
    repo.set_pointer(TEST_DATA_PATH, data_sha)
    remote.mains[DEMO_URL] = demo_sha
    remote.mains[TEST_DATA_URL] = data_sha
    remote.tags[TEST_DATA_URL] = {data_sha: ["v0.3.0"]}
    _git(root, "commit", "-q", "-m", "bump: canvodpy 1.0.0")
    _git(root, "tag", "-a", "v1.0.0", "-m", "Release canvodpy 1.0.0")

    _write(root, "release-notes/v1.1.0.py", notebook(["canvodpy==1.1.0"]))
    _write(
        root,
        "release-notes/README.md",
        "| Release | Open |\n|---|---|\n| [v1.1.0](v1.1.0.py): broadcast | |\n",
    )
    _write(
        root,
        "docs/whats-new.md",
        "# What's new in v1.1.0\n\n"
        "[Release notebook](https://github.com/TUW-GEO/canvodpy/blob/main/release-notes/v1.1.0.py)\n",
    )
    repo.commit("feat(store): broadcast ephemeris (#100)")
    _git(
        root,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Merge pull request #101 from TUW-GEO/feat/100-broadcast",
    )
    repo.remote.mains[CANVODPY_URL] = _git(root, "rev-parse", "HEAD")
    repo.remote.checks[_git(root, "rev-parse", "HEAD")] = "success"
    return repo


def test_a_ready_repository_passes(repo: Repo, capsys) -> None:
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out
    assert "✗" not in out


def _line(out: str, status: str, needle: str) -> bool:
    return any(line.startswith(status) and needle in line for line in out.splitlines())


def test_a_demo_pointer_behind_its_main_fails(repo: Repo, capsys) -> None:
    repo.remote.mains[DEMO_URL] = "f" * 40
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "demo points at")


def test_a_test_data_pointer_behind_its_main_fails(repo: Repo, capsys) -> None:
    repo.remote.mains[TEST_DATA_URL] = "f" * 40
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", f"{TEST_DATA_PATH} points at")


def test_untagged_test_data_is_a_warning_only(repo: Repo, capsys) -> None:
    repo.remote.tags.clear()
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out
    assert _line(out, "⚠", "has no tag")


def _demo_commit(repo: Repo, files: dict[str, str]) -> None:
    """A new demo commit, recorded as canvodpy's pointer and the demo's main."""
    for path, text in files.items():
        _write(repo.demo, path, text)
    sha = _commit(repo.demo, "docs: change a notebook")
    repo.set_pointer("demo", sha)
    repo.remote.mains[DEMO_URL] = sha
    repo.commit("chore(demo): bump the pointer")


def test_a_demo_notebook_without_a_canvodpy_pin_fails(repo: Repo, capsys) -> None:
    _demo_commit(repo, {"03_grids.py": notebook(["canvod-store==1.0.0"])})
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "03_grids.py pins no canvodpy")


def test_a_demo_notebook_with_another_package_version_fails(repo: Repo, capsys) -> None:
    _demo_commit(
        repo, {"03_grids.py": notebook(["canvodpy==1.0.0", "canvod-store==0.9.0"])}
    )
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "03_grids.py pins canvod-store==0.9.0")


def test_demo_files_that_are_no_notebooks_are_not_checked(repo: Repo, capsys) -> None:
    _demo_commit(repo, {"build.py": "print('a helper script')\n"})
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out


def test_a_head_behind_main_fails(repo: Repo, capsys) -> None:
    repo.remote.mains[CANVODPY_URL] = "f" * 40
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "is not main on GitHub")


@pytest.mark.parametrize("state", ["pending", "failure", "none"])
def test_ci_that_has_not_passed_fails(repo: Repo, capsys, state: str) -> None:
    repo.remote.checks.clear()
    repo.remote.checks[repo.remote.mains[CANVODPY_URL]] = state
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "CI ")


def test_a_feature_released_as_a_patch_fails(repo: Repo, capsys) -> None:
    code, out = repo.check("1.0.1", capsys)
    assert code == 1
    assert _line(out, "✗", "call for a minor: ")
    assert "broadcast ephemeris" in out


def test_a_breaking_change_released_as_a_minor_fails(repo: Repo, capsys) -> None:
    repo.commit("feat(store)!: drop the old store layout")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "call for a major: ")


def _release_v110(repo: Repo) -> None:
    """Release and tag 1.1.0, so the next release counts from there."""
    _write(
        repo.root,
        "canvodpy/pyproject.toml",
        '[project]\nname = "canvodpy"\nversion = "1.1.0"\n'
        'dependencies = ["canvod-store==1.0.0"]\n',
    )
    repo.commit("bump: canvodpy 1.1.0")
    _git(repo.root, "tag", "-a", "v1.1.0", "-m", "Release canvodpy 1.1.0")


def test_a_deprecation_released_as_a_patch_fails(repo: Repo, capsys) -> None:
    _release_v110(repo)
    repo.commit("refactor(config): deprecate ephemeris source final, use precise")
    code, out = repo.check("1.1.1", capsys)
    assert code == 1
    assert _line(out, "✗", "call for a minor: ")


def test_a_patch_release_needs_no_notebook(repo: Repo, capsys) -> None:
    _release_v110(repo)
    repo.commit("fix(store): close the session")
    repo.commit("docs(store): mention the deprecated *_to_file functions")
    _, out = repo.check("1.1.1", capsys)
    assert _line(out, "✓", "patch release; the commits since v1.1.0 call for a patch")
    assert _line(out, "✓", "Patch release: no release notebook needed")
    assert "release-notes/v1.1.1.py" not in out


def test_a_missing_release_notebook_fails(repo: Repo, capsys) -> None:
    code, out = repo.check("1.2.0", capsys)
    assert code == 1
    assert _line(out, "✗", "release-notes/v1.2.0.py is not on HEAD")


def test_a_release_notebook_pinning_another_version_fails(repo: Repo, capsys) -> None:
    _write(repo.root, "release-notes/v1.1.0.py", notebook(["canvodpy==1.0.0"]))
    repo.commit("docs(release-notes): pin")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "pins canvodpy 1.0.0, not ==1.1.0")


def test_a_release_notebook_missing_from_whats_new_fails(repo: Repo, capsys) -> None:
    _write(repo.root, "docs/whats-new.md", "# What's new in v1.0.0\n")
    repo.commit("docs: whats-new")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "docs/whats-new.md does not link the notebook")
    assert _line(out, "✓", "release-notes/README.md links the notebook")


def test_an_uncommitted_release_file_fails(repo: Repo, capsys) -> None:
    (repo.root / "CHANGELOG.md").write_text("# Changelog\n\nedited\n")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "CHANGELOG.md")


def test_an_existing_release_branch_fails(repo: Repo, capsys) -> None:
    _git(repo.root, "branch", "release/v1.1.0")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "release/v1.1.0 exists already")


def test_a_feature_pull_request_the_notebook_does_not_name_warns(
    repo: Repo, capsys
) -> None:
    _git(repo.root, "switch", "-q", "-c", "feat/102-overlay")
    _commit(repo.root, "feat(viz): overlay recipes")
    _git(repo.root, "switch", "-q", "main")
    _git(
        repo.root,
        "merge",
        "-q",
        "--no-ff",
        "feat/102-overlay",
        "-m",
        "Merge pull request #103 from TUW-GEO/feat/102-overlay",
    )
    head = _git(repo.root, "rev-parse", "HEAD")
    repo.remote.mains[CANVODPY_URL] = head
    repo.remote.checks[head] = "success"
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out
    assert _line(out, "⚠", "#103 feat/102-overlay")


def test_a_version_that_is_no_version_is_refused(repo: Repo, capsys) -> None:
    code, out = repo.check("v1.1.0", capsys)
    assert code == 2
    assert "not a version" in out
