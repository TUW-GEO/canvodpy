"""Build the reference stores, or run the profiles again and compare (spec #318).

Every setting profile is a settings folder under ``reference/profiles/``.
Its ``reference-runs.yaml`` names the sites to run and their days. A run is
``canvodpy run --config-dir <profile>`` from the root of the repository, the
same entry point users run (seam A); this script only adds the output
folders (stores, auxiliary files, logs) and the site's SIDs (``sids`` in
``reference-runs.yaml``) as a settings file passed with ``--config``, one
per site, and copies the orbit and clock files of the test data into the
auxiliary folder, so no run downloads anything. A list in that file
replaces the profile's list. A site whose test files
carry no receiver position (MOFLUX) sets ``fill_header_position: true``
in ``reference-runs.yaml``: the build copies its files into the output
folder with the made-up test position (``canvod.utils.testing``) in the
header and runs on the copies. canvodpy itself needs the position in the
files.

A profile that changes one setting of another profile names it as
``base`` in its ``reference-runs.yaml`` and holds no settings file of its
own: its runs use the base's settings folder, with the profile's
``settings`` merged in through the per-site settings file. Its ``sites``
pick sites of the base; an entry's keys replace the base entry's keys,
so ``rosalia_sbf: {}`` runs that site with the base's days and SIDs.

    build OUT [PROFILE ...]
                  build the stores of every profile, or of the named
                  ones, into OUT/<profile>/
    pack BUILD OUT
                  write one zip per store of a build of every profile into
                  OUT/<profile>/<site>-<gnss|vod>.zip and their sha256 into
                  OUT/SHA256SUMS, the files to upload to Hugging Face
    check [REF]   run every profile again into a temporary folder and
                  compare each store with the reference stores using
                  canvod.store.compare_stores; writes the report and exits
                  1 on a difference. REF is a build folder or a folder of
                  packed zips; without REF the check downloads the
                  published zips (``published.yaml`` in
                  ``canvodpy/src/canvodpy/reference-stores/``)

The zips are deterministic: the same build gives the same sha256. They
hold only the stores; ``pack`` refuses a store that holds a local path
(the build folder, the repository, the home folder). A check takes the
settings of its own runs, so the reference stores need no settings files.
The download, sha256 check and cache are those of the demo data
(``canvodpy.demo.fetch_archive``).

Called by ``just reference-stores``, ``just reference-pack`` and
``just reference-check``.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from compression import zstd
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from canvod.store import MyIcechunkStore

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "reference" / "profiles"
TEST_DATA = ROOT / "packages" / "canvod-readers" / "tests" / "test_data" / "valid"
AUX_FOLDERS = {"01_SP3": "*_ORB.SP3", "02_CLK": "*_CLK.CLK"}
RUNS_FILE = "reference-runs.yaml"
SUMS_FILE = "SHA256SUMS"
# Fixed time of every zip member, so a zip depends on the files only.
FIXED_TIME = (2025, 1, 1, 0, 0, 0)
# canvodpy's commit lock of a store: an empty file, not part of the data.
SKIPPED_FILES = frozenset({".canvodpy-commit.lock"})
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
#: Environment fields a commit fills only with processing.metadata.record_machine.
MACHINE_FIELDS = ("hostname", "os", "arch", "cpu_count", "memory_gb", "disk_free_gb")


def profiles() -> list[Path]:
    """The profile folders, by name."""
    return sorted(p for p in PROFILES.iterdir() if (p / RUNS_FILE).is_file())


def read_runs(profile: Path) -> tuple[Path, dict, dict]:
    """The settings folder, the site runs and the extra settings of ``profile``.

    For a profile with a ``base``, the settings folder is the base's, each
    site's entry is the base's entry updated with the profile's, and the
    extra settings are the base's extra settings with the profile's
    ``settings`` merged in, so a chain of bases keeps every change.
    """
    runs = yaml.safe_load((profile / RUNS_FILE).read_text(encoding="utf-8"))
    base = runs.get("base")
    if base is None:
        return profile, runs["sites"], {}
    base_dir, base_sites, base_extra = read_runs(PROFILES / base)
    sites = {}
    for site, entry in runs["sites"].items():
        if site not in base_sites:
            msg = f"{profile.name}: site {site} is not in the base profile {base}"
            raise SystemExit(msg)
        sites[site] = {**base_sites[site], **(entry or {})}
    return base_dir, sites, merge(base_extra, runs.get("settings") or {})


def merge(into: dict, extra: dict) -> dict:
    """``into`` with the keys of ``extra`` merged in, nested mappings too."""
    merged = dict(into)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def copy_aux(aux: Path) -> None:
    """Copy the orbit and clock files of the test data into ``aux``.

    Copies, not links: links need extra rights on Windows.
    """
    for folder, pattern in AUX_FOLDERS.items():
        (aux / folder).mkdir(parents=True, exist_ok=True)
        for f in sorted((TEST_DATA / "aux_data" / folder).glob(pattern)):
            shutil.copy2(f, aux / folder / f.name)


def copy_with_position(source: Path, target: Path) -> Path:
    """Copy a site's RINEX files to ``target`` with the test position.

    Only the ``APPROX POSITION XYZ`` line changes: it gets the made-up
    position of ``canvod.utils.testing``. Returns ``target``. Stops with
    the file's name when a header has no such line.
    """
    from canvod.utils.testing import ECEF_X, ECEF_Y, ECEF_Z

    xyz = (ECEF_X, ECEF_Y, ECEF_Z)
    line = "".join(f"{v:14.4f}" for v in xyz).ljust(60) + "APPROX POSITION XYZ"
    for f in sorted(p for p in source.rglob("*") if p.is_file()):
        copy = target / f.relative_to(source)
        copy.parent.mkdir(parents=True, exist_ok=True)
        lines = f.read_text(encoding="ascii", newline="").splitlines(keepends=True)
        for i, old in enumerate(lines):
            if old.rstrip("\r\n").endswith("APPROX POSITION XYZ"):
                lines[i] = line + "\n"
                break
            if old.rstrip("\r\n").endswith("END OF HEADER"):
                raise SystemExit(f"{f}: the header has no APPROX POSITION XYZ line.")
        else:
            raise SystemExit(f"{f}: no APPROX POSITION XYZ line, no END OF HEADER.")
        copy.write_text("".join(lines), encoding="ascii", newline="")
    return target


def output_settings(
    out: Path,
    site: str,
    sids: list[str] | None,
    data_root: Path | None,
    extra: dict,
) -> Path:
    """Write the settings file of one site's run into ``out``.

    It holds the profile's ``extra`` settings and points the output into
    ``out``; ``sids`` replaces the profile's SID list and ``data_root`` the
    site's data folder.
    """
    settings: dict = {
        "processing": {
            "storage": {
                "stores_root_dir": str(out / "stores"),
                "aux_data_dir": str(out / "aux"),
            },
            "logging": {"log_dir": str(out / "logs")},
        }
    }
    if sids:
        settings["sids"] = {"mode": "custom", "custom_sids": sids}
    if data_root is not None:
        settings["sites"] = {site: {"gnss_site_data_root": str(data_root)}}
    path = out / f"settings-{site}.yaml"
    path.write_text(yaml.safe_dump(merge(extra, settings)), encoding="utf-8")
    return path


def build_profile(profile: Path, out: Path) -> float:
    """Run every site of ``profile`` into ``out``; return the seconds taken."""
    if out.exists():
        msg = f"{out} exists: build into an empty folder"
        raise SystemExit(msg)
    out.mkdir(parents=True)
    copy_aux(out / "aux")
    settings_dir, sites, extra = read_runs(profile)
    settings = yaml.safe_load(
        (settings_dir / "canvod-settings.yaml").read_text(encoding="utf-8")
    )
    overlays = {}
    for site, days in sites.items():
        data_root = None
        if days.get("fill_header_position"):
            root = ROOT / settings["sites"][site]["gnss_site_data_root"]
            data_root = copy_with_position(root, out / "data" / site)
        overlays[site] = output_settings(out, site, days.get("sids"), data_root, extra)
    started = time.perf_counter()
    for site, days in sites.items():
        command = [
            "canvodpy",
            "run",
            "--config-dir",
            str(settings_dir),
            "--config",
            str(overlays[site]),
            "--site",
            site,
            "--start",
            str(days["start"]),
            "--end",
            str(days["end"]),
            "--label",
            f"reference {profile.name}",
        ]
        print(f"{profile.name}/{site}: {' '.join(command[2:])}", flush=True)
        log = out / f"run-{site}.txt"
        site_started = time.perf_counter()
        with log.open("w", encoding="utf-8") as stream:
            done = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        if done.returncode != 0:
            msg = f"{profile.name}/{site} failed (exit {done.returncode}); see {log}"
            raise SystemExit(msg)
        seconds = time.perf_counter() - site_started
        print(f"{profile.name}/{site}: ran in {seconds:.0f} s", flush=True)
    return time.perf_counter() - started


def stores_of(
    profile: Path, out: Path, root: Path | None = None
) -> dict[str, MyIcechunkStore | None]:
    """The stores a build of ``profile`` wrote, by name; ``None`` if missing.

    The stores are those of the build in ``out``, or, with ``root``, the
    stores at the same places under ``root``, opened with the settings of
    the build in ``out``.
    """
    from canvod.config import load_config
    from canvod.store import MyIcechunkStore

    settings_dir, sites, _ = read_runs(profile)
    found = {}
    for site in sites:
        config = load_config(
            config_dir=settings_dir, config_file=out / f"settings-{site}.yaml"
        )
        storage = config.processing.storage
        for kind, path in (
            ("gnss", storage.get_gnss_store_path(site)),
            ("vod", storage.get_vod_store_path(site)),
        ):
            if root is not None:
                path = root / Path(path).resolve().relative_to(out.resolve())
            found[f"{site}/{kind}"] = (
                MyIcechunkStore(path, store_type=f"{kind}_store", config=config)
                if Path(path).exists()
                else None
            )
    return found


def compare_profile(profile: Path, reference: Path, new: Path) -> str:
    """Compare the stores of two builds of ``profile``; return the report."""
    from canvod.store import compare_stores

    lines = []
    new_stores = stores_of(profile, new)
    for name, ref_store in stores_of(profile, new, root=reference).items():
        new_store = new_stores[name]
        if ref_store is None or new_store is None:
            which = "reference stores" if ref_store is None else "new build"
            lines.append(f"## {profile.name}/{name}\nNot in the {which}.")
            continue
        text = compare_stores(ref_store, new_store).to_text()
        if text:
            lines.append(f"## {profile.name}/{name}\n{text}")
    return "\n\n".join(lines)


def build(out: Path, names: list[str]) -> None:
    out = out.resolve()
    chosen = profiles()
    if names:
        unknown = sorted(set(names) - {p.name for p in chosen})
        if unknown:
            raise SystemExit(f"No such profile: {', '.join(unknown)}")
        chosen = [p for p in chosen if p.name in names]
    for profile in chosen:
        seconds = build_profile(profile, out / profile.name)
        print(f"{profile.name}: built in {seconds:.0f} s into {out / profile.name}")


def require_profiles(folder: Path) -> None:
    """Stop unless ``folder`` holds a build of every profile."""
    missing = [p.name for p in profiles() if not (folder / p.name).is_dir()]
    if missing:
        msg = (
            f"{folder} holds no stores of the profiles: {', '.join(missing)}. "
            f"Build them with `just reference-stores {folder} "
            f"{' '.join(missing)}`."
        )
        raise SystemExit(msg)


def holds_local_path(path: Path, needles: tuple[bytes, ...]) -> bool:
    """Whether the file ``path`` holds one of ``needles``.

    Most store files (Icechunk's metadata, the chunks) are zstd frames;
    those are searched after decompressing. A file whose frame does not
    decompress stops the pack: it could not be searched.
    """
    data = path.read_bytes()
    start = data.find(ZSTD_MAGIC)
    if start >= 0:
        try:
            data += zstd.decompress(data[start:])
        except zstd.ZstdError as exc:
            msg = f"{path} could not be decompressed to be searched: {exc}"
            raise SystemExit(msg) from exc
    return any(needle in data for needle in needles)


def this_machine() -> tuple[str, ...]:
    """This computer's host name, user name and platform string."""
    names = (socket.gethostname(), getpass.getuser(), platform.platform())
    return tuple(name for name in names if name)


def machine_trace(store: Path, names: tuple[str, ...]) -> str | None:
    """What in ``store`` records a computer, or ``None``.

    Walks every snapshot of every branch: a commit's environment must
    leave the computer out (``processing.metadata.record_machine:
    false``), and neither its metadata, the root attributes nor the
    repository metadata may name ``names``.
    """
    import icechunk
    import zarr
    from zarr.errors import GroupNotFoundError

    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store)))
    words = [re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])") for name in names]

    def named(text: str) -> str | None:
        return next(
            (n for n, w in zip(names, words, strict=True) if w.search(text)), None
        )

    if name := named(json.dumps(repo.get_metadata(), default=str)):
        return f"its repository metadata names {name!r}"
    seen = set()
    for branch in sorted(repo.list_branches()):
        for snapshot in repo.ancestry(branch=branch):
            if snapshot.id in seen:
                continue
            seen.add(snapshot.id)
            environment = (snapshot.metadata or {}).get("environment") or {}
            recorded = [f for f in MACHINE_FIELDS if environment.get(f) is not None]
            if recorded:
                return (
                    f"commit {snapshot.id} records the computer "
                    f"({', '.join(recorded)}); build it with "
                    "processing.metadata.record_machine: false"
                )
            session = repo.readonly_session(snapshot_id=snapshot.id)
            try:
                attrs = dict(zarr.open_group(session.store, mode="r").attrs)
            except GroupNotFoundError:  # the first snapshot
                attrs = {}
            text = json.dumps([snapshot.metadata, attrs], default=str)
            if name := named(text):
                return f"commit {snapshot.id} names {name!r}"
    return None


def pack(build: Path, out: Path) -> None:
    build, out = build.resolve(), out.resolve()
    require_profiles(build)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty: pack into an empty folder")
    sums = {}
    for profile in profiles():
        folder = build / profile.name
        local = {build, folder.resolve(), ROOT, Path.home()}
        # The user name is too short to look for in the chunks' bytes;
        # machine_trace looks for it in the metadata. A short host name
        # can match chunk bytes by chance too; the pack then stops and
        # names the file, so a false match is seen, never missed.
        machine = (socket.gethostname(), platform.platform())
        needles = tuple(str(p).encode() for p in (*local, *machine) if p)
        stores = sorted(p for p in (folder / "stores").glob("*/*") if p.is_dir())
        for store in stores:
            files = sorted(
                f
                for f in store.rglob("*")
                if f.is_file() and f.name not in SKIPPED_FILES
            )
            leaks = [f for f in files if holds_local_path(f, needles)]
            if leaks:
                where = leaks[0].relative_to(build)
                msg = (
                    f"{where} holds a local path or names this computer; "
                    "nothing more was packed"
                )
                raise SystemExit(msg)
            if found := machine_trace(store, this_machine()):
                msg = f"{store.relative_to(build)}: {found}; nothing more was packed"
                raise SystemExit(msg)
            name = f"{profile.name}/{store.parent.name}-{store.name}.zip"
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # Stored, not deflated: the files are compressed already, and
            # the bytes then don't depend on the zlib version.
            with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as zf:
                for f in files:
                    info = zipfile.ZipInfo(f.relative_to(folder).as_posix(), FIXED_TIME)
                    info.external_attr = 0o644 << 16
                    info.create_system = 3  # Unix, whatever system packs
                    zf.writestr(info, f.read_bytes())
            with target.open("rb") as stream:
                sums[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            size = target.stat().st_size / 1e6
            print(f"{name}  {len(files)} files  {size:.1f} MB  sha256 {sums[name]}")
    lines = "".join(f"{sha256}  {name}\n" for name, sha256 in sorted(sums.items()))
    (out / SUMS_FILE).write_text(lines, encoding="utf-8")
    print(f"{len(sums)} zips and {SUMS_FILE} in {out}")


def reference_folder(reference: Path | None, work: Path) -> Path:
    """The folder with a build of every profile to compare with.

    ``reference`` is a build folder, used as it is; a folder of packed zips
    (it holds ``SHA256SUMS``), unpacked into ``work``; or ``None``: the
    published zips, downloaded and unpacked into the user cache folder.
    Every zip's sha256 is checked before it is unpacked.
    """
    from canvodpy.demo import (
        fetch_archive,
        published_reference,
        read_sums,
        reference_cache_dir,
    )

    if reference is None:
        published = published_reference()
        sums = published.sums
        urls = {name: published.url(name) for name in sums}
        root = reference_cache_dir(published.revision)
    elif (reference / SUMS_FILE).is_file():
        sums = read_sums(reference / SUMS_FILE)
        urls = {name: (reference / name).resolve().as_uri() for name in sums}
        root = work / "reference"
    else:
        return reference.resolve()
    for name, sha256 in sums.items():
        profile, file = name.split("/")
        fetch_archive(file, urls[name], sha256, root / profile)
    return root


def check(reference: Path | None, report: Path | None) -> int:
    work = Path(tempfile.mkdtemp(prefix="canvodpy-reference-check-"))
    reports = []
    try:
        reference = reference_folder(reference, work)
        require_profiles(reference)
        for profile in profiles():
            started = time.perf_counter()
            build_profile(profile, work / profile.name)
            text = compare_profile(
                profile, reference / profile.name, work / profile.name
            )
            seconds = time.perf_counter() - started
            print(f"{profile.name}: checked in {seconds:.0f} s", flush=True)
            if text:
                reports.append(text)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = "\n\n".join(reports)
    if report is not None:
        report.write_text(text + "\n" if text else "", encoding="utf-8")
    if text:
        print(f"The stores differ from the reference stores:\n\n{text}")
        return 1
    print("The stores match the reference stores.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build", help="build the reference stores")
    build_parser.add_argument("out", type=Path, help="empty folder for the stores")
    build_parser.add_argument(
        "profile", nargs="*", help="build only these profiles (default: all)"
    )
    pack_parser = sub.add_parser("pack", help="zip the stores of a build")
    pack_parser.add_argument("build", type=Path, help="folder of a build")
    pack_parser.add_argument("out", type=Path, help="empty folder for the zips")
    check_parser = sub.add_parser("check", help="compare a new build with them")
    check_parser.add_argument(
        "reference",
        type=Path,
        nargs="?",
        help="folder of a build or of packed zips (default: the published zips)",
    )
    check_parser.add_argument(
        "--report", type=Path, help="write the report here (empty if they match)"
    )
    args = parser.parse_args()
    if args.command == "build":
        build(args.out, args.profile)
        return 0
    if args.command == "pack":
        pack(args.build, args.out)
        return 0
    return check(args.reference, args.report)


if __name__ == "__main__":
    sys.exit(main())
