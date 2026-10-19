"""Write the settings reference page from the descriptions on the models.

The page lists every setting of ``canvod-settings.yaml`` with its
description, type, limits and default, so it can't drift from the code.
``canvodpy config explain`` prints the same text, and the settings
template links each setting to its entry here.

Usage: ``python scripts/settings_docs.py`` writes ``docs/guides/settings.md``;
``python scripts/settings_docs.py --check`` exits non-zero if that page
differs from what the code would write.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from canvod.config.settings_help import SettingHelp, all_settings

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "guides" / "settings.md"

HEADER = """\
---
title: Settings reference
description: Every setting of canvod-settings.yaml, with its description, type and default.
---

<!-- Written by scripts/settings_docs.py from the descriptions on the
     settings models. Don't edit this page: change the descriptions in
     packages/canvod-config and run `just settings-docs`. -->

# Settings reference

Every setting of `canvod-settings.yaml`, in the order of the file. For how
the file is found and checked, see the [Configuration guide](configuration.md).

A name in angle brackets is a name you choose: `sites.<site>` is a site,
`<receiver>` a receiver and `<analysis>` a VOD analysis. `[]` marks a list:
each item has the settings listed under it. To print a setting's entry in
the terminal, run `canvodpy config explain SETTING`, for example
`canvodpy config explain gnss_store.epoch`.
"""


# A value in single quotes, 'skip', and a name with an underscore or a dot,
# store_radial_distance or sites.<name>.store_description, are code.
_QUOTED = re.compile(r"(?<![\w`])'([^'\s][^']*?)'(?![\w])")
# The part after the first dot or underscore takes each dot together with
# the character after it, so no string can be split two ways (no
# exponential backtracking).
_NAME = re.compile(
    r"(?<![\w`.<])([A-Za-z<][\w<>]*[._][\w<>{}](?:\.?[\w<>{}])*)(?![\w`])"
)


def _prose(text: str) -> str:
    """The description as Markdown: values and names as code."""
    parts = re.split(r"(`[^`]*`)", _QUOTED.sub(r"`\1`", text))
    for index in range(0, len(parts), 2):  # outside the code spans
        parts[index] = _NAME.sub(r"`\1`", parts[index])
    joined = "".join(parts)
    # A name in angle brackets outside code would read as an HTML tag.
    parts = re.split(r"(`[^`]*`)", joined)
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("<", "&lt;").replace(">", "&gt;")
    return "".join(parts)


def _entry(setting: SettingHelp) -> str:
    if "." not in setting.path:
        depth = 2
    else:
        depth = 3 if setting.section else 4
    lines = [f"{'#' * depth} `{setting.path}` {{#{setting.anchor}}}", ""]
    lines += [_prose(setting.description), ""]
    if not setting.section:
        kind = re.sub(r'"([^"]*)"', r"`\1`", setting.kind)
        lines.append(f"- Type: {kind}")
        if setting.limits:
            lines.append(f"- Limits: {', '.join(setting.limits)}")
        default = (
            "none, you have to set it"
            if setting.default is None
            else f"`{setting.default}`"
        )
        lines.append(f"- Default: {default}")
        lines.append("")
    return "\n".join(lines)


def render() -> str:
    """Return the reference page as Markdown."""
    return HEADER + "\n" + "\n".join(_entry(s) for s in all_settings())


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        if not PAGE.exists() or PAGE.read_text() != text:
            print(
                f"{PAGE.relative_to(ROOT)} is out of date: run `just settings-docs`.",
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
