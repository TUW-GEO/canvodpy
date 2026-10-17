"""Write an anonymized copy of a run history for the dashboard example.

The copy keeps what the run dashboard shows (the runs, their timings,
results, problems and resource samples) and replaces everything that
names a person, a machine or a place:

- the person, institution, funding and site in the settings become the
  test persona of :mod:`canvod.utils.testing` (site Fangorn);
- the machine becomes an example machine: no real CPU model, core
  counts, memory, operating system, host name or process ids;
- every path under ``--path-prefix`` moves under ``/data/example``, and
  the disk sizes are example values (the changes of free space during a
  run are kept);
- the file index (the receiver file names) is emptied: the dashboard
  doesn't show it.

A last check refuses the copy if any home folder path, an e-mail other
than the persona's, or a ``--forbid`` text is left. The source is only
read.

Usage::

    uv run python scripts/anonymize_run_history.py SOURCE.sqlite OUT.sqlite \\
        --path-prefix /home/someone/benchmarks --forbid someone --forbid SiteName
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from canvod.utils import testing

EXAMPLE_ROOT = "/data/example"
EXAMPLE_HOST = "example-host"
EXAMPLE_DISK_TOTAL = 2_000_000_000_000
EXAMPLE_DISK_FREE = 1_500_000_000_000
EXAMPLE_MACHINE = {
    "cpu_model": "Example CPU",
    "cpu_physical": 72,
    "cpu_logical": 144,
    "memory_total": 512 * 1024**3,
    "os": "Linux-example-x86_64",
}
FIRST_PID = 10_000
HOME_PATH = re.compile(r"/(home|Users)/[^/\s\"']+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def _persona_metadata(metadata: dict) -> dict:
    """The processing metadata of the test persona, same keys."""
    persona = {
        "author": testing.PERSON_NAME,
        "email": testing.PERSON_EMAIL,
        "orcid": testing.PERSON_ORCID,
        "institution": testing.INSTITUTION,
        "institution_ror": f"https://ror.org/{testing.INSTITUTION_ROR}",
        "department": testing.DEPARTMENT,
        "research_group": testing.RESEARCH_GROUP,
        "website": testing.WEBSITE,
        "publisher": testing.PUBLISHER,
        "publisher_url": testing.WEBSITE,
        "naming_authority": testing.NAMING_AUTHORITY,
        "initials": testing.PERSON_INITIALS,
    }
    return {key: persona.get(key, value) for key, value in metadata.items()}


def _persona_site(site: dict) -> dict:
    """One site of the settings as the persona's site Fangorn."""
    receivers = {}
    for name, receiver in site.get("receivers", {}).items():
        receiver = dict(receiver)
        kind = receiver.get("type", "receiver")
        receiver["description"] = f"{testing.CANOPY_SITE} {kind} receiver"
        if receiver.get("recipe"):
            receiver["recipe"] = f"{testing.SITE_KEY}_{kind}"
        for key in ("metadata", "receiver_hardware", "antenna"):
            if receiver.get(key) is not None:
                receiver[key] = None
        receivers[name] = receiver
    return {
        **site,
        "description": testing.SITE_DESCRIPTION,
        "store_description": "Example store of the canvodpy run dashboard demo.",
        "country": "ZA",
        "latitude": testing.LATITUDE,
        "longitude": testing.LONGITUDE,
        "altitude_m": testing.ALTITUDE_M,
        "receivers": receivers,
    }


class Anonymizer:
    """The replacements of one run history, kept consistent across tables."""

    def __init__(self, path_prefix: str, site: str) -> None:
        self.path_prefix = path_prefix.rstrip("/")
        self.site = site
        self.pids: dict[int, int] = {}
        self.first_free: dict[str, int] = {}

    def path(self, text: str) -> str:
        """Move a path under ``--path-prefix`` to the example root, and the
        site's name in it to the persona's."""
        if text.startswith(self.path_prefix):
            text = EXAMPLE_ROOT + text[len(self.path_prefix) :]
        return text.replace(self.site, testing.SITE_KEY)

    def text(self, value):
        """Apply :meth:`path` to every string in a JSON value."""
        if isinstance(value, str):
            return self.path(value)
        if isinstance(value, list):
            return [self.text(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.text(item) for key, item in value.items()}
        return value

    def pid(self, pid: int) -> int:
        """An example process id, the same one for the same real one."""
        return self.pids.setdefault(pid, FIRST_PID + len(self.pids))

    def run_id(self, run_id: str) -> str:
        """The run id with the persona's site name."""
        return run_id.replace(self.site, testing.SITE_KEY)

    def free(self, folder: str, free: int) -> int:
        """Example free space: the change since the folder's first sample."""
        first = self.first_free.setdefault(folder, free)
        return EXAMPLE_DISK_FREE + (free - first)

    def settings(self, settings: dict) -> dict:
        """The settings with the persona, its site and example paths."""
        settings = json.loads(json.dumps(settings))
        processing = settings.get("processing", {})
        if "metadata" in processing:
            processing["metadata"] = _persona_metadata(processing["metadata"])
        if "references" in processing:
            processing["references"] = {
                **processing["references"],
                "software_repository": testing.REPOSITORY,
                "documentation": testing.DOCUMENTATION,
                "funding": [],
            }
        if "credentials" in processing:
            processing["credentials"] = {key: None for key in processing["credentials"]}
        sites = settings.get("sites", {}).get("sites", {})
        if sites:
            settings["sites"]["sites"] = {
                testing.SITE_KEY if name == self.site else name: _persona_site(site)
                for name, site in sites.items()
            }
        return self.text(settings)

    def machine(self, machine: dict) -> dict:
        """An example machine with the real one's disks moved and resized."""
        disks = {
            self.path(folder): {
                "total": EXAMPLE_DISK_TOTAL,
                "free": self.free(folder, disk["free"]),
                "filesystem": disk.get("filesystem"),
            }
            for folder, disk in machine.get("disks", {}).items()
        }
        return {
            **EXAMPLE_MACHINE,
            "python": machine.get("python"),
            "disks": disks,
        }


def anonymize(source: Path, out: Path, path_prefix: str) -> None:
    """Write the anonymized copy of ``source`` to ``out``."""
    if out.exists():
        sys.exit(f"{out} exists; remove it or choose another name")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        dst = sqlite3.connect(out)
        src.backup(dst)
    sites = {row[0] for row in dst.execute("SELECT DISTINCT site FROM runs")}
    if len(sites) != 1:
        sys.exit(f"expected the runs of one site, found {sorted(sites)}")
    anonymizer = Anonymizer(path_prefix, sites.pop())

    # Disk samples first, so each folder's first free space is the earliest.
    samples = dst.execute(
        "SELECT rowid, run_id, free_disk FROM resource_samples ORDER BY sampled_at"
    ).fetchall()
    for rowid, run_id, free_disk in samples:
        free = json.loads(free_disk) if free_disk else {}
        moved = {anonymizer.path(f): anonymizer.free(f, v) for f, v in free.items()}
        dst.execute(
            "UPDATE resource_samples SET run_id = ?, free_disk = ? WHERE rowid = ?",
            (anonymizer.run_id(run_id), json.dumps(moved), rowid),
        )
    runs = dst.execute("SELECT run_id, pid, settings, machine FROM runs").fetchall()
    for run_id, pid, settings, machine in runs:
        dst.execute(
            "UPDATE runs SET run_id = ?, site = ?, host = ?, pid = ?, settings = ?, "
            "machine = ? WHERE run_id = ?",
            (
                anonymizer.run_id(run_id),
                testing.SITE_KEY,
                EXAMPLE_HOST,
                anonymizer.pid(pid) if pid is not None else None,
                json.dumps(anonymizer.settings(json.loads(settings or "{}"))),
                json.dumps(anonymizer.machine(json.loads(machine or "{}"))),
                run_id,
            ),
        )
    for table in ("stage_timings", "receiver_days", "problems"):
        for (run_id,) in dst.execute(f"SELECT DISTINCT run_id FROM {table}").fetchall():
            dst.execute(
                f"UPDATE {table} SET run_id = ? WHERE run_id = ?",
                (anonymizer.run_id(run_id), run_id),
            )
    # Negative while renaming, so a new pid never meets an old one.
    pids = dst.execute(
        "SELECT DISTINCT pid FROM stage_timings WHERE pid IS NOT NULL"
    ).fetchall()
    for (pid,) in pids:
        dst.execute(
            "UPDATE stage_timings SET pid = ? WHERE pid = ?",
            (-anonymizer.pid(pid), pid),
        )
    dst.execute("UPDATE stage_timings SET pid = -pid WHERE pid < 0")
    for (message,) in dst.execute("SELECT DISTINCT message FROM problems").fetchall():
        dst.execute(
            "UPDATE problems SET message = ? WHERE message = ?",
            (anonymizer.path(message), message),
        )
    dst.execute("DELETE FROM file_index")
    dst.commit()
    dst.execute("PRAGMA journal_mode = DELETE")
    dst.execute("VACUUM")
    dst.close()


def leftovers(path: Path, forbid: list[str]) -> list[str]:
    """Every home path, foreign e-mail or forbidden text left in the file."""
    found = []
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            for row in db.execute(f"SELECT * FROM {table}"):
                for value in row:
                    if not isinstance(value, str):
                        continue
                    found += [
                        f"{table}: {m.group(0)}" for m in HOME_PATH.finditer(value)
                    ]
                    found += [
                        f"{table}: {m.group(0)}"
                        for m in EMAIL.finditer(value)
                        if m.group(0) != testing.PERSON_EMAIL
                    ]
                    found += [
                        f"{table}: {text!r}"
                        for text in forbid
                        if text.lower() in value.lower()
                    ]
    return sorted(set(found))


def main() -> None:
    """Parse the arguments, write the copy and check it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="run_history.sqlite to read")
    parser.add_argument("out", type=Path, help="anonymized copy to write")
    parser.add_argument(
        "--path-prefix",
        required=True,
        help="folder the runs' paths start with; moved to " + EXAMPLE_ROOT,
    )
    parser.add_argument(
        "--forbid",
        action="append",
        default=[],
        help="text that must not be left in the copy (repeatable), "
        "for example a user, host, institution or site name",
    )
    args = parser.parse_args()
    anonymize(args.source, args.out, args.path_prefix)
    found = leftovers(args.out, args.forbid)
    if found:
        args.out.unlink()
        sys.exit("Not anonymized, the copy is deleted. Left over:\n" + "\n".join(found))
    print(f"{args.out}: {args.out.stat().st_size / 1e6:.1f} MB, nothing left over")


if __name__ == "__main__":
    main()
