"""CI skips the expensive jobs only for a pull request that changes docs only (#633).

The classifier takes the files a pull request changes and says whether
CI runs everything. Anything it doesn't know runs everything, so a gap
in the docs-only list costs time, never a skipped test.
"""

import importlib.util
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


def test_outputs_for_github(tmp_path):
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    script.write_outputs(
        script.classify(["docs/index.md", "Justfile"]), output, summary
    )
    assert output.read_text() == "full=true\n"
    assert "Justfile" in summary.read_text()
