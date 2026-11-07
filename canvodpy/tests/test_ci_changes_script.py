"""CI skips the expensive jobs only for a pull request that changes docs only (#633).

The classifier takes the files a pull request changes and says whether
CI runs everything. Anything it doesn't know runs everything, so a gap
in the docs-only list costs time, never a skipped test.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "ci_changes", ROOT / "scripts" / "ci_changes.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


@pytest.mark.parametrize(
    ("paths", "full"),
    [
        (["docs/guides/configuration.md"], False),
        (["docs/guides/configuration.md", "docs/assets/logo.svg"], False),
        (["AGENTS.md"], False),
        (["packages/canvod-store/AGENTS.md", "README.md"], False),
        ([".claude/skills/release/SKILL.md"], False),
        (["release-notes/v1.1.0.py"], False),
        (["zensical.toml", "overrides/main.html"], False),
        ([".vale.ini", ".vale/styles/config/vocabularies/canvodpy/accept.txt"], False),
        (
            [
                "docs/guides/configuration.md",
                "packages/canvod-readers/src/canvod/readers/base.py",
            ],
            True,
        ),
        (["Justfile"], True),
        (["some-new-file.txt"], True),
        ([], True),
        (["scripts/ci_changes.py"], True),
        ([".github/workflows/ci.yml"], True),
        (["uv.lock"], True),
        (["packages/canvod-store/pyproject.toml"], True),
    ],
)
def test_full_ci_unless_every_file_is_docs(paths, full):
    assert script.classify(paths).full is full


@pytest.mark.parametrize(
    ("paths", "full", "s3"),
    [
        (["packages/canvod-store/src/canvod/store/store.py"], True, True),
        (
            ["packages/canvod-store-metadata/src/canvod/store_metadata/io.py"],
            True,
            True,
        ),
        (["canvodpy/src/canvodpy/cli/store.py"], True, True),
        (["canvodpy/src/canvodpy/cli/config.py"], True, True),
        (["canvodpy/tests/test_s3_maintenance_cli.py"], True, True),
        (["canvodpy/tests/test_config_from_store_s3.py"], True, True),
        (["uv.lock"], True, True),
        ([".github/workflows/test_s3.yml"], True, True),
        (["scripts/ci_changes.py"], True, True),
        (["packages/canvod-store/AGENTS.md"], False, False),
        (["docs/guides/configuration.md"], False, False),
        (["packages/canvod-readers/src/canvod/readers/base.py"], True, False),
        (["canvodpy/src/canvodpy/cli/run.py"], True, False),
        ([], True, True),
    ],
)
def test_s3_tests_only_for_store_changes(paths, full, s3):
    changes = script.classify(paths)
    assert (changes.full, changes.s3) == (full, s3)


def test_outputs_for_github(tmp_path):
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    script.write_outputs(
        script.classify(["docs/index.md", "Justfile"]), output, summary
    )
    assert output.read_text() == "full=true\ns3=false\n"
    assert "Justfile" in summary.read_text()


def test_a_moved_file_counts_with_its_old_path(tmp_path):
    """Moving code into the docs folder removes code: the full run."""

    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.org")
    git("config", "user.name", "test")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gen.py").write_text("print('the same content')\n" * 20)
    git("add", ".")
    git("commit", "-q", "-m", "base")
    (tmp_path / "docs").mkdir()
    git("mv", "scripts/gen.py", "docs/gen.py")
    git("commit", "-q", "-m", "move")

    paths = script.changed_files("HEAD~1", "HEAD", cwd=tmp_path)
    assert sorted(paths) == ["docs/gen.py", "scripts/gen.py"]
    assert script.classify(paths).full is True
