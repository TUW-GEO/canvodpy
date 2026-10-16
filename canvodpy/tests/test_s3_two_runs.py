"""Two runs write one S3 store at the same time, without a lock (#358).

Two ``canvodpy run`` processes write the same receivers' days into one
store on S3: one day both runs hold (some files in both), and the day
before it, which only the first run holds. The grilling on two writers
(Q16, Q18, Q33) decided: if this passes, S3 stays without a commit lock.

The second day is synthetic: the test day's files with every date moved
one day on (the epochs, the header and the file name), so the data are
the same and only the time differs. The orbit files of both days are in
the test data.

Against a real S3 service, as ``test_s3_run.py``: CI runs it against an
S3 emulator (RustFS, ``.github/workflows/test_s3.yml``). It needs
``CANVOD_TEST_S3_URL`` (``s3://bucket/prefix``, a bucket that exists) and
the ``AWS_*`` variables the service needs; without the URL it is skipped.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from canvod.store import MyIcechunkStore
from canvod.store_metadata.io import read_metadata
from canvod.utils import testing

S3_URL = os.environ.get("CANVOD_TEST_S3_URL", "")

_TEST_DATA = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
    / "valid"
)
_ROSALIA = _TEST_DATA / "rinex_v3_04" / "01_Rosalia"
_AUX = _TEST_DATA / "aux_data"
_RECEIVERS = {
    "reference_01": "01_reference/01_GNSS/01_raw",
    "canopy_01": "02_canopy/01_GNSS/01_raw",
}
# Two hours of each day: enough for two runs to meet, short enough for CI.
_FILES_PER_DAY = 8
_EPOCHS_PER_FILE = 180  # 15 min at 5 s

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not S3_URL,
        reason=(
            "No S3 service: set CANVOD_TEST_S3_URL=s3://bucket/prefix and the "
            "AWS_* variables to run the S3 tests (see the module docstring)."
        ),
    ),
    pytest.mark.skipif(not _ROSALIA.exists(), reason="Test data missing"),
]


def _next_day(text: str) -> str:
    """Move every date of a RINEX 3 observation file from 2025-01-01 to 01-02."""
    # Epoch records (RINEX 3.04, section 5.2.3) and the TIME OF FIRST/LAST
    # OBS header records (Table A2).
    text = re.sub(r"^> 2025 01 01 ", "> 2025 01 02 ", text, flags=re.MULTILINE)
    return re.sub(
        r"^(  2025     1)     1(.*TIME OF (?:FIRST|LAST) OBS)",
        r"\1     2\2",
        text,
        flags=re.MULTILINE,
    )


def _day_files(day: str, receiver_dir: str, synthetic: Path) -> list[Path]:
    """The first ``_FILES_PER_DAY`` files of a receiver on ``day``."""
    source = _ROSALIA / receiver_dir / "25001"
    files = sorted(f for f in source.iterdir() if f.name.endswith(".rnx"))
    files = files[:_FILES_PER_DAY]
    if day == "2025001":
        return files
    target = synthetic / receiver_dir / "25002"
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in files:
        out = target / f.name.replace("_2025001", "_2025002")
        if not out.exists():
            out.write_text(_next_day(f.read_text()))
        moved.append(out)
    return moved


def _site_data(root: Path, files: dict[str, dict[str, slice]], synthetic: Path) -> Path:
    """A site folder with the files a run holds: ``{day: {receiver: slice}}``."""
    for day, receivers in files.items():
        for receiver, part in receivers.items():
            receiver_dir = _RECEIVERS[receiver]
            target = root / receiver_dir / day[2:]
            target.mkdir(parents=True, exist_ok=True)
            for f in _day_files(day, receiver_dir, synthetic)[part]:
                (target / f.name).symlink_to(f)
    return root


def _settings(folder: Path, data: Path, stores: str) -> Path:
    """Settings of one run: its own data and logs, the shared S3 stores."""
    path = testing.write_settings(folder)
    # The orbits and clocks of both days, so the run downloads nothing.
    for aux, pattern in (("01_SP3", "*ORB.SP3"), ("02_CLK", "*CLK.CLK")):
        (folder / "aux" / aux).mkdir(parents=True)
        for f in _AUX.joinpath(aux).glob(pattern):
            (folder / "aux" / aux / f.name).symlink_to(f)
    settings = json.loads(path.read_text())
    settings["processing"]["storage"]["stores_root_dir"] = stores
    site = settings["sites"][testing.SITE_KEY]
    site["gnss_site_data_root"] = str(data)
    site["store_description"] = "Two runs at once on the test data."
    site["latitude"] = testing.LATITUDE
    site["longitude"] = testing.LONGITUDE
    site["receivers"] = {
        "reference_01": {
            "type": "reference",
            "directory": _RECEIVERS["reference_01"],
            "paired_canopies": ["canopy_01"],
        },
        "canopy_01": {"type": "canopy", "directory": _RECEIVERS["canopy_01"]},
    }
    path.write_text(json.dumps(settings))
    return folder


def _start(config_dir: Path, start: str, end: str) -> subprocess.Popen[str]:
    """Start ``canvodpy run`` as a process of its own."""
    canvodpy = Path(sys.executable).with_name("canvodpy")
    return subprocess.Popen(
        [
            str(canvodpy),
            "run",
            "--site",
            testing.SITE_KEY,
            "--start",
            start,
            "--end",
            end,
            "--no-vod",
        ],
        env={**os.environ, "CANVOD_CONFIG_DIR": str(config_dir)},
        cwd=config_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _finish(run: subprocess.Popen[str]) -> tuple[int, str]:
    output, _ = run.communicate(timeout=900)
    return run.returncode, output


def _reported_snapshots(config_dir: Path) -> set[str]:
    """The snapshot ids a run logged for the commits it made (first 12 chars)."""
    reported = set()
    for log in (config_dir / "logs").rglob("agent*.json*"):
        for line in log.read_text().splitlines():
            event = json.loads(line)
            if event.get("event") == "batch_write_complete":
                reported.add(event["snapshot_id"])
    return reported


def _log_book(store: MyIcechunkStore, group: str):
    with store.readonly_session("main") as session:
        return store.read_metadata_table(session, group)


def _gnss_store(stores: str) -> MyIcechunkStore:
    return MyIcechunkStore(f"{stores}/{testing.SITE_KEY}/rinex")


def test_two_runs_write_one_s3_store_at_the_same_time(tmp_path, monkeypatch) -> None:
    stores = f"{S3_URL.rstrip('/')}/two-runs-{uuid.uuid4().hex}"
    synthetic = tmp_path / "synthetic"
    every_file = dict.fromkeys(_RECEIVERS, slice(None))
    # Run A: day 1, and the first six files of day 2.
    # Run B: day 2 from the third file on, so four files are in both runs.
    a = _settings(
        tmp_path / "a",
        _site_data(
            tmp_path / "data_a",
            {"2025001": every_file, "2025002": dict.fromkeys(_RECEIVERS, slice(0, 6))},
            synthetic,
        ),
        stores,
    )
    b = _settings(
        tmp_path / "b",
        _site_data(
            tmp_path / "data_b",
            {"2025002": dict.fromkeys(_RECEIVERS, slice(2, None))},
            synthetic,
        ),
        stores,
    )
    # The settings this test process reads to open the store.
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(a))

    runs = [_start(a, "2025001", "2025002"), _start(b, "2025002", "2025002")]
    for code, output in map(_finish, runs):
        assert code == 0, output

    store = _gnss_store(stores)
    history = list(store.repo.ancestry(branch="main"))

    # No commit lost: every commit a run reported is on main.
    reported = _reported_snapshots(a) | _reported_snapshots(b)
    assert reported
    assert reported <= {snapshot.id[:12] for snapshot in history}

    # Each receiver-day once, each epoch once, one log-book row per stored file.
    groups = store.list_groups()
    assert len(groups) == len(_RECEIVERS)
    for group in groups:
        epochs = store.read_group(group, drop_empty=True)["epoch"].values
        assert len(epochs) == len(set(epochs)) == 2 * _FILES_PER_DAY * _EPOCHS_PER_FILE
        # A file the other run had stored already gets a row "skipped".
        rows = _log_book(store, group)
        stored = rows.filter(rows["action"] != "skipped")["rinex_hash"]
        assert stored.len() == stored.n_unique() == 2 * _FILES_PER_DAY
        assert set(rows["rinex_hash"]) == set(stored)

    # The content settings are those the store was created with.
    created = next(
        meta.content_settings
        for snapshot in reversed(history)
        if (
            meta := read_metadata(store.store_path, snapshot_id=snapshot.id)
        ).content_settings
        is not None
    )
    assert read_metadata(store.store_path).content_settings == created


def _changed(f: Path, folder: Path) -> Path:
    """A copy of ``f`` with other content (a header comment) and the same epochs."""
    folder.mkdir(parents=True, exist_ok=True)
    text = f.read_text()
    old = "NO FURTHER PHASE SHIFT APPLIED IN THE RINEX ENCODER."
    assert old in text
    out = folder / f.name
    out.write_text(
        text.replace(old, "A CHANGED COPY FOR THE OVERLAP TEST.".ljust(len(old)))
    )
    return out


def test_of_two_runs_with_different_files_for_the_same_epochs_one_stops(
    tmp_path, monkeypatch
) -> None:
    stores = f"{S3_URL.rstrip('/')}/two-runs-{uuid.uuid4().hex}"
    first_files = dict.fromkeys(_RECEIVERS, slice(0, 4))
    a = _settings(
        tmp_path / "a",
        _site_data(tmp_path / "data_a", {"2025001": first_files}, tmp_path),
        stores,
    )
    data_b = _site_data(tmp_path / "data_b", {"2025001": first_files}, tmp_path)
    # Run B's canopy file of 00:15 has other content than run A's.
    canopy = data_b / _RECEIVERS["canopy_01"] / "25001"
    original = sorted(canopy.iterdir())[1]
    changed = _changed(original.resolve(), tmp_path / "changed")
    original.unlink()
    original.symlink_to(changed)
    b = _settings(tmp_path / "b", data_b, stores)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(a))

    runs = [_start(a, "2025001", "2025001"), _start(b, "2025001", "2025001")]
    results = list(map(_finish, runs))

    # One run stores the day; the other finds the other file stored and stops.
    codes = sorted(code for code, _ in results)
    assert codes[0] == 0
    assert codes[1] != 0, [output for _, output in results]
    stopped = next(output for code, output in results if code != 0)
    assert original.name in stopped, stopped
    assert "gnss_store_strategy: overwrite" in stopped

    store = _gnss_store(stores)
    canopy_group = next(g for g in store.list_groups() if g == "canopy_01")
    epochs = store.read_group(canopy_group, drop_empty=True)["epoch"].values
    assert len(epochs) == len(set(epochs)) == 4 * _EPOCHS_PER_FILE
    rows = _log_book(store, canopy_group)
    stored = rows.filter(rows["action"] != "skipped")["rinex_hash"]
    assert stored.len() == stored.n_unique() == 4
