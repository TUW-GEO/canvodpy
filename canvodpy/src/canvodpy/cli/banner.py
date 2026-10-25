"""The canVODpy logo in the terminal.

Shown at the start of ``canvodpy run``, for ``canvodpy --version`` and for
``canvodpy`` without a command: the logo, and centred below it the
website and the version, then the support address and the licence. Only
where the run's live progress display is shown too: in an interactive
terminal (stdout is a TTY), never in a pipe, a cron job or a log file. It
needs a terminal wider than the logo (:data:`MIN_COLUMNS`), and
``CANVODPY_NO_BANNER=1`` turns it off.

The satellite of the logo flies in from the left (under a second); in a
terminal too short for the whole logo, the logo is printed without the
flight, and on Windows it is printed without the flight too (the old
console doesn't take its escape codes). The frames, ``logo_frames.txt.gz``, are drawn from the SVG logo by
``scripts/render_logo.py``; the last frame is the logo.

The colour follows the logos in ``docs/assets/logo``: the dark-mode logo's
colour on a dark terminal background, the bright-mode logo's on a light
one. The background is taken from, in this order:

1. ``CANVODPY_TERMINAL_THEME`` (``dark`` or ``light``: the terminal's
   background, not the logo's colour);
2. the terminal's answer to the background colour query (OSC 11), which
   most current terminals give; asked only while canvodpy runs in the
   terminal's foreground (not for ``canvodpy run ... &``);
3. ``COLORFGBG``, which some terminals set;
4. otherwise dark.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import sys
import time
from importlib.resources import files
from typing import Literal

Theme = Literal["dark", "light"]

_WINDOWS = os.name == "nt"

#: The fill colour of docs/assets/logo/canvodpy_logo_{dark,bright}_mode.svg.
LOGO_COLORS: dict[Theme, str] = {"dark": "#e1e5ba", "light": "#183127"}

#: Columns of the logo.
LOGO_COLUMNS = 80

#: Columns the logo needs: one more than its width, since some terminals
#: wrap a full line at once, and the flight would then redraw too low.
MIN_COLUMNS = LOGO_COLUMNS + 1

#: Shown below the logo, as a link.
WEBSITE = "https://canvodpy.eu"

#: Support address, shown below the version as a mail link.
SUPPORT_EMAIL = "support@canvodpy.eu"

#: The licence, shown last.
LICENSE = "Apache-2.0"

#: Frames per second of the flight: its 25 frames take about 0.8 s.
FRAME_RATE = 30

_OSC11_ANSWER = re.compile(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")

#: The answer to the device attributes query (DA1), which every terminal gives.
_DA1_ANSWER = re.compile(rb"\033\[\?[0-9;]*c")


def frames() -> list[str]:
    """The frames of the flight, each without a trailing newline."""
    import gzip

    data = (files("canvodpy.cli") / "logo_frames.txt.gz").read_bytes()
    return gzip.decompress(data).decode("utf-8").rstrip("\n").split("\f")


def logo() -> str:
    """The logo: the last frame of the flight."""
    return frames()[-1]


def theme_from_osc11(answer: bytes) -> Theme | None:
    """Dark or light from a terminal's answer to OSC 11, ``None`` if unreadable.

    The answer holds the background as ``rgb:RRRR/GGGG/BBBB`` (1 to 4 hex
    digits per channel); light means a relative luminance above one half.
    """
    match = _OSC11_ANSWER.search(answer)
    if match is None:
        return None
    red, green, blue = (int(c, 16) / (16 ** len(c) - 1) for c in match.groups())
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "light" if luminance > 0.5 else "dark"


def theme_from_colorfgbg(value: str) -> Theme | None:
    """Dark or light from ``COLORFGBG`` (``"fg;bg"``), ``None`` if unreadable.

    The background is an ANSI colour number: 7 (light grey) and 9 to 15
    (the bright colours) are light, the others dark.
    """
    background = value.rsplit(";", 1)[-1]
    if not background.isdigit():
        return None
    number = int(background)
    return "light" if number == 7 or 9 <= number <= 15 else "dark"


def _owns_terminal(fd: int) -> bool:
    """Whether this process runs in the terminal's foreground.

    A background job (``canvodpy run ... &``) that changes the terminal's
    settings or reads from it is stopped by the shell until ``fg``.
    """
    try:
        return os.tcgetpgrp(fd) == os.getpgrp()
    except OSError:
        return False


def _query_background(timeout_s: float = 1.0) -> bytes:
    """Ask the terminal for its background colour (OSC 11); ``b""`` if no answer.

    POSIX only, with both stdin and stdout on the terminal and this process
    in its foreground: the answer arrives on stdin, read without echo, and
    the terminal's settings are restored afterwards. The query is followed
    by the device attributes query (DA1), which every terminal answers, and
    in order: once that answer is in, a terminal without OSC 11 has given
    none, so the wait ends at once and no late answer reaches the shell.
    ``timeout_s`` only matters for a terminal that answers neither.
    """
    if os.name != "posix" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return b""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    if not _owns_terminal(fd):
        return b""
    try:
        saved = termios.tcgetattr(fd)
    except termios.error, OSError:  # a pty that isn't a full terminal
        return b""
    answer = b""
    try:
        tty.setcbreak(fd, termios.TCSANOW)  # TCSAFLUSH would drop type-ahead
        sys.stdout.write("\033]11;?\033\\\033[c")
        sys.stdout.flush()
        deadline = time.monotonic() + timeout_s
        while not _DA1_ANSWER.search(answer):
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break
            answer += os.read(fd, 1024)
    except termios.error, OSError:
        answer = b""
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        except termios.error, OSError:
            pass
    return answer


@functools.cache
def terminal_theme() -> Theme:
    """Whether the terminal's background is dark or light (see the module).

    Asked once per process: the logo and the help colours use the same answer.
    """
    setting = os.environ.get("CANVODPY_TERMINAL_THEME", "").strip().lower()
    if setting in ("dark", "light"):
        return setting  # type: ignore[return-value]
    theme = theme_from_osc11(_query_background())
    if theme is None:
        theme = theme_from_colorfgbg(os.environ.get("COLORFGBG", ""))
    return theme or "dark"


def _fly(flight: list[str], color: str) -> None:
    """Play ``flight`` in place, in ``color``, with the cursor hidden."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    on, off = f"\033[38;2;{red};{green};{blue}m", "\033[0m"
    rows = flight[0].count("\n") + 1
    out = sys.stdout
    out.write("\033[?25l")
    try:
        for k, frame in enumerate(flight):
            if k:
                time.sleep(1 / FRAME_RATE)
                out.write(f"\033[{rows}A\r")  # back to the top of the logo
            out.write("".join(f"{on}{line}{off}\033[K\n" for line in frame.split("\n")))
            out.flush()
    finally:
        out.write("\033[?25h")
        out.flush()


def version_line() -> str:
    """``canvodpy <version>``, as ``canvodpy --version`` prints it."""
    from importlib.metadata import version

    try:
        return f"canvodpy {version('canvodpy')}"
    except Exception:
        return "canvodpy 0.0.0+unknown"


def show_banner() -> bool:
    """Show the logo with website, version and licence in an interactive terminal.

    Returns
    -------
    bool
        Whether the logo was shown.
    """
    if os.environ.get("CANVODPY_NO_BANNER", "") not in ("", "0"):
        return False
    if not sys.stdout.isatty():
        return False
    from rich.console import Console
    from rich.text import Text

    console = Console(highlight=False)
    if console.width < MIN_COLUMNS:
        return False
    color = LOGO_COLORS[terminal_theme()]
    flight = frames()
    # The flight redraws in place: it needs the whole logo on the screen,
    # and escape codes that Windows' old console doesn't take.
    tall = shutil.get_terminal_size().lines > flight[-1].count("\n") + 3
    if tall and not _WINDOWS:
        _fly(flight, color)
    else:
        console.print(Text(flight[-1], style=color))
    console.print("\n")  # two empty lines between the logo and the website
    console.print(Text(_centred(WEBSITE), style=f"bold {color} link {WEBSITE}"))
    console.print(Text(_centred(version_line()), style=color))
    console.print()
    console.print(
        Text(_centred(SUPPORT_EMAIL), style=f"{color} link mailto:{SUPPORT_EMAIL}")
    )
    console.print(Text(_centred(LICENSE), style=f"dim {color}"))
    console.print()
    return True


def _centred(text: str) -> str:
    """``text`` centred under the logo."""
    return f"{text:^{LOGO_COLUMNS}}".rstrip()
