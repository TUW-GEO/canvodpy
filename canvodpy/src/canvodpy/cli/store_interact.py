"""canvodpy store interact: a store in a marimo notebook of its own.

The notebook is written to a temporary folder and opened with
``marimo edit --sandbox``: uv installs the canvodpy and marimo versions of
this command into an environment of the notebook's own, from the
notebook's inline script metadata (PEP 723). The notebook opens the store
without settings (``CANVOD_CONFIG_DIR`` points at an empty folder), so
canvodpy refuses every commit, expiry and garbage collection on it. The
folder is deleted when marimo stops.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from importlib.metadata import metadata, version
from pathlib import Path
from subprocess import Popen

from canvodpy.cli.theme import console

NOTEBOOK = '''# /// script
# requires-python = "{requires_python}"
# dependencies = [
#     "canvodpy=={canvodpy}",
#     "marimo=={marimo}",
# ]
# ///

import marimo

__generated_with = "{marimo}"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    from canvod.store import MyIcechunkStore

    return MyIcechunkStore, mo


@app.cell
def _(mo):
    mo.md("""
    **{location_md}**

    Opened without settings: canvodpy refuses every write to this
    store. This notebook is deleted when marimo stops; save a copy
    from marimo's menu to keep your work.
    """)
    return


@app.cell
def _(MyIcechunkStore):
    store = MyIcechunkStore({location!r}, store_type={store_type!r})
    store
    return (store,)


if __name__ == "__main__":
    app.run()
'''


def interact_notebook(location: str, store_type: str) -> str:
    """The notebook that opens the store at ``location``, pinned to the
    canvodpy and marimo versions of this command."""
    return NOTEBOOK.format(
        requires_python=metadata("canvodpy")["Requires-Python"],
        canvodpy=version("canvodpy"),
        marimo=version("marimo"),
        location=location,
        location_md=location.replace("\\", "\\\\").replace('"', '\\"'),
        store_type=store_type,
    )


def run_interact(location: str, store_type: str) -> int:
    """Open the store in a sandboxed marimo notebook; marimo's exit code."""
    if shutil.which("uv") is None:
        console.print(
            "[canvod.error]❌ store interact needs uv on the PATH:[/canvod.error] "
            "it builds the notebook's environment. "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="canvodpy-interact-") as tmp:
        notebook = Path(tmp) / "store.py"
        notebook.write_text(interact_notebook(location, store_type), encoding="utf-8")
        no_settings = Path(tmp) / "no-settings"
        no_settings.mkdir()
        env = os.environ | {"CANVOD_CONFIG_DIR": str(no_settings)}

        console.print(
            f"Opening {location} read-only in marimo, with canvodpy "
            f"{version('canvodpy')} in an environment of its own. "
            "The first start installs it and takes a while. Ctrl-C stops marimo."
        )
        process = Popen(
            [sys.executable, "-m", "marimo", "edit", "--sandbox", str(notebook)],
            env=env,
        )
        # marimo handles Ctrl-C itself (it asks before it quits); wait for it
        # instead of killing it, so it can shut its kernel down.
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                continue
