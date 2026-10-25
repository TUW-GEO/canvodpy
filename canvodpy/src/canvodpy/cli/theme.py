"""canVODpy's colours in the terminal: help, messages, progress and logs.

Three rules, so that every colour has one meaning:

1. **Structure in the brand's greens, by lightness.** The ramp of
   ``cli/dashboards/canvod_nordic.css`` gives three steps: *primary*
   (``--g1``, the logo's colour; ``--g5`` on a light background) for
   commands, headings, names and values; *secondary* (``--gray-8`` /
   ``--gray-9``) for descriptions, defaults and units; *frame*
   (``--gray-11`` / ``--gray-7``) for borders. Within a step, the kind of
   text shows by weight and style, not by another colour: bold for
   commands and headings, italic for paths and value types, underline for
   links, dim for defaults.
2. **Status in three added hues, nothing else.** The brand has no status
   colours (its "error" is a red), so three are added, used only for
   status and always with their symbol: *ok* blue (✓), *warning* amber
   (⚠️, ⊘), *error* orange (❌). They lie on the blue-yellow axis, which
   red-green colour blindness keeps, at one OKLCH chroma (0.13 dark, 0.10
   light), so they read as one set beside the muted greens. No red.
3. **Every pair stays apart.** The lightness of each status colour is
   chosen so that the closest pair of all five (structure and status)
   stays apart in CIELAB as seen with protanopia and deuteranopia (Machado
   et al. 2009), and every text colour has 4.5:1 contrast to a black
   (dark) or white (light) background; the frame is lighter on purpose.

The colours are named roles of a Rich theme (``canvod.ok``,
``canvod.warning``, ...), which the commands use in their markup; the
same roles set Typer's help styles (``typer.rich_utils.STYLE_*``), Rich's
styles that the CLI shows (progress bars, prompts, highlighting) and the
colours of the log in the terminal (structlog's console renderer).

:func:`apply_colors` picks the set for the terminal's background
(:func:`canvodpy.cli.banner.terminal_theme`); only ``canvodpy``'s entry
point calls it, so Rich's own styles change only in the CLI. Importing
this module installs just the ``canvod.*`` roles (dark set), so the
commands' markup always works, also outside a terminal, where Rich leaves
colours out anyway.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import rich
from rich.theme import Theme as RichTheme

from canvodpy.cli.banner import Theme, terminal_theme

#: The Nordic Green palette of canvod_nordic.css.
G1, G2, G3, G4, G5 = "#E1E6B9", "#C4D7A4", "#ABC8A4", "#375D3B", "#183128"

#: The ramp of canvod_nordic.css: --gray-7, --gray-8, --gray-9, --gray-11.
GRAY7, GRAY8, GRAY9, GRAY11 = "#96B07A", "#7D9568", "#5A7A4A", "#375D3B"


@dataclass(frozen=True)
class Palette:
    """The colours of one background.

    Attributes
    ----------
    primary : str
        Commands, headings, names, values, paths, links.
    secondary : str
        Descriptions, defaults, units, the "off" form of a flag.
    frame : str
        Borders, the empty part of a progress bar.
    ok : str
        Done, valid, written (with ✓).
    warning : str
        Needs attention, skipped, not set, required (with ⚠️ or ⊘).
    error : str
        Failed, invalid, refused (with ❌).
    """

    primary: str
    secondary: str
    frame: str
    ok: str
    warning: str
    error: str


#: Status hues (OKLCH): ok 230, warning 95, error 65.
PALETTES: dict[Theme, Palette] = {
    "dark": Palette(
        primary=G1,
        secondary=GRAY8,
        frame=GRAY11,
        ok="#0AA0D2",  # L 0.66, C 0.13
        warning="#F9DD73",  # L 0.90, C 0.13
        error="#C87F2C",  # L 0.66, C 0.13
    ),
    "light": Palette(
        primary=G5,
        secondary=GRAY9,
        frame=GRAY7,
        ok="#0E7397",  # L 0.52, C 0.10
        warning="#89691B",  # L 0.54, C 0.10
        error="#662703",  # L 0.36, C 0.10
    ),
}


def help_styles(p: Palette) -> dict[str, str]:
    """Typer's help styles, by what Typer uses each for."""
    return {
        # commands, options and the usage line (Typer: cyan, green, yellow)
        "STYLE_OPTION": f"bold {p.primary}",
        "STYLE_SWITCH": f"bold {p.primary}",
        "STYLE_COMMANDS_TABLE_FIRST_COLUMN": f"bold {p.primary}",
        "STYLE_USAGE": p.primary,
        "STYLE_USAGE_COMMAND": f"bold {p.primary}",
        # the "off" form of a flag, --no-... (Typer: magenta, red): quieter
        "STYLE_NEGATIVE_OPTION": f"bold {p.secondary}",
        "STYLE_NEGATIVE_SWITCH": f"bold {p.secondary}",
        # value types, TEXT, INTEGER, ... (Typer: bold yellow)
        "STYLE_TYPES": f"italic {p.secondary}",
        # descriptions, defaults and environment variables (Typer: dim)
        "STYLE_HELPTEXT_FIRST_LINE": p.secondary,
        "STYLE_HELPTEXT": p.secondary,
        "STYLE_OPTION_HELP": p.secondary,
        "STYLE_OPTION_DEFAULT": f"dim {p.secondary}",
        "STYLE_OPTION_ENVVAR": f"dim {p.secondary}",
        "STYLE_ERRORS_SUGGESTION": p.secondary,
        # needs attention: required, deprecated (Typer: red)
        "STYLE_REQUIRED_SHORT": p.warning,
        "STYLE_REQUIRED_LONG": f"dim {p.warning}",
        "STYLE_DEPRECATED": p.warning,
        # frames and errors (Typer: dim, red)
        "STYLE_OPTIONS_PANEL_BORDER": p.frame,
        "STYLE_COMMANDS_PANEL_BORDER": p.frame,
        "STYLE_ERRORS_PANEL_BORDER": p.error,
        "STYLE_ABORTED": f"bold {p.error}",
    }


def roles(p: Palette) -> dict[str, str]:
    """The roles of the commands' markup."""
    return {
        # status (rule 2)
        "canvod.ok": p.ok,
        "canvod.done": f"bold {p.ok}",
        "canvod.warning": p.warning,
        "canvod.error": f"bold {p.error}",
        "canvod.danger": f"bold reverse {p.error}",
        # structure (rule 1)
        "canvod.heading": f"bold {p.primary}",
        "canvod.name": p.primary,
        "canvod.text": p.secondary,
        "canvod.border": p.frame,
    }


def rich_styles(p: Palette) -> dict[str, str]:
    """The roles, and Rich's styles the CLI shows."""
    return {
        **roles(p),
        # progress bars (Rich: pink-red running, green finished)
        "progress.description": f"bold {p.primary}",
        "bar.back": p.frame,
        "bar.complete": p.primary,
        "bar.finished": p.ok,
        "bar.pulse": p.primary,
        "progress.spinner": p.primary,
        "status.spinner": p.primary,
        "progress.percentage": p.primary,
        "progress.elapsed": p.secondary,
        "progress.remaining": p.secondary,
        "progress.download": p.secondary,
        "progress.filesize": p.secondary,
        "progress.filesize.total": p.secondary,
        "progress.data.speed": p.secondary,
        # prompts of `config init` (Rich: magenta, cyan, red)
        "prompt.choices": f"bold {p.primary}",
        "prompt.default": f"bold {p.secondary}",
        "prompt.invalid": p.error,
        "prompt.invalid.choice": p.error,
        # highlighting in printed text (Rich: cyan, green, magenta, red)
        "repr.number": f"not italic {p.primary}",
        "repr.number_complex": f"not italic {p.primary}",
        "repr.str": f"not bold not italic {p.primary}",
        "repr.path": f"italic {p.primary}",
        "repr.filename": f"italic {p.primary}",
        "repr.url": f"not bold not italic underline {p.primary}",
        "repr.bool_true": f"italic {p.primary}",
        "repr.bool_false": f"italic {p.primary}",
        "repr.none": f"italic {p.secondary}",
        "repr.ellipsis": p.secondary,
        "repr.indent": f"dim {p.secondary}",
        "repr.error": f"bold {p.error}",
        "repr.call": f"bold {p.primary}",
        "repr.tag_name": f"bold {p.primary}",
        "repr.attrib_name": f"not italic {p.secondary}",
        "repr.attrib_value": f"not italic {p.primary}",
        "repr.ipv4": p.primary,
        "repr.ipv6": p.primary,
        "repr.eui48": p.primary,
        "repr.eui64": p.primary,
        "repr.uuid": f"not bold {p.primary}",
        "rule.line": p.frame,
        "log.time": f"dim {p.secondary}",
    }


def _ansi(color: str, *, bold: bool = False) -> str:
    """The escape code of a truecolor foreground."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return ("\x1b[1m" if bold else "") + f"\x1b[38;2;{r};{g};{b}m"


def log_level_styles(p: Palette) -> dict[str, str]:
    """structlog's level colours (structlog: red, yellow, green)."""
    error = _ansi(p.error, bold=True)
    return {
        "critical": error,
        "exception": error,
        "error": error,
        "warn": _ansi(p.warning),
        "warning": _ansi(p.warning),
        "info": _ansi(p.ok),
        "debug": _ansi(p.secondary),
        "notset": _ansi(p.secondary),
    }


def log_column_styles(p: Palette):
    """structlog's other colours: keys and values (structlog: cyan, magenta)."""
    from structlog.dev import ColumnStyles

    return ColumnStyles(
        reset="\x1b[0m",
        bright="\x1b[1m",
        level_critical=_ansi(p.error, bold=True),
        level_exception=_ansi(p.error, bold=True),
        level_error=_ansi(p.error, bold=True),
        level_warn=_ansi(p.warning),
        level_info=_ansi(p.ok),
        level_debug=_ansi(p.secondary),
        level_notset=_ansi(p.secondary),
        timestamp="\x1b[2m",
        logger_name=_ansi(p.primary),
        kv_key=_ansi(p.secondary),
        kv_value=_ansi(p.primary),
    )


#: Typer's help styles by background (kept by name for the tests).
HELP_STYLES: dict[Theme, dict[str, str]] = {
    theme: help_styles(p) for theme, p in PALETTES.items()
}

#: The console every command prints to: Rich's global console, which the
#: progress bars of the run use as well.
console = rich.get_console()
console.push_theme(RichTheme(roles(PALETTES["dark"])))

#: The theme :func:`apply_colors` pushed, and for which background.
_applied: tuple[Theme, RichTheme] | None = None


def apply_colors(theme: Theme | None = None) -> bool:
    """Set the colours for the terminal's background; ``True`` if set.

    Sets Typer's help styles, the theme of :data:`console` and the colours
    of the log in the terminal. Called again for the same background, it
    changes nothing; for the other one, it takes its theme off the console
    only while the console still shows that theme's styles, so a theme
    pushed since that changes any of them stays.

    Parameters
    ----------
    theme : {"dark", "light"}, optional
        The terminal's background; detected if not given. Without a
        given theme, nothing changes outside an interactive terminal.
    """
    if theme is None:
        if not sys.stdout.isatty():
            return False
        theme = terminal_theme()
    global _applied
    from typer import rich_utils

    from canvodpy.logging.logging_config import set_console_colors

    palette = PALETTES[theme]
    for name, style in HELP_STYLES[theme].items():
        setattr(rich_utils, name, style)
    if _applied is None or _applied[0] != theme:
        if _applied is not None and _top_theme_is(_applied[1]):
            console.pop_theme()
        rich_theme = RichTheme(rich_styles(palette))
        console.push_theme(rich_theme)
        _applied = (theme, rich_theme)
    set_console_colors(log_column_styles(palette), log_level_styles(palette))
    return True


def _top_theme_is(rich_theme: RichTheme) -> bool:
    """Whether the console still shows the styles of ``rich_theme``.

    Rich has no public view of its theme stack, so the styles are compared.
    """
    return all(
        console.get_style(name) == style for name, style in rich_theme.styles.items()
    )
