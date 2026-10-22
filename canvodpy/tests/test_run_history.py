"""The run history (ADR 0018), through the functions of its module only."""

import multiprocessing
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
from canvodpy.run_history import (
    NetworkDriveError,
    RunHistory,
    RunHistoryVersionError,
)

from canvod.utils.testing import SITE_KEY
from canvodpy import run_history


def _start(history: RunHistory, run_id: str = "fangorn-20261014-120000", **kw):
    history.start_run(
        run_id,
        site=SITE_KEY,
        settings={"processing": {"n_max_threads": 4}},
        canvodpy_version="1.0.0",
        commit="abc1234",
        machine={"cpu": "test CPU", "cores": 8},
        workers=4,
        **kw,
    )


def test_opening_an_absent_run_history_creates_it(tmp_path):
    with RunHistory.open(tmp_path) as history:
        assert history.runs() == []
    assert run_history.run_history_path(tmp_path).exists()


def test_runs_are_kept_when_the_run_history_is_opened_again(tmp_path):
    with RunHistory.open(tmp_path) as history:
        _start(history, label="benchmark 4 workers")
    with RunHistory.open(tmp_path) as history:
        (run,) = history.runs()
    assert run.run_id == "fangorn-20261014-120000"
    assert run.label == "benchmark 4 workers"
    assert run.settings == {"processing": {"n_max_threads": 4}}
    assert run.machine == {"cpu": "test CPU", "cores": 8}
    assert run.workers == 4


def test_a_run_history_of_a_newer_canvodpy_is_refused(tmp_path, monkeypatch):
    # A newer canvodpy: one schema version more, with its migration step.
    with monkeypatch.context() as m:
        m.setitem(run_history._MIGRATIONS, run_history.SCHEMA_VERSION, "")
        m.setattr(run_history, "SCHEMA_VERSION", run_history.SCHEMA_VERSION + 1)
        RunHistory.open(tmp_path).close()
    with pytest.raises(RunHistoryVersionError, match="newer canvodpy"):
        RunHistory.open(tmp_path)


def test_a_finished_run_shows_its_progress_timings_and_problems(tmp_path):
    with RunHistory.open(tmp_path) as history:
        _start(history)
        rid = "fangorn-20261014-120000"
        history.plan_receiver_days(
            rid, [("canopy_01", "2025001"), ("canopy_01", "2025002")]
        )
        history.plan_receiver_days(rid, [("reference_01", "2025001")])
        assert history.run(rid).status == "running"

        history.finish_receiver_day(
            rid, "canopy_01", "2025001", "written", bytes_added=1000
        )
        history.finish_receiver_day(rid, "reference_01", "2025001", "skipped")
        history.record_stage(rid, "reading", 2.5, receiver="canopy_01", day="2025001")
        history.record_problem(
            rid, "warning", "3 files not processed", receiver="canopy_01", day="2025001"
        )
        history.end_run(rid, "finished")

        run = history.run(rid)
        progress = {p.receiver: p for p in history.progress(rid)}
        (timing,) = history.stage_timings(rid)
        (problem,) = history.problems(rid)

    assert run.status == "finished"
    assert run.ended_at is not None
    assert (progress["canopy_01"].planned, progress["canopy_01"].written) == (2, 1)
    assert progress["canopy_01"].bytes_added == 1000
    assert (progress["reference_01"].planned, progress["reference_01"].skipped) == (
        1,
        1,
    )
    assert (timing.stage, timing.seconds, timing.day) == ("reading", 2.5, "2025001")
    assert (problem.level, problem.receiver) == ("warning", "canopy_01")


def test_a_failed_run_keeps_its_error(tmp_path):
    with RunHistory.open(tmp_path) as history:
        _start(history)
        history.end_run("fangorn-20261014-120000", "failed", error="disk full")
        run = history.run("fangorn-20261014-120000")
    assert (run.status, run.error) == ("failed", "disk full")


def test_runs_are_filtered_by_site_and_label(tmp_path):
    with RunHistory.open(tmp_path) as history:
        _start(history, "fangorn-20261014-120000", label="a")
        _start(history, "fangorn-20261014-130000", label="b")
        assert [r.run_id for r in history.runs(label="a")] == [
            "fangorn-20261014-120000"
        ]
        assert [r.run_id for r in history.runs(site=SITE_KEY)] == [
            "fangorn-20261014-130000",
            "fangorn-20261014-120000",
        ]
        assert history.runs(site="isengard") == []


def test_resource_samples_are_kept_in_order(tmp_path):
    with RunHistory.open(tmp_path) as history:
        _start(history)
        rid = "fangorn-20261014-120000"
        history.record_resources(
            rid, cpu_percent=50.0, memory_percent=20.0, free_disk={"/stores": 10}
        )
        history.record_resources(
            rid, cpu_percent=70.0, memory_percent=25.0, free_disk={"/stores": 9}
        )
        samples = history.resource_samples(rid)
    assert [s.cpu_percent for s in samples] == [50.0, 70.0]
    assert samples[1].free_disk == {"/stores": 9}


def _start_and_vanish(log_dir: Path) -> None:
    history = RunHistory.open(log_dir)
    _start(history, "fangorn-20261014-140000")
    history.close()


def test_a_run_whose_process_is_gone_without_an_end_is_interrupted(tmp_path):
    process = multiprocessing.get_context("spawn").Process(
        target=_start_and_vanish, args=(tmp_path,)
    )
    process.start()
    process.join(60)
    assert process.exitcode == 0
    with RunHistory.open(tmp_path) as history:
        assert history.run("fangorn-20261014-140000").status == "interrupted"


def test_runs_started_together_on_a_new_run_history_all_open_it(tmp_path):
    # Switching a new file to WAL mode needs it alone; SQLite then fails at
    # once instead of waiting (#340). Each try: 4 openers, 1 new history.
    for trial in range(20):
        log_dir = tmp_path / str(trial)
        barrier = threading.Barrier(4)
        errors: list[Exception] = []

        def open_together(log_dir=log_dir, barrier=barrier, errors=errors):
            barrier.wait()
            try:
                with RunHistory.open(log_dir):
                    pass
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=open_together) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        assert errors == []
        with closing(sqlite3.connect(run_history.run_history_path(log_dir))) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_run_history_locked_longer_than_the_busy_timeout_is_not_opened(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(run_history, "BUSY_TIMEOUT_SECONDS", 0.5)
    path = run_history.run_history_path(tmp_path)
    with closing(sqlite3.connect(path, isolation_level=None)) as holder:
        holder.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            RunHistory.open(tmp_path)
        holder.execute("ROLLBACK")


N_ROWS = 300


def _write_timings(log_dir: Path, run_id: str) -> None:
    with RunHistory.open(log_dir) as history:
        for i in range(N_ROWS):
            history.record_stage(run_id, "reading", float(i), pid=1)


def test_a_reader_sees_committed_rows_while_processes_write(tmp_path):
    rid = "fangorn-20261014-120000"
    with RunHistory.open(tmp_path) as history:
        _start(history)

    ctx = multiprocessing.get_context("spawn")
    worker = ctx.Process(target=_write_timings, args=(tmp_path, rid))
    worker.start()

    seen = []
    with (
        RunHistory.open(tmp_path) as writer,
        RunHistory.open(tmp_path, read_only=True) as reader,
    ):
        deadline = time.monotonic() + 120
        while worker.is_alive() and time.monotonic() < deadline:
            writer.record_stage(rid, "writing", 0.1)
            seen.append(len(reader.stage_timings(rid)))
        worker.join(60)
        assert worker.exitcode == 0
        final = reader.stage_timings(rid)

    assert seen == sorted(seen)
    stages = [t.stage for t in final]
    assert stages.count("reading") == N_ROWS
    assert stages.count("writing") >= len(seen)


@pytest.mark.parametrize(
    ("fs_type", "network"),
    [
        ("nfs", True),
        ("nfs4", True),
        ("cifs", True),
        ("smbfs", True),
        ("smb3", True),
        ("remote", True),
        ("ext4", False),
        ("apfs", False),
        ("ntfs", False),
        ("", False),
    ],
)
def test_network_file_systems_are_recognized(fs_type, network):
    assert run_history.is_network_filesystem(fs_type) is network


def test_the_temporary_folder_is_a_local_disk(tmp_path):
    assert not run_history.is_network_filesystem(run_history.filesystem_type(tmp_path))


def test_opening_on_a_network_drive_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(run_history, "filesystem_type", lambda path: "cifs")
    with pytest.raises(NetworkDriveError, match=r"processing\.logging\.log_dir"):
        RunHistory.open(tmp_path)
    assert not run_history.run_history_path(tmp_path).exists()


# -- the file index (#299) -----------------------------------------------------


def _listings():
    from canvodpy.run_history import FolderListing

    return {
        ".": FolderListing(files=(), folders=("25001", "25002"), newest_day=None),
        "25001": FolderListing(
            files=("FANA01INK_R_20250010000_15M_05S_AA.rnx", "notes.txt"),
            folders=(),
            newest_day="2025001",
        ),
    }


def test_a_file_index_reads_back_as_saved(tmp_path):
    root = tmp_path / "data" / "canopy"
    with RunHistory.open(tmp_path) as history:
        history.save_file_index(root, None, _listings())
    with RunHistory.open(tmp_path) as history:
        assert history.file_index(root, None) == _listings()
        # Another receiver directory, or the same one with a recipe, has its own.
        assert history.file_index(tmp_path / "data" / "reference", None) == {}
        assert history.file_index(root, tmp_path / "recipe.yaml") == {}


def test_saving_a_file_index_replaces_the_previous_one(tmp_path):
    from canvodpy.run_history import FolderListing

    root = tmp_path / "data"
    with RunHistory.open(tmp_path) as history:
        history.save_file_index(root, None, _listings())
        only_root = {".": FolderListing(files=("a.rnx",), folders=(), newest_day=None)}
        history.save_file_index(root, None, only_root)
        assert history.file_index(root, None) == only_root


def test_a_corrupt_file_index_reads_as_empty(tmp_path):
    import sqlite3

    root = tmp_path / "data"
    with RunHistory.open(tmp_path) as history:
        history.save_file_index(root, None, _listings())
    with sqlite3.connect(run_history.run_history_path(tmp_path)) as db:
        db.execute("UPDATE file_index SET files = 'not json'")
    with RunHistory.open(tmp_path) as history:
        assert history.file_index(root, None) == {}


def test_a_run_history_of_schema_version_1_gets_the_file_index(tmp_path, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(run_history, "SCHEMA_VERSION", 1)
        with RunHistory.open(tmp_path) as history:
            _start(history)
    with RunHistory.open(tmp_path) as history:
        history.save_file_index(tmp_path, None, _listings())
        assert history.file_index(tmp_path, None) == _listings()
        assert len(history.runs()) == 1


URL = "https://raw.githubusercontent.com/the-inklings/red-book/main/recipes/x.yaml"


def test_settings_and_problems_keep_only_the_file_name_of_a_url(tmp_path):
    rid = "fangorn-20261014-120000"
    with RunHistory.open(tmp_path) as history:
        history.start_run(
            rid,
            site=SITE_KEY,
            settings={"sites": {SITE_KEY: {"receivers": {"c": {"recipe": URL}}}}},
            canvodpy_version="1.0.0",
            commit=None,
            machine={},
            workers=1,
        )
        history.record_problem(rid, "warning", f"Recipe {URL}: field 'a' is ignored.")
        history.end_run(rid, "failed", error=f"Recipe not found: {URL}.")
        run = history.run(rid)
        (problem,) = history.problems(rid)
    assert run.settings["sites"][SITE_KEY]["receivers"]["c"]["recipe"] == "x.yaml"
    assert problem.message == "Recipe x.yaml: field 'a' is ignored."
    assert run.error == "Recipe not found: x.yaml."


def test_the_file_index_of_a_recipe_follows_its_content(tmp_path):
    root = tmp_path / "data" / "canopy"
    first, second = tmp_path / "run1" / "x.yaml", tmp_path / "run2" / "x.yaml"
    for path in (first, second):
        path.parent.mkdir()
        path.write_text("name: x\n")
    with RunHistory.open(tmp_path) as history:
        history.save_file_index(root, first, _listings())
        # A recipe fetched again by the next run, in another folder.
        assert history.file_index(root, second) == _listings()
        second.write_text("name: y\n")
        assert history.file_index(root, second) == {}
