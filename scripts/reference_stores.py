"""Build the reference stores, or run the profiles again and compare (spec #318).

Every setting profile is a settings folder under ``reference/profiles/``.
Its ``reference-runs.yaml`` names the sites to run and their days. A run is
``canvodpy run --config-dir <profile>`` from the root of the repository, the
same entry point users run (seam A); this script only adds the output
folders (stores, auxiliary files, logs) as a settings file passed with
``--config``, and links the orbit and clock files of the test data into the
auxiliary folder, so no run downloads anything.

    build OUT     build the stores of every profile into OUT/<profile>/
    check REF     run every profile again into a temporary folder and
                  compare each store with REF/<profile>/ using
                  canvod.store.compare_stores; writes the report and exits
                  1 on a difference

Called by ``just reference-stores`` and ``just reference-check``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
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


def profiles() -> list[Path]:
    """The profile folders, by name."""
    return sorted(p for p in PROFILES.iterdir() if (p / RUNS_FILE).is_file())


def copy_aux(aux: Path) -> None:
    """Copy the orbit and clock files of the test data into ``aux``.

    Copies, not links: links need extra rights on Windows.
    """
    for folder, pattern in AUX_FOLDERS.items():
        (aux / folder).mkdir(parents=True, exist_ok=True)
        for f in sorted((TEST_DATA / "aux_data" / folder).glob(pattern)):
            shutil.copy2(f, aux / folder / f.name)


def output_settings(out: Path) -> Path:
    """Write the settings file that points a run's output into ``out``."""
    settings = {
        "processing": {
            "storage": {
                "stores_root_dir": str(out / "stores"),
                "aux_data_dir": str(out / "aux"),
            },
            "logging": {"log_dir": str(out / "logs")},
        }
    }
    path = out / "output-settings.yaml"
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    return path


def build_profile(profile: Path, out: Path) -> float:
    """Run every site of ``profile`` into ``out``; return the seconds taken."""
    if out.exists():
        msg = f"{out} exists: build into an empty folder"
        raise SystemExit(msg)
    out.mkdir(parents=True)
    copy_aux(out / "aux")
    overlay = output_settings(out)
    runs = yaml.safe_load((profile / RUNS_FILE).read_text(encoding="utf-8"))
    started = time.perf_counter()
    for site, days in runs["sites"].items():
        command = [
            "canvodpy",
            "run",
            "--config-dir",
            str(profile),
            "--config",
            str(overlay),
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
        with log.open("w", encoding="utf-8") as stream:
            done = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        if done.returncode != 0:
            msg = f"{profile.name}/{site} failed (exit {done.returncode}); see {log}"
            raise SystemExit(msg)
    return time.perf_counter() - started


def stores_of(profile: Path, out: Path) -> dict[str, MyIcechunkStore | None]:
    """The stores a build of ``profile`` wrote, by name; ``None`` if missing."""
    from canvod.config import load_config
    from canvod.store import MyIcechunkStore

    config = load_config(config_dir=profile, config_file=out / "output-settings.yaml")
    storage = config.processing.storage
    runs = yaml.safe_load((profile / RUNS_FILE).read_text(encoding="utf-8"))
    found = {}
    for site in runs["sites"]:
        for kind, path in (
            ("gnss", storage.get_gnss_store_path(site)),
            ("vod", storage.get_vod_store_path(site)),
        ):
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
    for name, ref_store in stores_of(profile, reference).items():
        new_store = new_stores[name]
        if ref_store is None or new_store is None:
            which = "reference stores" if ref_store is None else "new build"
            lines.append(f"## {profile.name}/{name}\nNot in the {which}.")
            continue
        text = compare_stores(ref_store, new_store).to_text()
        if text:
            lines.append(f"## {profile.name}/{name}\n{text}")
    return "\n\n".join(lines)


def build(out: Path) -> None:
    out = out.resolve()
    for profile in profiles():
        seconds = build_profile(profile, out / profile.name)
        print(f"{profile.name}: built in {seconds:.0f} s into {out / profile.name}")


def check(reference: Path, report: Path | None) -> int:
    reference = reference.resolve()
    work = Path(tempfile.mkdtemp(prefix="canvodpy-reference-check-"))
    reports = []
    try:
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
    check_parser = sub.add_parser("check", help="compare a new build with them")
    check_parser.add_argument("reference", type=Path, help="folder of a build")
    check_parser.add_argument(
        "--report", type=Path, help="write the report here (empty if they match)"
    )
    args = parser.parse_args()
    if args.command == "build":
        build(args.out)
        return 0
    return check(args.reference, args.report)


if __name__ == "__main__":
    sys.exit(main())
