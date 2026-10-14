"""The run history: what every run did, in one SQLite file per machine.

Every run records itself here (ADR 0018): its start (settings, canvodpy
version and commit, machine, workers, an optional label), the
receiver-days it plans and finishes, the time of each stage, resource
samples, its warnings and errors, and its end. The run dashboard and
scripts (the paper benchmark) read it through the queries of
:class:`RunHistory`. This module is the only code that touches the SQL.

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

import json
import os
import socket
import sqlite3
import threading
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
SCHEMA_VERSION = 1

# Seconds a write waits while another process writes.
BUSY_TIMEOUT_SECONDS = 60.0

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

# Steps from each schema version to the next: _MIGRATIONS[v] takes a run
# history from version v to v + 1. Version 0 is an empty file.
_MIGRATIONS: dict[int, str] = {0: _SCHEMA_V1}


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
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        history = cls(connection, path)
        history._migrate()
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
    ) -> None:
        """Record the start of a run, by the process calling this.

        The host and process of the caller are recorded, so a run whose
        process is gone without :meth:`end_run` shows as interrupted.
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
                    _now(),
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

    def end_run(
        self, run_id: str, result: RunResult, *, error: str | None = None
    ) -> None:
        """Record the end of a run; *error* says why a failed run failed."""
        with self._write() as db:
            db.execute(
                "UPDATE runs SET ended_at = ?, result = ?, error = ? WHERE run_id = ?",
                (_now(), result, error, run_id),
            )

    # -- queries -------------------------------------------------------

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
