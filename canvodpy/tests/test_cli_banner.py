"""The logo in the terminal: when it is shown, in which colour, and where."""

import io
import os
import termios
import time

import pytest
from canvodpy.cli import banner
from canvodpy.cli.app import main_app
from typer.testing import CliRunner


class _Terminal(io.StringIO):
    """A stdout that says whether it is a terminal."""

    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def plain_env(monkeypatch):
    for name in (
        "CANVODPY_NO_BANNER",
        "CANVODPY_TERMINAL_THEME",
        "COLORFGBG",
        "NO_COLOR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(banner, "_query_background", lambda: b"")
    banner.terminal_theme.cache_clear()
    yield
    banner.terminal_theme.cache_clear()


@pytest.fixture
def flights(monkeypatch):
    """Record the flight instead of playing it."""
    calls = []
    monkeypatch.setattr(banner, "_fly", lambda flight, color: calls.append(color))
    return calls


@pytest.fixture
def terminal(plain_env, monkeypatch):
    """Make stdout an interactive terminal of 100 x 50 with true colour.

    Call it in the test body: pytest replaces stdout after the fixtures.
    """

    def use() -> _Terminal:
        out = _Terminal(tty=True)
        monkeypatch.setattr("sys.stdout", out)
        return out

    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("LINES", "50")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("TERM", "xterm-256color")
    return use


def test_frames_fit_the_logo_width_in_block_characters():
    flight = banner.frames()
    assert len(flight) > 1
    assert banner.logo() == flight[-1]
    assert len({frame.count("\n") for frame in flight}) == 1  # same height
    for frame in flight:
        assert max(len(line) for line in frame.split("\n")) <= banner.LOGO_COLUMNS
        assert set(frame) <= set(" \n▘▝▀▖▌▞▛▗▚▐▜▄▙▟█")


def test_flight_redraws_in_place(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr(banner.time, "sleep", lambda _s: None)
    flight = banner.frames()
    rows = flight[0].count("\n") + 1
    banner._fly(flight, banner.LOGO_COLORS["dark"])
    text = out.getvalue()
    assert (
        text.count(f"\033[{rows}A") == len(flight) - 1
    )  # back up for each later frame
    assert text.startswith("\033[?25l") and text.endswith(
        "\033[?25h"
    )  # cursor hidden, then shown


@pytest.mark.parametrize(
    ("answer", "theme"),
    [
        (b"\033]11;rgb:0000/0000/0000\033\\", "dark"),
        (b"\033]11;rgb:ffff/ffff/ffff\033\\", "light"),
        (b"\033]11;rgb:28/2c/34\a", "dark"),
        (b"\033]11;rgb:fdf6/e3e3/c4c4\033\\", "light"),
        (b"", None),
        (b"garbage", None),
    ],
)
def test_theme_from_osc11(answer, theme):
    assert banner.theme_from_osc11(answer) == theme


@pytest.mark.parametrize(
    ("value", "theme"),
    [
        ("15;0", "dark"),
        ("0;15", "light"),
        ("0;7", "light"),
        ("15;default;0", "dark"),
        ("", None),
    ],
)
def test_theme_from_colorfgbg(value, theme):
    assert banner.theme_from_colorfgbg(value) == theme


def test_theme_setting_wins(plain_env, monkeypatch):
    monkeypatch.setenv("CANVODPY_TERMINAL_THEME", "light")
    monkeypatch.setattr(
        banner, "_query_background", lambda: b"\033]11;rgb:0000/0000/0000\033\\"
    )
    assert banner.terminal_theme() == "light"


def test_theme_falls_back_to_colorfgbg_then_dark(plain_env, monkeypatch):
    assert banner.terminal_theme() == "dark"
    banner.terminal_theme.cache_clear()
    monkeypatch.setenv("COLORFGBG", "0;15")
    assert banner.terminal_theme() == "light"


def test_theme_is_asked_once(plain_env, monkeypatch):
    asked = []
    monkeypatch.setattr(banner, "_query_background", lambda: asked.append(1) or b"")
    banner.terminal_theme()
    banner.terminal_theme()
    assert asked == [1]


def test_not_shown_outside_a_terminal(plain_env, flights, monkeypatch):
    out = _Terminal(tty=False)
    monkeypatch.setattr("sys.stdout", out)
    assert banner.show_banner() is False
    assert out.getvalue() == ""
    assert flights == []


def test_not_shown_when_switched_off(terminal, flights, monkeypatch):
    out = terminal()
    monkeypatch.setenv("CANVODPY_NO_BANNER", "1")
    assert banner.show_banner() is False
    assert out.getvalue() == ""
    assert flights == []


def test_not_shown_in_a_terminal_as_wide_as_the_logo(terminal, flights, monkeypatch):
    """Some terminals wrap a full line at once; the flight would smear."""
    out = terminal()
    monkeypatch.setenv("COLUMNS", str(banner.LOGO_COLUMNS))
    assert banner.show_banner() is False
    assert out.getvalue() == ""
    assert flights == []


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_flown_in_the_logo_colour(terminal, flights, monkeypatch, theme):
    terminal()
    monkeypatch.setenv("CANVODPY_TERMINAL_THEME", theme)
    assert banner.show_banner() is True
    assert flights == [banner.LOGO_COLORS[theme]]


def test_printed_without_the_flight_in_a_short_terminal(terminal, flights, monkeypatch):
    out = terminal()
    monkeypatch.setenv("LINES", "20")
    monkeypatch.setenv("CANVODPY_TERMINAL_THEME", "dark")
    assert banner.show_banner() is True
    assert flights == []
    red, green, blue = (
        int(banner.LOGO_COLORS["dark"][i : i + 2], 16) for i in (1, 3, 5)
    )
    assert f"38;2;{red};{green};{blue}" in out.getvalue()
    assert banner.logo().splitlines()[0].strip() in out.getvalue()


def test_printed_without_the_flight_on_windows(terminal, flights, monkeypatch):
    out = terminal()
    monkeypatch.setattr(banner, "_WINDOWS", True)
    assert banner.show_banner() is True
    assert flights == []
    assert banner.logo().splitlines()[0].strip() in out.getvalue()


def test_website_and_version_below_the_logo(terminal, flights):
    out = terminal()
    assert banner.show_banner() is True
    text = out.getvalue()
    assert banner.WEBSITE in text
    assert banner.version_line() in text
    assert f"{banner.HOLDER} · {banner.LICENSE}" in text
    assert (
        text.index(banner.WEBSITE)
        < text.index(banner.version_line())
        < text.index(banner.SUPPORT_EMAIL)
        < text.index(banner.LICENSE)
    )


def test_no_copyright_claim(terminal, flights):
    out = terminal()
    banner.show_banner()
    assert "Copyright" not in out.getvalue()
    assert "©" not in out.getvalue()


def test_cli_without_a_command_shows_the_logo_then_the_help(monkeypatch):
    shown = []
    monkeypatch.setattr(banner, "show_banner", lambda: shown.append(1) or True)
    result = CliRunner().invoke(main_app, [])
    assert result.exit_code == 0
    assert shown == [1]
    assert "Commands" in result.output


@pytest.mark.parametrize("in_terminal", [True, False])
def test_cli_version_prints_the_version_once(monkeypatch, in_terminal):
    """With the logo, the version is below it; without, it is printed alone."""
    monkeypatch.setattr(banner, "show_banner", lambda: in_terminal)
    result = CliRunner().invoke(main_app, ["--version"])
    assert result.exit_code == 0
    assert result.output == ("" if in_terminal else banner.version_line() + "\n")


@pytest.fixture
def pty_stdin(monkeypatch):
    """stdin on a pseudo-terminal, in the foreground.

    Returns the terminal's end to answer from, and a function that makes
    stdout a terminal (call it in the test body, as for ``terminal``).
    """
    terminal_end, process_end = os.openpty()
    # No echo, as a terminal's answers aren't echoed: an echo nobody reads
    # would keep the restore (TCSADRAIN) waiting.
    attrs = termios.tcgetattr(process_end)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(process_end, termios.TCSANOW, attrs)
    stdin = os.fdopen(process_end, "rb", buffering=0)
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr(banner, "_owns_terminal", lambda _fd: True)

    def stdout() -> _Terminal:
        out = _Terminal(tty=True)
        monkeypatch.setattr("sys.stdout", out)
        return out

    yield terminal_end, stdout
    stdin.close()
    os.close(terminal_end)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminals only")
class TestQueryBackground:
    def test_reads_the_answer_up_to_the_device_attributes(self, pty_stdin):
        terminal, stdout = pty_stdin
        stdout()
        os.write(terminal, b"\033]11;rgb:ffff/ffff/ffff\033\\\033[?62;22c")
        answer = banner._query_background(timeout_s=5)
        assert banner.theme_from_osc11(answer) == "light"

    def test_asks_for_the_background_then_the_device_attributes(self, pty_stdin):
        terminal, stdout = pty_stdin
        out = stdout()
        os.write(terminal, b"\033[?1;2c")
        banner._query_background(timeout_s=5)
        assert out.getvalue() == "\033]11;?\033\\\033[c"

    def test_stops_at_once_without_osc11(self, pty_stdin):
        """A terminal without OSC 11 answers only DA1: no wait."""
        terminal, stdout = pty_stdin
        stdout()
        os.write(terminal, b"\033[?1;2c")
        start = time.monotonic()
        answer = banner._query_background(timeout_s=5)
        assert time.monotonic() - start < 1
        assert banner.theme_from_osc11(answer) is None

    def test_gives_up_on_a_silent_terminal(self, pty_stdin):
        terminal, stdout = pty_stdin
        stdout()
        assert banner._query_background(timeout_s=0.05) == b""

    def test_restores_the_settings(self, pty_stdin):
        terminal, stdout = pty_stdin
        stdout()

        def settings():
            attrs = termios.tcgetattr(terminal)
            attrs[3] &= ~getattr(termios, "PENDIN", 0)  # the kernel's, not ours
            return attrs

        before = settings()
        os.write(terminal, b"\033[?1;2c")
        banner._query_background(timeout_s=5)
        assert settings() == before

    def test_not_asked_from_the_background(self, pty_stdin, monkeypatch):
        """``canvodpy run ... &``: the shell would stop the job."""
        terminal, stdout = pty_stdin
        out = stdout()
        monkeypatch.setattr(banner, "_owns_terminal", lambda _fd: False)
        assert banner._query_background(timeout_s=5) == b""
        assert out.getvalue() == ""

    def test_a_terminal_without_settings_gives_no_answer(self, pty_stdin, monkeypatch):
        terminal, stdout = pty_stdin
        stdout()

        def refuse(_fd):
            raise termios.error(25, "Inappropriate ioctl for device")

        monkeypatch.setattr(termios, "tcgetattr", refuse)
        assert banner._query_background(timeout_s=5) == b""


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminals only")
def test_owns_terminal_only_in_the_foreground(monkeypatch):
    monkeypatch.setattr(os, "tcgetpgrp", lambda _fd: os.getpgrp())
    assert banner._owns_terminal(0) is True
    monkeypatch.setattr(os, "tcgetpgrp", lambda _fd: os.getpgrp() + 1)
    assert banner._owns_terminal(0) is False

    def no_terminal(_fd):
        raise OSError(25, "Inappropriate ioctl for device")

    monkeypatch.setattr(os, "tcgetpgrp", no_terminal)
    assert banner._owns_terminal(0) is False
