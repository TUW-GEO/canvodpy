"""canVODpy's colours in the terminal: help, messages, progress and logs."""

import colorsys
import itertools
import logging
import re
from pathlib import Path

import pytest
from canvodpy.cli import theme
from canvodpy.logging import logging_config
from rich.default_styles import DEFAULT_STYLES
from typer import rich_utils

CSS = Path(theme.__file__).parent / "dashboards" / "canvod_nordic.css"
PAGE = {"dark": "#000000", "light": "#FFFFFF"}
NAMED = re.compile(r"\b(bright_)?(red|green|yellow|blue|magenta|cyan)\b|rgb\(")


def test_palette_is_that_of_the_css():
    css = CSS.read_text(encoding="utf-8")
    palette = {
        k: v.upper() for k, v in re.findall(r"--(g[1-5]):\s*(#[0-9A-Fa-f]{6})", css)
    }
    assert [palette[f"g{i}"] for i in range(1, 6)] == [
        theme.G1,
        theme.G2,
        theme.G3,
        theme.G4,
        theme.G5,
    ]


def _linear(color: str) -> list[float]:
    def channel(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return [channel(int(color[i : i + 2], 16)) for i in (1, 3, 5)]


def _luminance(rgb: list[float]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(_linear(a)), _luminance(_linear(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


#: Red-green colour blindness, full severity (Machado, Oliveira and
#: Fernandes 2009), on linear RGB.
CVD = {
    "protan": [
        [0.152286, 1.052583, -0.204868],
        [0.114503, 0.786281, 0.099216],
        [-0.003882, -0.048116, 1.051998],
    ],
    "deutan": [
        [0.367322, 0.860646, -0.227968],
        [0.280085, 0.672501, 0.047413],
        [-0.011820, 0.042940, 0.968881],
    ],
}


def _lab(rgb: list[float]) -> tuple[float, float, float]:
    x = (0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]) / 0.95047
    y = _luminance(rgb)
    z = (0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _distance_seen(a: str, b: str, deficiency: str) -> float:
    """CIELAB distance of two colours as seen with *deficiency*."""

    def seen(color: str) -> list[float]:
        rgb = _linear(color)
        m = CVD[deficiency]
        return [
            min(1.0, max(0.0, sum(m[r][k] * rgb[k] for k in range(3))))
            for r in range(3)
        ]

    la, lb = _lab(seen(a)), _lab(seen(b))
    return sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)) ** 0.5


@pytest.mark.parametrize("background", ["dark", "light"])
def test_every_colour_is_readable(background):
    palette = theme.PALETTES[background]
    for role in ("primary", "secondary", "ok", "warning", "error"):
        assert _contrast(getattr(palette, role), PAGE[background]) >= 4.5, role


@pytest.mark.parametrize("background", ["dark", "light"])
def test_structure_steps_differ_in_brightness(background):
    """Rule 1: brightness, not hue, keeps primary and secondary apart."""
    palette = theme.PALETTES[background]
    assert _contrast(palette.primary, palette.secondary) >= 2.0


@pytest.mark.parametrize("background", ["dark", "light"])
def test_no_red(background):
    """No hue from magenta over red to red-orange, for red-green colour blindness."""
    for color in vars(theme.PALETTES[background]).values():
        rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        hue, _, saturation = colorsys.rgb_to_hls(*rgb)
        assert saturation < 0.25 or 20 <= hue * 360 <= 290, color


@pytest.mark.parametrize("deficiency", ["protan", "deutan"])
@pytest.mark.parametrize("background", ["dark", "light"])
def test_every_pair_stays_apart(background, deficiency):
    """Rule 3: structure and status colours, as seen with colour blindness."""
    p = theme.PALETTES[background]
    colours = (p.primary, p.secondary, p.ok, p.warning, p.error)
    for a, b in itertools.combinations(colours, 2):
        assert _distance_seen(a, b, deficiency) >= 20, (a, b)


@pytest.mark.parametrize("background", ["dark", "light"])
def test_status_colours_share_one_chroma(background):
    """Rule 2: the three added hues read as one set."""
    p = theme.PALETTES[background]
    chromas = [_oklch_chroma(c) for c in (p.ok, p.warning, p.error)]
    assert max(chromas) - min(chromas) < 0.01


def _oklch_chroma(color: str) -> float:
    r, g, b = _linear(color)
    lms = [
        (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3),
        (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3),
        (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3),
    ]
    a = 1.9779984951 * lms[0] - 2.4285922050 * lms[1] + 0.4505937099 * lms[2]
    b_ = 0.0259040371 * lms[0] + 0.7827717662 * lms[1] - 0.8086757660 * lms[2]
    return (a**2 + b_**2) ** 0.5


@pytest.mark.parametrize("background", ["dark", "light"])
def test_no_named_colours_left_in_the_styles(background):
    """Every style is the palette's: Rich's and Typer's names are all replaced."""
    palette = theme.PALETTES[background]
    styles = [
        *theme.help_styles(palette).values(),
        *theme.rich_styles(palette).values(),
    ]
    assert not [s for s in styles if NAMED.search(s)]


def test_rich_styles_the_cli_shows_are_all_replaced():
    """Progress bars, prompts and highlighting: no default colour left."""
    shown = ("progress.", "bar.", "prompt.", "repr.", "status.", "rule.", "log.time")
    left = [
        name
        for name, style in DEFAULT_STYLES.items()
        if name.startswith(shown) and NAMED.search(str(style))
    ]
    assert set(left) <= set(theme.rich_styles(theme.PALETTES["dark"]))


def test_typer_colours_are_all_replaced():
    """Every colour Typer gives its help has a style of the palette."""
    coloured = {
        name
        for name in dir(rich_utils)
        if name.startswith("STYLE_")
        and isinstance(getattr(rich_utils, name), str)
        and NAMED.search(getattr(rich_utils, name))
    }
    assert coloured <= set(theme.HELP_STYLES["dark"])


def test_every_role_in_the_markup_exists():
    cli = Path(theme.__file__).parent
    used = {
        role
        for path in cli.glob("*.py")
        for role in re.findall(r"\[/?(canvod\.[a-z]+)\]", path.read_text("utf-8"))
    }
    assert used
    assert used <= set(theme.rich_styles(theme.PALETTES["dark"]))


def test_both_backgrounds_set_the_same_styles():
    dark, light = theme.PALETTES["dark"], theme.PALETTES["light"]
    assert theme.help_styles(dark).keys() == theme.help_styles(light).keys()
    assert theme.rich_styles(dark).keys() == theme.rich_styles(light).keys()


@pytest.fixture
def restore_colors(monkeypatch):
    """Restore Typer's styles, the console's theme and the log's colours."""
    for name in theme.HELP_STYLES["dark"]:
        monkeypatch.setattr(rich_utils, name, getattr(rich_utils, name))
    monkeypatch.setattr(logging_config, "_console_colors", None)
    monkeypatch.setattr(theme, "_applied", None)
    depth = len(theme.console._theme_stack._entries)
    yield
    while len(theme.console._theme_stack._entries) > depth:
        theme.console.pop_theme()
    for handler in logging.getLogger().handlers:
        if handler.get_name() == logging_config._CONSOLE_HANDLER:
            handler.setFormatter(
                logging_config._console_formatter(logging_config._shared_processors())
            )


def _console_handler() -> logging.Handler:
    return next(
        h
        for h in logging.getLogger().handlers
        if h.get_name() == logging_config._CONSOLE_HANDLER
    )


def _warning_line() -> str:
    record = logging.LogRecord("canvodpy", logging.WARNING, "", 0, "x", None, None)
    return _console_handler().format(record)


@pytest.mark.parametrize("background", ["dark", "light"])
def test_apply_sets_typer_console_and_log(restore_colors, monkeypatch, background):
    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: True)
    palette = theme.PALETTES[background]
    assert theme.apply_colors(background) is True
    for name, style in theme.HELP_STYLES[background].items():
        assert getattr(rich_utils, name) == style
    ok = theme.console.get_style("canvod.ok").color
    assert ok.triplet.hex.upper() == palette.ok

    r, g, b = (int(palette.warning[i : i + 2], 16) for i in (1, 3, 5))
    assert f"\x1b[38;2;{r};{g};{b}m" in _warning_line()


def test_log_to_a_file_or_pipe_has_no_escape_codes(restore_colors, monkeypatch):
    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: False)
    theme.apply_colors("dark")
    assert "\x1b[" not in _warning_line()


def test_roles_exist_before_apply():
    """Commands run without :func:`apply_colors` (pipes, tests) still print."""
    assert theme.console.get_style("canvod.error")


def test_nothing_set_outside_a_terminal(restore_colors, monkeypatch):
    before = rich_utils.STYLE_OPTION
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert theme.apply_colors() is False
    assert rich_utils.STYLE_OPTION == before


def test_import_sets_only_the_roles(restore_colors):
    """Rich's own styles change only when the CLI applies its colours."""
    from rich.default_styles import DEFAULT_STYLES

    assert theme.console.get_style("bar.complete") == DEFAULT_STYLES["bar.complete"]


@pytest.mark.parametrize("second", ["dark", "light"])
def test_apply_twice_leaves_one_theme(restore_colors, monkeypatch, second):
    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: True)
    depth = len(theme.console._theme_stack._entries)
    theme.apply_colors("dark")
    theme.apply_colors(second)
    assert len(theme.console._theme_stack._entries) == depth + 1
    ok = theme.console.get_style("canvod.ok").color.triplet.hex.upper()
    assert ok == theme.PALETTES[second].ok


def test_apply_again_keeps_a_theme_pushed_since(restore_colors, monkeypatch):
    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: True)
    theme.apply_colors("dark")
    theme.console.push_theme(theme.RichTheme({"canvod.ok": "#123456"}))
    theme.apply_colors("light")
    theme.console.pop_theme()  # the light theme
    assert theme.console.get_style("canvod.ok").color.triplet.hex == "#123456"


def test_no_level_colours_where_structlog_has_none(restore_colors, monkeypatch):
    """Windows without colorama: no escape codes at all, not just in columns."""
    import structlog

    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: True)
    init = structlog.dev.ConsoleRenderer.__init__
    defaults = list(init.__defaults__)
    defaults[1] = False  # colors=_has_colors, read at import
    monkeypatch.setattr(init, "__defaults__", tuple(defaults))
    theme.apply_colors("dark")
    assert "\x1b[" not in _warning_line()


_COLOUR_NAMES = r"(?:bright_)?(?:red|green|yellow|blue|cyan|magenta|white|black)\d?"


def test_no_colour_names_in_the_cli():
    """The commands use the roles, so every colour follows the palette."""
    cli = Path(theme.__file__).parent
    pattern = re.compile(
        rf"\[/?(?:(?:bold|dim|italic|underline|reverse) )*{_COLOUR_NAMES}\b"
        rf"|style=\"(?:[a-z ]* )?{_COLOUR_NAMES}\b"
    )
    found = {
        path.name: pattern.findall(path.read_text("utf-8"))
        for path in cli.glob("*.py")
        if path.name != "theme.py"
    }
    assert {name: hits for name, hits in found.items() if hits} == {}


def test_no_colour_codes_in_the_log_with_no_color(restore_colors, monkeypatch):
    monkeypatch.setattr(logging_config, "_stdout_is_terminal", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    theme.apply_colors("dark")
    assert "\x1b[" not in _warning_line()
