"""canvodpy logs collect: a copy of the log folder, to send on (#131).

An unattended run leaves its log folder on the machine it ran on. The
command copies it to one folder, which the operator then sends on with
rsync or scp.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from canvodpy.cli.app import main_app
from canvodpy.run_history import RunHistory, run_history_path
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils import testing

runner = CliRunner()

RUN = "fangorn-20261106-030000-3f9a1c"


@pytest.fixture(autouse=True)
def _clear_config_cache():
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


def _config_dir(tmp_path, log_dir):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": {
                        "author": testing.PERSON_NAME,
                        "email": testing.PERSON_EMAIL,
                        "institution": testing.INSTITUTION,
                    },
                    "logging": {"log_dir": str(log_dir)},
                    "storage": {"stores_root_dir": str(tmp_path / "stores")},
                },
                "sites": {
                    testing.SITE_KEY: {
                        "gnss_site_data_root": str(tmp_path / "raw"),
                        "receivers": {
                            "canopy_01": {"type": "canopy", "directory": "canopy"},
                        },
                    }
                },
            }
        )
    )
    return config_dir


def _start(history: RunHistory, run_id: str) -> None:
    history.start_run(
        run_id,
        site=testing.SITE_KEY,
        settings={"processing": {"n_max_threads": 4}},
        canvodpy_version="1.0.0",
        commit="abc1234",
        machine={"cpu": "test CPU", "cores": 8},
        workers=4,
    )


def _collect(config_dir, *args):
    return runner.invoke(
        main_app,
        ["logs", "collect", *map(str, args)],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )


def test_a_copy_taken_during_a_run_holds_its_newest_records(tmp_path):
    log_dir = tmp_path / "logs"
    (log_dir / "human").mkdir(parents=True)
    (log_dir / "machine").mkdir()
    (log_dir / "human" / "main.log").write_text("a readable line\n")
    (log_dir / "machine" / "agent.json.1").write_text('{"event": "older"}\n')
    dest = tmp_path / "collected"

    # The run is still going: its records are in the WAL file, not yet
    # merged into run_history.sqlite.
    with RunHistory.open(log_dir) as history:
        _start(history, RUN)
        assert (
            run_history_path(log_dir).with_name("run_history.sqlite-wal").stat().st_size
        )
        result = _collect(_config_dir(tmp_path, log_dir), dest)

    assert result.exit_code == 0, result.output
    assert (dest / "human" / "main.log").read_text() == "a readable line\n"
    assert (dest / "machine" / "agent.json.1").read_text() == '{"event": "older"}\n'
    assert sorted(p.name for p in dest.glob("run_history*")) == ["run_history.sqlite"]
    with RunHistory.open(dest, read_only=True) as copy:
        assert [run.run_id for run in copy.runs()] == [RUN]


def _event(run_id: str, event: str, timestamp: str) -> str:
    return json.dumps({"event": event, "run_id": run_id, "timestamp": timestamp})


def test_one_run_keeps_its_events_from_the_main_process_and_the_workers(tmp_path):
    other = "fangorn-20261105-030000-77b2e0"
    log_dir = tmp_path / "logs"
    machine = log_dir / "machine"
    machine.mkdir(parents=True)
    (log_dir / "human").mkdir()
    (log_dir / "human" / "main.log").write_text("both runs\n")
    # The main process, its older rotated file, and one worker
    (machine / "agent.json").write_text(
        "\n".join(
            [
                _event(RUN, "run_finished", "2026-11-06T03:09:00Z"),
                _event(other, "run_finished", "2026-11-05T03:09:00Z"),
            ]
        )
        + "\n"
    )
    (machine / "agent.json.1").write_text(
        _event(RUN, "run_started", "2026-11-06T03:00:00Z") + "\n"
    )
    (machine / "agent.12345.json").write_text(
        _event(RUN, "task_failed", "2026-11-06T03:05:00Z")
        + "\n"
        + _event(other, "task_failed", "2026-11-05T03:05:00Z")
        + "\n"
    )
    with RunHistory.open(log_dir) as history:
        _start(history, RUN)
        _start(history, other)
    dest = tmp_path / "collected"

    result = _collect(_config_dir(tmp_path, log_dir), dest, "--run-id", RUN)

    assert result.exit_code == 0, result.output
    events = [
        json.loads(line) for line in (dest / f"{RUN}.json").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == [
        "run_started",
        "task_failed",
        "run_finished",
    ]
    assert {e["run_id"] for e in events} == {RUN}
    assert sorted(p.name for p in dest.iterdir()) == [
        f"{RUN}.json",
        "run_history.sqlite",
    ]
    with RunHistory.open(dest, read_only=True) as copy:
        assert [run.run_id for run in copy.runs()] == [RUN]


def _rotate_before(call, rotated):
    """*call*: on another log file next to *rotated*, a running run's log
    handler first deletes *rotated*, as its rotation does."""

    def wrapped(path, *args, **kwargs):
        if Path(path).parent == rotated.parent and Path(path) != rotated:
            rotated.unlink(missing_ok=True)
        return call(path, *args, **kwargs)

    return wrapped


def test_a_log_file_that_rotates_away_during_the_copy_is_skipped(tmp_path, monkeypatch):
    machine = tmp_path / "logs" / "machine"
    machine.mkdir(parents=True)
    (machine / "agent.json").write_text('{"event": "newest"}\n')
    (machine / "agent.json.150").write_text('{"event": "oldest"}\n')
    dest = tmp_path / "collected"
    # The files are listed, then the handler deletes agent.json.150
    monkeypatch.setattr(
        shutil, "copy2", _rotate_before(shutil.copy2, machine / "agent.json.150")
    )

    result = _collect(_config_dir(tmp_path, tmp_path / "logs"), dest)

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in (dest / "machine").iterdir()) == ["agent.json"]
    assert "1 log file was rotated away during the copy" in result.output


def test_one_run_skips_a_log_file_that_rotates_away(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    machine = log_dir / "machine"
    machine.mkdir(parents=True)
    (machine / "agent.json").write_text(
        _event(RUN, "run_started", "2026-11-06T03:00:00Z") + "\n"
    )
    (machine / "agent.json.150").write_text(
        _event(RUN, "older", "2026-11-06T02:00:00Z") + "\n"
    )
    with RunHistory.open(log_dir) as history:
        _start(history, RUN)
    dest = tmp_path / "collected"
    monkeypatch.setattr(
        Path, "open", _rotate_before(Path.open, machine / "agent.json.150")
    )

    result = _collect(_config_dir(tmp_path, log_dir), dest, "--run-id", RUN)

    assert result.exit_code == 0, result.output
    events = [
        json.loads(line) for line in (dest / f"{RUN}.json").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == ["run_started"]


def test_a_folder_that_is_not_empty_is_refused(tmp_path):
    log_dir = tmp_path / "logs"
    (log_dir / "human").mkdir(parents=True)
    (log_dir / "human" / "main.log").write_text("new\n")
    dest = tmp_path / "collected"
    dest.mkdir()
    (dest / "main.log").write_text("kept\n")

    result = _collect(_config_dir(tmp_path, log_dir), dest)

    assert result.exit_code == 1
    assert "is not empty" in result.output
    assert sorted(p.name for p in dest.iterdir()) == ["main.log"]
    assert (dest / "main.log").read_text() == "kept\n"


def test_a_run_the_run_history_does_not_know_is_refused(tmp_path):
    log_dir = tmp_path / "logs"
    with RunHistory.open(log_dir) as history:
        _start(history, RUN)
    dest = tmp_path / "collected"

    result = _collect(
        _config_dir(tmp_path, log_dir), dest, "--run-id", "fangorn-unknown"
    )

    assert result.exit_code == 1
    assert "has no run fangorn-unknown" in result.output
    assert not dest.exists()


def test_a_log_folder_that_does_not_exist_is_refused(tmp_path):
    log_dir = tmp_path / "logs"

    result = _collect(_config_dir(tmp_path, log_dir), tmp_path / "collected")

    assert result.exit_code == 1
    assert "doesn't exist" in result.output
    assert not log_dir.exists()
