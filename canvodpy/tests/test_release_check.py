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
class FakeRemote(release.Remote):
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
    _write(root, "CITATION.cff", "version: 1.0.0\ndate-released: '2026-10-01'\n")
    _write(
        root, ".zenodo.json", '{"version": "1.0.0", "publication_date": "2026-10-01"}\n'
    )
    _write(
        root, "codemeta.json", '{"version": "1.0.0", "datePublished": "2026-10-01"}\n'
    )
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
    _git(root, "add", "CHANGELOG.md", ".gitmodules", "CITATION.cff")
    _git(root, "add", ".zenodo.json", "codemeta.json")
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
    assert _line(out, "⚠", "CI is not checked: HEAD is not main.")


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
    assert _line(out, "✗", "docs/whats-new.md on HEAD does not link the notebook")
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
    _merge(repo, "feat/102-overlay", 103, "feat(viz): overlay recipes")
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out
    assert _line(out, "⚠", "#103 feat/102-overlay")


def test_a_version_that_is_no_version_is_refused(repo: Repo, capsys) -> None:
    code, out = repo.check("v1.1.0", capsys)
    assert code == 2
    assert "not a version" in out


def test_a_release_notebook_missing_from_the_readme_fails(repo: Repo, capsys) -> None:
    _write(repo.root, "release-notes/README.md", "| Release | Open |\n|---|---|\n")
    repo.commit("docs(release-notes): readme")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "release-notes/README.md on HEAD does not link the notebook")


def test_a_link_only_in_the_working_tree_is_not_on_head(repo: Repo, capsys) -> None:
    _write(repo.root, "docs/whats-new.md", "# What's new in v1.0.0\n")
    repo.commit("docs: whats-new")
    _write(repo.root, "docs/whats-new.md", "release-notes/v1.1.0.py\n")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "docs/whats-new.md on HEAD does not link the notebook")


def test_a_version_not_above_the_current_one_fails(repo: Repo, capsys) -> None:
    code, out = repo.check("1.0.0", capsys)
    assert code == 1
    assert _line(out, "✗", "canvodpy: 1.0.0 is not above the current 1.0.0")


def test_a_version_tagged_already_fails(repo: Repo, capsys) -> None:
    _git(repo.root, "tag", "v1.1.0")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "tag v1.1.0 exists already")


def test_a_missing_citation_field_fails_as_in_just_release(repo: Repo, capsys) -> None:
    _write(repo.root, "codemeta.json", '{"datePublished": "2026-10-01"}\n')
    repo.commit("chore: codemeta")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "codemeta.json has no field matching")


def test_a_demo_submodule_that_is_not_checked_out_fails(repo: Repo, capsys) -> None:
    sha = "f" * 40
    repo.set_pointer("demo", sha)
    repo.remote.mains[DEMO_URL] = sha
    # Commit the index as it is: `git add -A` would record the checked-out commit.
    _git(
        repo.root, "commit", "-q", "-m", "chore(demo): pointer to a commit not fetched"
    )
    head = _git(repo.root, "rev-parse", "HEAD")
    repo.remote.mains[CANVODPY_URL] = head
    repo.remote.checks[head] = "success"
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "git submodule update --init demo"), out


def test_without_an_earlier_release_the_history_checks_warn(repo: Repo, capsys) -> None:
    _git(repo.root, "tag", "-d", "v1.0.0")
    _, out = repo.check("1.1.0", capsys)
    assert _line(out, "⚠", "No earlier release tag: the increment is not checked")
    assert _line(out, "⚠", "No earlier release tag: the demo headers are not checked")


def test_a_breaking_change_footer_calls_for_a_major(repo: Repo, capsys) -> None:
    repo.commit(
        "refactor(store): new layout\n\nBREAKING CHANGE: stores need a migration"
    )
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "call for a major: ")


def test_a_deprecation_mentioned_in_the_docs_calls_for_no_minor(
    repo: Repo, capsys
) -> None:
    _release_v110(repo)
    repo.commit("docs(functional): the deprecated *_to_file functions write a pickle")
    code, out = repo.check("1.1.1", capsys)
    assert _line(out, "✓", "the commits since v1.1.0 call for a patch")


def test_a_demo_pin_written_shorter_is_the_same_version(repo: Repo, capsys) -> None:
    _demo_commit(
        repo, {"03_grids.py": notebook(["canvodpy==1.0", "canvod-store==1.0.0"])}
    )
    code, out = repo.check("1.1.0", capsys)
    assert code == 0, out


def test_a_demo_notebook_with_a_broken_header_fails(repo: Repo, capsys) -> None:
    broken = notebook(["canvodpy==1.0.0"]).replace("# ]\n", "")
    _demo_commit(repo, {"03_grids.py": broken})
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "03_grids.py has an unreadable script header")


def _merge(repo: Repo, branch: str, number: int, subject: str) -> None:
    _git(repo.root, "switch", "-q", "-c", branch)
    _commit(repo.root, subject)
    _git(repo.root, "switch", "-q", "main")
    _git(
        repo.root,
        "merge",
        "-q",
        "--no-ff",
        branch,
        "-m",
        f"Merge pull request #{number} from TUW-GEO/{branch}",
    )
    head = _git(repo.root, "rev-parse", "HEAD")
    repo.remote.mains[CANVODPY_URL] = head
    repo.remote.checks[head] = "success"


def test_a_deprecation_pull_request_is_listed(repo: Repo, capsys) -> None:
    _merge(
        repo,
        "refactor/529-sensor",
        104,
        "refactor(airflow): deprecate check_sp3_availability",
    )
    _, out = repo.check("1.1.0", capsys)
    assert _line(out, "⚠", "#104 refactor/529-sensor")


def test_a_documentation_pull_request_is_not_listed(repo: Repo, capsys) -> None:
    _merge(repo, "docs/105-typos", 105, "docs: fix typos")
    _, out = repo.check("1.1.0", capsys)
    assert "#105" not in out


def test_a_squashed_pull_request_is_listed(repo: Repo, capsys, monkeypatch) -> None:
    monkeypatch.setenv("GIT_COMMITTER_NAME", "GitHub")
    repo.commit("fix(readers): keep truncated records (#106)")
    _, out = repo.check("1.1.0", capsys)
    assert _line(out, "⚠", "#106 fix(readers): keep truncated records")


def test_an_issue_number_in_a_local_commit_is_not_a_pull_request(
    repo: Repo, capsys
) -> None:
    repo.commit("fix(readers): keep truncated records (#433)")
    repo.commit("fix(readers): and the last one (#433)")
    _, out = repo.check("1.1.0", capsys)
    assert "#433" not in out


def test_a_pull_request_is_listed_once(repo: Repo, capsys, monkeypatch) -> None:
    monkeypatch.setenv("GIT_COMMITTER_NAME", "GitHub")
    repo.commit("fix(store): one (#107)")
    repo.commit("fix(store): one (#107)")
    _, out = repo.check("1.1.0", capsys)
    assert out.count("#107 fix(store): one") == 1


def test_a_longer_number_in_the_notebook_does_not_name_a_pull_request(
    repo: Repo, capsys
) -> None:
    _merge(repo, "fix/61-short", 61, "fix(store): short")
    _write(
        repo.root,
        "release-notes/v1.1.0.py",
        notebook(["canvodpy==1.1.0"]) + "# Something else (#613)\n",
    )
    repo.commit("docs(release-notes): name another pull request")
    _, out = repo.check("1.1.0", capsys)
    assert _line(out, "⚠", "#61 fix/61-short")


@pytest.mark.parametrize(
    "message",
    [
        "refactor(store): stop calling a deprecated icechunk API",
        "perf: avoid the deprecated path",
        "fix(cli): no BREAKING CHANGE for users",
    ],
)
def test_prose_about_deprecation_or_breaking_calls_for_a_patch(
    repo: Repo, capsys, message: str
) -> None:
    _release_v110(repo)
    repo.commit(message)
    _, out = repo.check("1.1.1", capsys)
    assert _line(out, "✓", "the commits since v1.1.0 call for a patch")


def test_a_release_tag_without_canvodpy_pins_fails(repo: Repo, capsys) -> None:
    pyproject = (repo.root / "canvodpy" / "pyproject.toml").read_text()
    (repo.root / "canvodpy" / "pyproject.toml").unlink()
    repo.commit("chore: no umbrella")
    _git(repo.root, "tag", "v1.0.1")
    _write(repo.root, "canvodpy/pyproject.toml", pyproject)
    repo.commit("chore: the umbrella again")
    code, out = repo.check("1.1.0", capsys)
    assert code == 1
    assert _line(out, "✗", "v1.0.1 has no readable canvodpy/pyproject.toml")


def test_a_pull_request_the_notebook_names_is_not_listed(repo: Repo, capsys) -> None:
    _merge(repo, "feat/100-broadcast", 100, "feat(store): broadcast ephemeris")
    _write(
        repo.root,
        "release-notes/v1.1.0.py",
        notebook(["canvodpy==1.1.0"]) + "# Broadcast ephemeris (#100)\n",
    )
    repo.commit("docs(release-notes): name the pull request")
    _, out = repo.check("1.1.0", capsys)
    assert _line(out, "✓", "The notebook names every notable pull request")


def test_an_origin_outside_github_stops_with_a_reason(repo: Repo) -> None:
    _git(repo.root, "remote", "set-url", "origin", "https://example.org/canvodpy.git")
    with pytest.raises(SystemExit, match="not a GitHub repository"):
        release.main(["check", "1.1.0"], root=repo.root)
