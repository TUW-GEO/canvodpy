"""Write the command-line reference page from the ``canvodpy`` Typer app.

The page lists every command and option with the text of its ``--help``,
so it can't drift from the code. Typer's own generator (``typer ... utils
docs``) prints a command's whole docstring; Click's ``--help`` stops at a
``\\f`` line and drops the ``\\b`` markers that keep a paragraph unwrapped.
This script does the same before it calls Typer's generator, so the page
shows what ``--help`` shows.

Usage: ``python scripts/cli_docs.py`` writes ``docs/api/cli.md``;
``python scripts/cli_docs.py --check`` exits non-zero if that page differs
from what the code would write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from canvodpy.cli.app import main_app
from typer.cli import get_docs_for_click
from typer.core import TyperCommand, TyperGroup

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "api" / "cli.md"

HEADER = """\
---
title: Command line
description: Every canvodpy command and option, with the text of its --help.
---

<!-- Written by scripts/cli_docs.py from the canvodpy --help texts.
     Don't edit this page: change the help texts and run `just cli-docs`. -->

"""

INTRO = """\
The `canvodpy` command runs canVODpy from the command line. This page
lists every command and option, and `canvodpy COMMAND --help` prints the same
text in the terminal. For a walk through a first run, see
[Retrieve VOD](../users/index.md).

"""


def _trim_help(command: TyperCommand | TyperGroup) -> None:
    """Cut each help text the way ``--help`` shows it, for all commands."""
    if command.help:
        text = command.help.split("\f")[0]
        lines = [line for line in text.splitlines() if line.strip() != "\b"]
        command.help = "\n".join(lines).strip()
    if isinstance(command, TyperGroup):
        for sub in command.commands.values():
            if not isinstance(sub, TyperCommand | TyperGroup):
                raise TypeError(f"{sub.name} is not a Typer command")
            _trim_help(sub)


def render() -> str:
    """Return the reference page as Markdown."""
    command = typer.main.get_command(main_app)
    if not isinstance(command, TyperGroup):
        raise TypeError("canvodpy's main app is not a Typer group")
    _trim_help(command)
    ctx = typer.Context(command)
    body = get_docs_for_click(
        obj=command, ctx=ctx, name="canvodpy", title="Command line"
    )
    title, rest = body.strip().split("\n", 1)
    return HEADER + title + "\n\n" + INTRO + rest.lstrip("\n") + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        if not PAGE.exists() or PAGE.read_text() != text:
            print(
                f"{PAGE.relative_to(ROOT)} is out of date: run `just cli-docs`.",
                file=sys.stderr,
            )
            return 1
        print(f"{PAGE.relative_to(ROOT)} is up to date.")
        return 0
    PAGE.write_text(text)
    print(f"Wrote {PAGE.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
