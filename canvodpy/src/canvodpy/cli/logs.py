"""canvodpy logs: a copy of this machine's log folder (#131).

An unattended run leaves its logs on the machine it ran on. ``collect``
copies the log folder (``processing.logging.log_dir``) to one new folder,
which the operator sends on with rsync or scp. The run history is copied
through SQLite (:meth:`canvodpy.run_history.RunHistory.copy`), so its
copy is consistent while a run writes. A log file that is removed or
renamed after the listing, as a running run's log rotation does, is left
out and counted: what its name holds then is another file.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, BinaryIO, NoReturn

import typer
from rich.markup import escape

from canvodpy.cli.options import CONFIG_DIR_OPTION, CONFIG_FILE_OPTION
from canvodpy.cli.theme import console

logs_app = typer.Typer(
    name="logs",
    help="Copy the log folder of this machine, to send it on.",
    no_args_is_help=True,
)


def _log_dir() -> Path:
    from canvod.config import load_config

    log_dir = load_config().processing.logging.log_dir
    if log_dir is None:
        _refused(
            "No log folder set. Set processing.logging.log_dir in canvod-settings.yaml."
        )
    if not log_dir.is_dir():
        _refused(f"The log folder {log_dir} doesn't exist: no run has logged there.")
    return log_dir


def _listed(paths: Iterable[Path]) -> tuple[list[tuple[Path, int]], int]:
    """The regular files among *paths*, each with its inode, and the count
    of the paths that were gone by the time they were looked at."""
    listed, gone = [], 0
    for path in sorted(paths):
        try:
            status = path.lstat()
        except FileNotFoundError:
            gone += 1
            continue
        if stat.S_ISREG(status.st_mode):
            listed.append((path, status.st_ino))
    return listed, gone


def _open_listed(path: Path, inode: int) -> BinaryIO | None:
    """*path* opened for reading, or None if the file listed there was
    removed or renamed since: a running run's log rotation does both, and
    the name then holds another file, or none."""
    try:
        handle = path.open("rb")
    except FileNotFoundError:
        return None
    if os.fstat(handle.fileno()).st_ino != inode:
        handle.close()
        return None
    return handle


def _copy_log_files(log_dir: Path, dest: Path) -> tuple[int, int, int]:
    """Copy every file but the run history.

    Returns the count and size of the copied files, and the count of the
    files that were removed or renamed after they were listed.
    """
    from canvodpy.run_history import FILE_NAME

    listed, changed = _listed(
        path for path in log_dir.rglob("*") if not path.name.startswith(FILE_NAME)
    )
    count = size = 0
    for source, inode in listed:
        handle = _open_listed(source, inode)
        if handle is None:
            changed += 1
            continue
        target = dest / source.relative_to(log_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        with handle, target.open("wb") as out:
            shutil.copyfileobj(handle, out)
            status = os.fstat(handle.fileno())
        os.utime(target, ns=(status.st_atime_ns, status.st_mtime_ns))
        count += 1
        size += target.stat().st_size
    return count, size, changed


def _run_events(log_dir: Path, run_id: str) -> tuple[list[str], int]:
    """The lines of every ``machine/agent*.json*`` file that *run_id* logged,
    and the count of the files removed or renamed after they were listed.

    The main process and each worker write their own files; the lines are
    returned in the order of their timestamps (ISO, UTC).
    """
    listed, changed = _listed((log_dir / "machine").glob("agent*.json*"))
    found = []
    for path, inode in listed:
        handle = _open_listed(path, inode)
        if handle is None:
            changed += 1
            continue
        with io.TextIOWrapper(handle, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # a line cut off by a crash
                if isinstance(event, dict) and event.get("run_id") == run_id:
                    found.append((str(event.get("timestamp", "")), line.rstrip("\n")))
    found.sort(key=lambda item: item[0])
    return [line for _, line in found], changed


def _warn_changed(changed: int) -> None:
    if changed:
        console.print(
            f"[canvod.warning]  {changed} log "
            f"{'files were' if changed > 1 else 'file was'} removed or renamed "
            "during the copy, probably by the log rotation of a running run, "
            "and left out. Collect between runs for a complete copy."
            "[/canvod.warning]"
        )


RUN_ID_OPTION = typer.Option(
    "--run-id",
    help=(
        "Copy only this run: its records of the run history and its events "
        "from machine/agent*.json, as DEST/<run-id>.json."
    ),
    show_default=False,
)


@logs_app.command("collect")
def collect(
    dest: Annotated[
        Path,
        typer.Argument(help="New or empty folder for the copy.", show_default=False),
    ],
    run_id: Annotated[str | None, RUN_ID_OPTION] = None,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
    config_file: Annotated[Path | None, CONFIG_FILE_OPTION] = None,
) -> None:
    """Copy the log folder of the settings to DEST.

    Every log file is copied with its folders (human/, machine/,
    component/). The run history is copied through SQLite, with the
    records a running run hasn't merged out of its WAL file yet, as one
    file. Nothing in DEST is overwritten: it must be new or empty. A log
    file that is removed or renamed during the copy, as a running run's
    log rotation does, is left out, and the command says how many.

    With --run-id, DEST gets that run's records of the run history and its
    events, from the main process and the workers, in DEST/<run-id>.json.
    The readable logs are left out: they mix runs.
    """
    from canvodpy.run_history import RunHistory, run_history_path

    log_dir = _log_dir()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        _refused(f"{dest} is not empty: give a new or empty folder.")
    if run_id is not None:
        _collect_run(log_dir, dest, run_id)
        return
    dest.mkdir(parents=True, exist_ok=True)

    count, size, changed = _copy_log_files(log_dir, dest)
    console.print(
        f"[canvod.ok]✓ {count} log files ({size / 1e6:.1f} MB) copied to "
        f"{escape(str(dest))}[/canvod.ok]"
    )
    _warn_changed(changed)
    if run_history_path(log_dir).exists():
        with RunHistory.open(log_dir, read_only=True) as history:
            history.copy(run_history_path(dest))
        console.print(f"  Run history: {escape(str(run_history_path(dest)))}")


def _collect_run(log_dir: Path, dest: Path, run_id: str) -> None:
    from canvodpy.run_history import RunHistory, run_history_path

    if not run_history_path(log_dir).exists():
        _refused(f"There is no run history in {log_dir}.")
    with RunHistory.open(log_dir, read_only=True) as history:
        try:
            history.run(run_id)
        except KeyError:
            _refused(f"The run history in {log_dir} has no run {run_id}.")
        dest.mkdir(parents=True, exist_ok=True)
        history.copy_runs([run_id], run_history_path(dest))
    events, changed = _run_events(log_dir, run_id)
    (dest / f"{run_id}.json").write_text(
        "".join(f"{line}\n" for line in events), encoding="utf-8"
    )
    console.print(
        f"[canvod.ok]✓ Run {escape(run_id)}: {len(events)} events and its run "
        f"history copied to {escape(str(dest))}[/canvod.ok]"
    )
    _warn_changed(changed)


def _refused(message: str) -> NoReturn:
    console.print(f"[canvod.error]❌ {escape(message)}[/canvod.error]", soft_wrap=True)
    raise typer.Exit(1)
