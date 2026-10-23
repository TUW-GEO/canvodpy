"""The download buttons of the run dashboard: the data behind a view, as a zip.

A zip holds the run history of the runs the view shows
(``run_history.sqlite``, only those runs), one CSV per table and chart
of the view, and a ``README.txt`` that says what the files are. The CSVs
are the rows the dashboard drew; the run history holds every record of
those runs, so a figure can be made again from the zip alone. Unzipped,
the folder opens as a log folder: ``canvodpy dashboard --logs-dir
<folder>``.

The zip is built here, outside the marimo notebook (``performance.py``),
so a test can check it without running the notebook.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import canvodpy
from canvodpy.run_history import FILE_NAME, RunHistory


def _cell(value: Any) -> Any:
    """One CSV cell: times in ISO 8601, dicts and lists as JSON."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def table_csv(rows: list[dict[str, Any]]) -> str:
    """The rows of one table or chart as CSV text, columns in first-seen order."""
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(value) for key, value in row.items()})
    return out.getvalue()


def _readme(
    title: str,
    log_dir: Path,
    run_ids: list[str],
    tables: dict[str, str],
    made_at: datetime,
) -> str:
    lines = [
        title,
        "",
        f"Made by the canvodpy run dashboard, canvodpy {canvodpy.__version__},",
        f"on {made_at.strftime('%Y-%m-%d %H:%M:%S')} UTC,",
        f"from the run history in {log_dir}.",
        "",
        "Runs:",
        *(f"  {run_id}" for run_id in run_ids),
        "",
        "Files:",
        f"  {FILE_NAME}: every record of the runs above (settings, machine,",
        "    receiver-days, stage timings, resource samples, warnings and",
        "    errors), nothing of other runs. Open it with",
        "    canvodpy.run_history.RunHistory.open(<this folder>, read_only=True)",
        "    or with any SQLite tool, or look at it with",
        "    canvodpy dashboard --logs-dir <this folder>",
        *(f"  {name}: {description}" for name, description in tables.items()),
        "",
        "The CSV files hold the rows the dashboard showed. The run history",
        "is read when you click the button, so for a running run it can",
        "hold records newer than the page you looked at.",
        "",
    ]
    return "\n".join(lines)


def export_zip(
    log_dir: Path,
    run_ids: Iterable[str],
    tables: dict[str, tuple[str, list[dict[str, Any]]]],
    *,
    title: str,
) -> bytes:
    """The zip of a dashboard view, as bytes.

    Parameters
    ----------
    log_dir : Path
        The log folder the dashboard reads.
    run_ids : iterable of str
        The runs the view shows; the run history in the zip holds only these.
    tables : dict
        File name (without ``.csv``) to a description and the rows of one
        table or chart of the view. A table without rows is left out.
    title : str
        The first line of the README.
    """
    run_ids = sorted(set(run_ids))
    made_at = datetime.now(UTC)
    csv_files = {
        f"{name}.csv": (description, table_csv(rows))
        for name, (description, rows) in tables.items()
        if rows
    }

    buffer = io.BytesIO()
    with (
        tempfile.TemporaryDirectory() as tmp,
        RunHistory.open(log_dir, read_only=True) as history,
    ):
        history_copy = Path(tmp) / FILE_NAME
        history.copy_runs(run_ids, history_copy)
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "README.txt",
                _readme(
                    title,
                    log_dir,
                    run_ids,
                    {name: description for name, (description, _) in csv_files.items()},
                    made_at,
                ),
            )
            zf.write(history_copy, FILE_NAME)
            for name, (_, text) in csv_files.items():
                zf.writestr(name, text)
    return buffer.getvalue()
