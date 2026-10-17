"""The run history: what every run did, in one SQLite file per machine.

Every run records itself here (ADR 0018): its start (settings, canvodpy
version and commit, machine, workers, an optional label), the
receiver-days it plans and finishes, the time of each stage, resource
samples, its warnings and errors, and its end. The run dashboard and
scripts (the paper benchmark) read it through the queries of
:class:`RunHistory`. This module is the only code that touches the SQL.

The same file holds the file index (#299): the names listed in each
folder of a receiver directory, so a run lists again only the folders
that can still change (:func:`canvodpy.orchestrator.discovery.scan_directory`).

The file is ``run_history.sqlite`` in the log folder
(``processing.logging.log_dir``). It is opened in WAL mode, so one
process writes while any number of processes read; writes are short
transactions that wait (busy timeout) while another process writes, so
the main process and the worker processes of a run can all write.
SQLite's WAL mode needs shared memory, which network drives don't
provide, so opening a run history on a network drive is refused.

Examples
--------
>>> from canvodpy.run_history import RunHistory
>>> with RunHistory.open(log_dir, read_only=True) as history:  # doctest: +SKIP
...     for run in history.runs(site="fangorn"):
...         print(run.run_id, run.status)
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import sqlite3
import threading
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

import psutil

FILE_NAME = "run_history.sqlite"

# Version of the tables below. Raise it with every change to them and add
# the step from the previous version to _MIGRATIONS.
SCHEMA_VERSION = 2

# Seconds between two resource samples of a run.
SAMPLE_INTERVAL_SECONDS = 30.0

# Seconds a write waits while another process writes.
BUSY_TIMEOUT_SECONDS = 60.0

# Seconds between two tries to put a new file in WAL mode.
WAL_SWITCH_RETRY_SECONDS = 0.05

DayResult = Literal["written", "skipped", "failed"]
RunResult = Literal["finished", "failed"]
RunStatus = Literal["running", "finished", "failed", "interrupted", "unknown"]

# File system types that are network drives, as psutil reports them:
# Linux (/proc/mounts), macOS (statfs) and "remote" for Windows network
# drives and UNC paths.
_NETWORK_FILESYSTEMS = frozenset(
    {
        "afpfs",
        "ceph",
        "cifs",
        "davfs",
        "fuse.sshfs",
        "glusterfs",
        "lustre",
        "ncpfs",
        "nfs",
        "remote",
        "smbfs",
        "sshfs",
        "webdav",
    }
)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    label TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    result TEXT,
    error TEXT,
    host TEXT NOT NULL,
    pid INTEGER NOT NULL,
    process_started REAL NOT NULL,
    canvodpy_version TEXT NOT NULL,
    commit_hash TEXT,
    workers INTEGER,
    settings TEXT NOT NULL,
    machine TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_site ON runs (site, started_at);
CREATE INDEX IF NOT EXISTS runs_label ON runs (label, started_at);

CREATE TABLE IF NOT EXISTS receiver_days (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    receiver TEXT NOT NULL,
    day TEXT NOT NULL,
    result TEXT,
    bytes_added INTEGER,
    finished_at TEXT,
    PRIMARY KEY (run_id, receiver, day)
);

CREATE TABLE IF NOT EXISTS stage_timings (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    recorded_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    seconds REAL NOT NULL,
    status TEXT NOT NULL,
    receiver TEXT,
    day TEXT,
    pid INTEGER
);
CREATE INDEX IF NOT EXISTS stage_timings_run ON stage_timings (run_id);

CREATE TABLE IF NOT EXISTS resource_samples (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    sampled_at TEXT NOT NULL,
    cpu_percent REAL,
    memory_percent REAL,
    free_disk TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS resource_samples_run ON resource_samples (run_id);

CREATE TABLE IF NOT EXISTS problems (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    recorded_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    receiver TEXT,
    day TEXT
);
CREATE INDEX IF NOT EXISTS problems_run ON problems (run_id);
"""

# Version 2: the file index, one row per folder below a receiver directory
# (root), per naming recipe ('' without one). files and folders are JSON
# lists of names; newest_day is the YYYYDOY of the newest data file in the
# folder, NULL if it holds none.
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS file_index (
    root TEXT NOT NULL,
    recipe TEXT NOT NULL,
    folder TEXT NOT NULL,
    files TEXT NOT NULL,
    folders TEXT NOT NULL,
    newest_day TEXT,
    PRIMARY KEY (root, recipe, folder)
);
"""

# Steps from each schema version to the next: _MIGRATIONS[v] takes a run
# history from version v to v + 1. Version 0 is an empty file.
_MIGRATIONS: dict[int, str] = {0: _SCHEMA_V1, 1: _SCHEMA_V2}


class RunHistoryError(Exception):
    """The run history cannot be opened."""


class RunHistoryVersionError(RunHistoryError):
    """The run history was written by a newer canvodpy."""


class NetworkDriveError(RunHistoryError):
    """The log folder is on a network drive, where SQLite's WAL mode fails."""


@dataclass(frozen=True)
class Run:
    """One run as the run history knows it.

    ``status`` is ``"running"`` while the run's process lives,
    ``"finished"`` or ``"failed"`` once it ended, ``"interrupted"`` when
    its process is gone without an end (killed, crashed), and
    ``"unknown"`` when it started on another machine, whose processes
    can't be checked from here.
    """

    run_id: str
    site: str
    label: str | None
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    error: str | None
    host: str
    pid: int
    canvodpy_version: str
    commit: str | None
    workers: int | None
    settings: dict[str, Any]
    machine: dict[str, Any]


@dataclass(frozen=True)
class ReceiverProgress:
    """Receiver-days of one receiver in a run, by result."""

    receiver: str
    planned: int
    written: int
    skipped: int
    failed: int
    bytes_added: int


@dataclass(frozen=True)
class ReceiverDay:
    """One planned receiver-day; ``result`` is None until it finishes."""

    receiver: str
    day: str
    result: DayResult | None
    bytes_added: int | None
    finished_at: datetime | None


@dataclass(frozen=True)
class StageTiming:
    """The duration of one stage (reading, writing, ...) of a run."""

    recorded_at: datetime
    stage: str
    seconds: float
    status: str
    receiver: str | None
    day: str | None
    pid: int | None


@dataclass(frozen=True)
class ResourceSample:
    """CPU, memory and free disk (bytes per folder) at one moment."""

    sampled_at: datetime
    cpu_percent: float | None
    memory_percent: float | None
    free_disk: dict[str, int]


@dataclass(frozen=True)
class Problem:
    """A warning or error of a run, in plain words."""

    recorded_at: datetime
    level: str
    message: str
    receiver: str | None
    day: str | None


@dataclass(frozen=True)
class FolderListing:
    """The names listed in one folder of a receiver directory (file index).

    ``newest_day`` is the day (``YYYYDOY``) of the newest data file in the
    folder, ``None`` if it holds no data file.
    """

    files: tuple[str, ...]
    folders: tuple[str, ...]
    newest_day: str | None


def _switch_to_wal(connection: sqlite3.Connection) -> None:
    """Put the file in WAL mode, waiting while another process has it.

    Switching a new file to WAL mode needs it alone, and SQLite then fails
    at once instead of waiting for the busy timeout: runs started together
    on a new run history crashed with "database is locked" (#340). So the
    switch is tried again until :data:`BUSY_TIMEOUT_SECONDS` have passed.
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_SECONDS
    while True:
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as error:
            busy = error.sqlite_errorcode in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }
            if not busy or time.monotonic() >= deadline:
                raise
            time.sleep(WAL_SWITCH_RETRY_SECONDS)
        else:
            return


def run_history_path(log_dir: Path | str) -> Path:
    """Return the run history file in *log_dir*."""
    return Path(log_dir) / FILE_NAME


def filesystem_type(path: Path | str) -> str:
    """Return the type of the file system *path* is on, lower case.

    Parameters
    ----------
    path : Path or str
        A file or folder; it need not exist yet.

    Returns
    -------
    str
        For example ``"apfs"``, ``"ext4"``, ``"nfs4"``, ``"cifs"``;
        ``"remote"`` for a Windows network drive or UNC path; ``""`` if
        the operating system names no file system for *path*.
    """
    resolved = Path(path).expanduser().resolve()
    if os.name == "nt" and str(resolved).startswith("\\\\"):
        return "remote"
    best = None
    for partition in psutil.disk_partitions(all=True):
        mountpoint = Path(partition.mountpoint)
        if (mountpoint == resolved or mountpoint in resolved.parents) and (
            best is None or len(partition.mountpoint) > len(best.mountpoint)
        ):
            best = partition
    if best is None:
        return ""
    if "remote" in best.opts.split(","):
        return "remote"
    return best.fstype.lower()


def is_network_filesystem(fs_type: str) -> bool:
    """Tell whether *fs_type* (from :func:`filesystem_type`) is a network drive.

    NFS and SMB in all their versions (``nfs4``, ``smb3``) count.
    """
    fs_type = fs_type.lower()
    return (
        fs_type in _NETWORK_FILESYSTEMS
        or fs_type.startswith(("nfs", "smb"))
        or (fs_type.startswith("fuse.") and fs_type[5:] in _NETWORK_FILESYSTEMS)
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _maybe_time(value: str | None) -> datetime | None:
    return None if value is None else _time(value)


class RunHistory:
    """An open run history; open it with :meth:`open`.

    One object may be shared by the threads of a process; every process
    opens its own.
    """

    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self._db = connection
        self._lock = threading.Lock()
        self.path = path

    @classmethod
    def open(cls, log_dir: Path | str, *, read_only: bool = False) -> Self:
        """Open the run history in *log_dir*, creating it if absent.

        Parameters
        ----------
        log_dir : Path or str
            The log folder (``processing.logging.log_dir``).
        read_only : bool, default False
            Open for the dashboard and scripts: no writes, nothing created.

        Raises
        ------
        NetworkDriveError
            If *log_dir* is on a network drive.
        RunHistoryVersionError
            If a newer canvodpy wrote the run history.
        FileNotFoundError
            If *read_only* and there is no run history in *log_dir*.
        """
        path = run_history_path(log_dir)
        fs_type = filesystem_type(path.parent)
        if is_network_filesystem(fs_type):
            msg = (
                f"The log folder {path.parent} is on a network drive ({fs_type}). "
                "The run history is a SQLite file, which works only on a local "
                "disk. Set processing.logging.log_dir in canvod-settings.yaml "
                "to a folder on a local disk."
            )
            raise NetworkDriveError(msg)

        if read_only:
            if not path.exists():
                msg = f"There is no run history in {path.parent}"
                raise FileNotFoundError(msg)
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=ro",
                uri=True,
                timeout=BUSY_TIMEOUT_SECONDS,
                autocommit=True,
                check_same_thread=False,
            )
            history = cls(connection, path)
            history._check_version(history._version())
            return history

        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            path,
            timeout=BUSY_TIMEOUT_SECONDS,
            autocommit=True,
            check_same_thread=False,
        )
        try:
            _switch_to_wal(connection)
            connection.execute("PRAGMA synchronous = NORMAL")
            history = cls(connection, path)
            history._migrate()
        except BaseException:
            connection.close()
            raise
        return history

    def close(self) -> None:
        """Close the file."""
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema --------------------------------------------------------

    def _version(self) -> int:
        return self._db.execute("PRAGMA user_version").fetchone()[0]

    def _check_version(self, version: int) -> None:
        if version > SCHEMA_VERSION:
            msg = (
                f"The run history {self.path} was written by a newer canvodpy "
                f"(schema version {version}; this canvodpy reads up to "
                f"{SCHEMA_VERSION}). Update canvodpy, or set "
                "processing.logging.log_dir to another folder."
            )
            raise RunHistoryVersionError(msg)

    def _migrate(self) -> None:
        with self._write() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            self._check_version(version)
            while version < SCHEMA_VERSION:
                for statement in _MIGRATIONS[version].split(";"):
                    if statement.strip():
                        db.execute(statement)
                version += 1
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        """One short write transaction; waits while another process writes."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _read(self, sql: str, *params: Any) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._db.execute(sql, params)
            cursor.row_factory = sqlite3.Row
            return cursor.fetchall()

    # -- writing -------------------------------------------------------

    def start_run(
        self,
        run_id: str,
        *,
        site: str,
        settings: dict[str, Any],
        canvodpy_version: str,
        commit: str | None,
        machine: dict[str, Any],
        workers: int | None,
        label: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Record the start of a run, by the process calling this.

        The host and process of the caller are recorded, so a run whose
        process is gone without :meth:`end_run` shows as interrupted.
        *started_at* defaults to now; pass an aware UTC time (as the tests
        do) to fix the run's wall time.
        """
        process = psutil.Process()
        with self._write() as db:
            db.execute(
                "INSERT INTO runs (run_id, site, label, started_at, host, pid,"
                " process_started, canvodpy_version, commit_hash, workers,"
                " settings, machine) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    site,
                    label,
                    _now() if started_at is None else started_at.isoformat(),
                    socket.gethostname(),
                    process.pid,
                    process.create_time(),
                    canvodpy_version,
                    commit,
                    workers,
                    json.dumps(settings, default=str),
                    json.dumps(machine, default=str),
                ),
            )

    def plan_receiver_days(
        self, run_id: str, receiver_days: Iterable[tuple[str, str]]
    ) -> None:
        """Record the receiver-days a run plans, as ``(receiver, YYYYDOY)``."""
        with self._write() as db:
            db.executemany(
                "INSERT OR IGNORE INTO receiver_days (run_id, receiver, day)"
                " VALUES (?, ?, ?)",
                [(run_id, receiver, day) for receiver, day in receiver_days],
            )

    def finish_receiver_day(
        self,
        run_id: str,
        receiver: str,
        day: str,
        result: DayResult,
        *,
        bytes_added: int | None = None,
    ) -> None:
        """Record that a receiver-day (``YYYYDOY``) finished, and how."""
        with self._write() as db:
            db.execute(
                "INSERT INTO receiver_days"
                " (run_id, receiver, day, result, bytes_added, finished_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (run_id, receiver, day) DO UPDATE SET"
                " result = excluded.result, bytes_added = excluded.bytes_added,"
                " finished_at = excluded.finished_at",
                (run_id, receiver, day, result, bytes_added, _now()),
            )

    def record_stage(
        self,
        run_id: str,
        stage: str,
        seconds: float,
        status: str = "ok",
        *,
        receiver: str | None = None,
        day: str | None = None,
        pid: int | None = None,
    ) -> None:
        """Record the duration of one stage, from any process of the run."""
        with self._write() as db:
            db.execute(
                "INSERT INTO stage_timings (run_id, recorded_at, stage, seconds,"
                " status, receiver, day, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, _now(), stage, seconds, status, receiver, day, pid),
            )

    def record_resources(
        self,
        run_id: str,
        *,
        cpu_percent: float | None,
        memory_percent: float | None,
        free_disk: dict[str, int],
    ) -> None:
        """Record one sample of CPU, memory and free disk (bytes per folder)."""
        with self._write() as db:
            db.execute(
                "INSERT INTO resource_samples (run_id, sampled_at, cpu_percent,"
                " memory_percent, free_disk) VALUES (?, ?, ?, ?, ?)",
                (run_id, _now(), cpu_percent, memory_percent, json.dumps(free_disk)),
            )

    def record_problem(
        self,
        run_id: str,
        level: str,
        message: str,
        *,
        receiver: str | None = None,
        day: str | None = None,
    ) -> None:
        """Record a warning or error of a run, in plain words."""
        with self._write() as db:
            db.execute(
                "INSERT INTO problems (run_id, recorded_at, level, message,"
                " receiver, day) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, _now(), level, message, receiver, day),
            )

    def set_workers(self, run_id: str, workers: int) -> None:
        """Record the worker processes the run was sized to."""
        with self._write() as db:
            db.execute(
                "UPDATE runs SET workers = ? WHERE run_id = ?", (workers, run_id)
            )

    def end_run(
        self,
        run_id: str,
        result: RunResult,
        *,
        error: str | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        """Record the end of a run; *error* says why a failed run failed.

        *ended_at* defaults to now; pass an aware UTC time (as the tests
        do) to fix the run's wall time.
        """
        with self._write() as db:
            db.execute(
                "UPDATE runs SET ended_at = ?, result = ?, error = ? WHERE run_id = ?",
                (
                    _now() if ended_at is None else ended_at.isoformat(),
                    result,
                    error,
                    run_id,
                ),
            )

    def save_file_index(
        self, root: Path, recipe: Path | None, listings: dict[str, FolderListing]
    ) -> None:
        """Replace the file index of the receiver directory *root*.

        *listings* maps each folder, relative to *root* (``"."`` for
        *root*), to its listing. A receiver directory with a naming recipe
        has its own index per recipe file.
        """
        key = (str(root), str(recipe or ""))
        with self._write() as db:
            db.execute("DELETE FROM file_index WHERE root = ? AND recipe = ?", key)
            db.executemany(
                "INSERT INTO file_index (root, recipe, folder, files, folders,"
                " newest_day) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        *key,
                        folder,
                        json.dumps(listing.files),
                        json.dumps(listing.folders),
                        listing.newest_day,
                    )
                    for folder, listing in listings.items()
                ],
            )

    # -- queries -------------------------------------------------------

    def file_index(self, root: Path, recipe: Path | None) -> dict[str, FolderListing]:
        """The file index of the receiver directory *root*, as saved.

        Empty if there is none, or if it can't be read: a run then lists
        every folder and saves the index again.
        """
        try:
            rows = self._read(
                "SELECT folder, files, folders, newest_day FROM file_index"
                " WHERE root = ? AND recipe = ?",
                str(root),
                str(recipe or ""),
            )
            return {
                row["folder"]: FolderListing(
                    files=tuple(json.loads(row["files"])),
                    folders=tuple(json.loads(row["folders"])),
                    newest_day=row["newest_day"],
                )
                for row in rows
            }
        except sqlite3.Error, ValueError, TypeError:
            import structlog

            structlog.get_logger(__name__).warning(
                "file_index_unreadable", root=str(root), exc_info=True
            )
            return {}

    def runs(self, *, site: str | None = None, label: str | None = None) -> list[Run]:
        """Return the runs, newest first, optionally of one site or label."""
        rows = self._read(
            "SELECT * FROM runs WHERE (?1 IS NULL OR site = ?1)"
            " AND (?2 IS NULL OR label = ?2) ORDER BY started_at DESC, run_id DESC",
            site,
            label,
        )
        return [self._run(row) for row in rows]

    def run(self, run_id: str) -> Run:
        """Return one run.

        Raises
        ------
        KeyError
            If the run history has no run *run_id*.
        """
        rows = self._read("SELECT * FROM runs WHERE run_id = ?", run_id)
        if not rows:
            raise KeyError(run_id)
        return self._run(rows[0])

    def progress(self, run_id: str) -> list[ReceiverProgress]:
        """Return the planned and finished receiver-days per receiver."""
        rows = self._read(
            "SELECT receiver, count(*) AS planned,"
            " count(*) FILTER (WHERE result = 'written') AS written,"
            " count(*) FILTER (WHERE result = 'skipped') AS skipped,"
            " count(*) FILTER (WHERE result = 'failed') AS failed,"
            " coalesce(sum(bytes_added), 0) AS bytes_added"
            " FROM receiver_days WHERE run_id = ? GROUP BY receiver ORDER BY receiver",
            run_id,
        )
        return [ReceiverProgress(**dict(row)) for row in rows]

    def receiver_days(self, run_id: str) -> list[ReceiverDay]:
        """Return the receiver-days of a run, by receiver and day."""
        rows = self._read(
            "SELECT receiver, day, result, bytes_added, finished_at"
            " FROM receiver_days WHERE run_id = ? ORDER BY receiver, day",
            run_id,
        )
        return [
            ReceiverDay(
                receiver=row["receiver"],
                day=row["day"],
                result=row["result"],
                bytes_added=row["bytes_added"],
                finished_at=_maybe_time(row["finished_at"]),
            )
            for row in rows
        ]

    def stage_timings(self, run_id: str) -> list[StageTiming]:
        """Return the stage timings of a run, in the order they were recorded."""
        rows = self._read(
            "SELECT recorded_at, stage, seconds, status, receiver, day, pid"
            " FROM stage_timings WHERE run_id = ? ORDER BY rowid",
            run_id,
        )
        return [
            StageTiming(
                recorded_at=_time(row["recorded_at"]),
                stage=row["stage"],
                seconds=row["seconds"],
                status=row["status"],
                receiver=row["receiver"],
                day=row["day"],
                pid=row["pid"],
            )
            for row in rows
        ]

    def resource_samples(self, run_id: str) -> list[ResourceSample]:
        """Return the resource samples of a run, oldest first."""
        rows = self._read(
            "SELECT sampled_at, cpu_percent, memory_percent, free_disk"
            " FROM resource_samples WHERE run_id = ? ORDER BY rowid",
            run_id,
        )
        return [
            ResourceSample(
                sampled_at=_time(row["sampled_at"]),
                cpu_percent=row["cpu_percent"],
                memory_percent=row["memory_percent"],
                free_disk=json.loads(row["free_disk"]),
            )
            for row in rows
        ]

    def problems(self, run_id: str) -> list[Problem]:
        """Return the warnings and errors of a run, oldest first."""
        rows = self._read(
            "SELECT recorded_at, level, message, receiver, day"
            " FROM problems WHERE run_id = ? ORDER BY rowid",
            run_id,
        )
        return [
            Problem(
                recorded_at=_time(row["recorded_at"]),
                level=row["level"],
                message=row["message"],
                receiver=row["receiver"],
                day=row["day"],
            )
            for row in rows
        ]

    @staticmethod
    def _run(row: sqlite3.Row) -> Run:
        return Run(
            run_id=row["run_id"],
            site=row["site"],
            label=row["label"],
            status=_status(row),
            started_at=_time(row["started_at"]),
            ended_at=_maybe_time(row["ended_at"]),
            error=row["error"],
            host=row["host"],
            pid=row["pid"],
            canvodpy_version=row["canvodpy_version"],
            commit=row["commit_hash"],
            workers=row["workers"],
            settings=json.loads(row["settings"]),
            machine=json.loads(row["machine"]),
        )


def _status(row: sqlite3.Row) -> RunStatus:
    """Status of a run: its result once ended, else whether its process lives."""
    if row["result"] is not None:
        return row["result"]
    if row["host"] != socket.gethostname():
        return "unknown"
    try:
        process = psutil.Process(row["pid"])
        # The same process ID may belong to a later process.
        alive = abs(process.create_time() - row["process_started"]) < 1.0
    except psutil.NoSuchProcess:
        alive = False
    except psutil.AccessDenied:
        # A process of another user, whose start can't be read: it lives.
        alive = True
    return "running" if alive else "interrupted"


# -- recording a run ---------------------------------------------------


@dataclass(frozen=True)
class ActiveRun:
    """A run being recorded: what processing code writes to while it runs.

    A failed write is logged and doesn't stop the run: the data matter
    more than their record.
    """

    run_id: str
    history: RunHistory

    def plan(self, receiver_days: Iterable[tuple[str, str]]) -> None:
        """Record the ``(receiver, day)`` pairs the run will process."""
        self._try(self.history.plan_receiver_days, self.run_id, list(receiver_days))

    def record_resources(self, **sample: Any) -> None:
        """Record one resource sample (:meth:`RunHistory.record_resources`)."""
        self._try(self.history.record_resources, self.run_id, **sample)

    def set_workers(self, workers: int) -> None:
        """Record the worker processes the run was sized to."""
        self._try(self.history.set_workers, self.run_id, workers)

    def finish(
        self,
        receiver: str,
        day: str,
        result: DayResult,
        *,
        bytes_added: int | None = None,
    ) -> None:
        """Record a finished receiver-day."""
        self._try(
            self.history.finish_receiver_day,
            self.run_id,
            receiver,
            day,
            result,
            bytes_added=bytes_added,
        )

    def save_file_index(
        self, root: Path, recipe: Path | None, listings: dict[str, FolderListing]
    ) -> None:
        """Save a receiver directory's file index (:meth:`RunHistory.save_file_index`)."""
        self._try(self.history.save_file_index, root, recipe, listings)

    @staticmethod
    def _try(write: Any, *args: Any, **kwargs: Any) -> None:
        try:
            write(*args, **kwargs)
        except sqlite3.Error:
            import structlog

            structlog.get_logger(__name__).warning(
                "run_history_write_failed", exc_info=True
            )


@contextmanager
def recorded_run(
    site: str,
    *,
    log_dir: Path | str,
    settings: dict[str, Any],
    workers: int | None,
    disks: Iterable[Path | str] = (),
    label: str | None = None,
) -> Generator[ActiveRun]:
    """Record a run of *site* from start to end in the run history of *log_dir*.

    While the block runs, CPU, memory and the free disk of the log folder
    and *disks* are sampled every :data:`SAMPLE_INTERVAL_SECONDS` and once
    more when it ends, also when it fails.

    The run takes the run ID of the caller's context
    (:func:`canvod.utils.logging.get_run_id`), or a new one. A run ID the
    run history already holds (a caller set one used before) gets a number
    (``fangorn-20261014-120000-3f9a1c-2``); the run ID is set for the time
    of the block. The run ends as finished when the block ends,
    as failed with the error when it raises.

    Parameters
    ----------
    site : str
        Site name.
    log_dir : Path or str
        Log folder (``processing.logging.log_dir``).
    settings : dict
        The settings of the run, as JSON-compatible values.
    workers : int or None
        Worker processes of the run, as asked; a pipeline run replaces it
        with the count it was sized to (:meth:`ActiveRun.set_workers`).
    disks : iterable of Path or str
        Folders whose disk the machine facts describe (the stores); the log
        folder is always included.
    label : str, optional
        Free-text label (``canvodpy run --label``).

    Raises
    ------
    NetworkDriveError
        If *log_dir* is on a network drive.
    """
    from canvod.utils.logging import get_run_id, new_run_id, reset_run_id, set_run_id
    from canvodpy.orchestrator.resources import ResourceSampler

    base_id = get_run_id() or new_run_id(site)
    token = None
    try:
        with RunHistory.open(log_dir) as history:
            facts = {
                "site": site,
                "settings": settings,
                "canvodpy_version": canvodpy_version(),
                "commit": canvodpy_commit(),
                "machine": machine_facts([log_dir, *disks]),
                "workers": workers,
                "label": label,
            }
            run_id = base_id
            for number in itertools.count(2):
                try:
                    history.start_run(
                        run_id,
                        site=facts["site"],
                        settings=facts["settings"],
                        canvodpy_version=facts["canvodpy_version"],
                        commit=facts["commit"],
                        machine=facts["machine"],
                        workers=facts["workers"],
                        label=facts["label"],
                    )
                    break
                except sqlite3.IntegrityError:
                    run_id = f"{base_id}-{number}"
            token = set_run_id(run_id)
            active = ActiveRun(run_id, history)
            sampler = ResourceSampler(
                SAMPLE_INTERVAL_SECONDS,
                disks=facts["machine"]["disks"],
                on_sample=active.record_resources,
            )
            sampler.start()
            try:
                yield active
            except BaseException as error:
                sampler.stop()
                history.end_run(
                    run_id, "failed", error=f"{type(error).__name__}: {error}"
                )
                raise
            sampler.stop()
            history.end_run(run_id, "finished")
    finally:
        if token is not None:
            reset_run_id(token)


def canvodpy_version() -> str:
    """Return the installed canvodpy version."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("canvodpy")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def canvodpy_commit() -> str | None:
    """Return the git commit canvodpy runs from, or ``None`` if unknown.

    From the install record of a package installed from git, else from the
    git checkout an editable install points into.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        direct_url = distribution("canvodpy").read_text("direct_url.json")
    except PackageNotFoundError:
        direct_url = None
    if direct_url:
        commit = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
        if commit:
            return commit
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return out.stdout.strip() or None


def machine_facts(disks: Iterable[Path | str] = ()) -> dict[str, Any]:
    """Return the facts of this machine a run records.

    CPU model and counts, memory, operating system, Python, and for each
    folder of *disks* the size, free space and file system of its disk.
    """
    import platform

    memory = psutil.virtual_memory()
    facts: dict[str, Any] = {
        "cpu_model": _cpu_model(),
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(logical=True),
        "memory_total": memory.total,
        "os": platform.platform(),
        "python": platform.python_version(),
        "disks": {},
    }
    for folder in disks:
        path = Path(folder).expanduser()
        existing = next((p for p in (path, *path.parents) if p.exists()), None)
        if existing is None:
            continue
        usage = psutil.disk_usage(str(existing))
        facts["disks"][str(path)] = {
            "total": usage.total,
            "free": usage.free,
            "filesystem": filesystem_type(existing),
        }
    return facts


def _cpu_model() -> str:
    import platform
    import subprocess
    import sys

    if sys.platform == "darwin":
        try:
            return subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
        except OSError, subprocess.SubprocessError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()
