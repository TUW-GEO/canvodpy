"""Say which CI jobs a pull request needs, from the files it changes (#632).

A pull request whose changed files are all docs skips the expensive jobs
(the platform tests, the type check, the package build, and the
package-import check). Any other file, this script and the workflows
included, runs everything, so a file nobody classified never skips a
test. An empty list runs everything too. ADR 0024 records the decision.

The changed files are those between the pull request head and its merge
base with the target branch, so commits merged in from ``main`` don't
count. The script uses only the standard library: the ``changes`` job
runs it with the runner's Python, without installing the project.

Usage (the ``changes`` job of ``.github/workflows/ci.yml``)::

    python3 scripts/ci_changes.py BASE_SHA HEAD_SHA

It writes ``full=true`` or ``full=false`` to ``$GITHUB_OUTPUT`` and the
files that need the full run to ``$GITHUB_STEP_SUMMARY``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Folders whose files are docs: the docs pages, the release notebooks,
#: the templates of the docs site and the Vale styles.
DOCS_FOLDERS = ("docs/", "release-notes/", "overrides/", ".vale/")

#: Single files that are docs: the docs site and the Vale configuration.
DOCS_FILES = ("zensical.toml", ".vale.ini")


@dataclass(frozen=True)
class Changes:
    """What a pull request's changed files ask of CI."""

    #: Run every job; False only when every changed file is docs.
    full: bool
    #: The changed files that are not docs, the reason for a full run.
    not_docs: tuple[str, ...]


def is_docs(path: str) -> bool:
    """A Markdown file anywhere, or a file of the docs folders and files."""
    return path.endswith(".md") or path.startswith(DOCS_FOLDERS) or path in DOCS_FILES


def classify(paths: list[str]) -> Changes:
    """The CI a pull request needs; no changed files means the full run."""
    not_docs = tuple(path for path in paths if not is_docs(path))
    return Changes(full=bool(not_docs) or not paths, not_docs=not_docs)


def changed_files(base: str, head: str, cwd: Path | None = None) -> list[str]:
    """The files that differ between ``head`` and its merge base with ``base``.

    A moved file counts with both paths (``--no-renames``): code moved into
    the docs folder is code removed.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def write_outputs(changes: Changes, output: Path, summary: Path) -> None:
    """Hand the result to the other jobs, and say why on the run page."""
    with output.open("a") as file:
        file.write(f"full={'true' if changes.full else 'false'}\n")
    if not changes.full:
        text = "Docs-only pull request: the platform tests, type check, package build, and package-import check are skipped.\n"
    elif changes.not_docs:
        listed = "\n".join(f"- `{path}`" for path in changes.not_docs)
        text = f"Full CI: these changed files are not docs.\n\n{listed}\n"
    else:
        text = "Full CI: no changed files found.\n"
    with summary.open("a") as file:
        file.write(text)


def main(argv: list[str]) -> int:
    base, head = argv
    changes = classify(changed_files(base, head))
    write_outputs(
        changes,
        Path(os.environ["GITHUB_OUTPUT"]),
        Path(os.environ["GITHUB_STEP_SUMMARY"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
