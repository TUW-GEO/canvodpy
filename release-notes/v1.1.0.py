# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "canvodpy==1.1.0",
#   "marimo>=0.23.9",
# ]
#
# [tool.marimo.opengraph]
# title = "canVODpy v1.1.0"
# description = "What canVODpy v1.1.0 brings, and how to use it."
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="medium",
    app_title="canVODpy v1.1.0",
)


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    <p align="center">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
        <img src="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" alt="canVODpy logo" width="280">
      </picture>
    </p>

    # canVODpy v1.1.0

    [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/TUW-GEO/canvodpy/blob/main/release-notes/v1.1.0.py)

    Receivers that write RINEX files can now use the broadcast ephemeris:
    the satellite positions come from the receiver's own RINEX navigation
    files, so a run needs no orbit products of an analysis center. Every
    run now names the satellites it observed without a position, and the
    command line can show the history of any store.

    ```bash
    uv add canvodpy==1.1.0
    ```

    Nothing changes for a run with the precise ephemeris or with SBF files,
    apart from the new name of the precise ephemeris below. The full list
    of changes is in the
    [changelog](https://github.com/TUW-GEO/canvodpy/blob/v1.1.0/CHANGELOG.md).

    ---
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Broadcast ephemeris from RINEX navigation files

    With `ephemeris_source: broadcast`, a receiver with RINEX files takes
    the satellite positions from its RINEX 3.04/3.05 navigation files:
    GPS, Galileo, GLONASS, BeiDou, QZSS and SBAS so far. canvodpy computes
    the positions from the navigation records, then interpolates them and
    turns them into $\theta$ and $\phi$ the same way as the precise orbits.
    The signals of other systems are stored without angles and get no VOD.

    Give each receiver with RINEX files the folder of its navigation files
    as `nav_directory`, relative to the site data root like `directory`
    (it may be the same folder). In shared-position mode, the default, a
    reference receiver uses the navigation files of its canopy and needs
    none of its own:

    ```yaml
    processing:
      params:
        ephemeris_source: broadcast
    sites:
      Fangorn:
        receivers:
          canopy_01:
            directory: 02_canopy
            nav_directory: 02_canopy_nav
            nav_recipe: fangorn_canopy_nav  # only for names outside the convention
            reader_format: rinex3
    ```

    Then check the settings and run:

    ```bash
    canvodpy config validate
    canvodpy run --site Fangorn --start 2025001 --end 2025007
    ```

    Settings with `broadcast` and a RINEX receiver without
    `nav_directory` are refused. With `shared_aux_cache_dir`, the orbits of
    the navigation files are cached too, one entry per date and content of
    the files, so a second run of the day computes nothing again. In
    Airflow, `check_day` waits for the navigation files as it waits for the
    observation files. The demo data hold no navigation files, so this
    section shows the settings only.

    More: [Ephemeris sources](https://canvodpy.eu/packages/readers/ephemeris-sources/#broadcast-ephemeris-from-rinex-navigation-files).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Navigation files have canonical names too

    Without a `nav_recipe`, canvodpy reads the navigation files with
    canonical canVOD names: type `nav` and sampling `00U`. Files with other
    names need a naming recipe with `file_type: nav`.
    """)
    return


@app.cell
def _(mo):
    from canvod.preflight import CanVODFilename

    _nav = CanVODFilename.from_filename("FANA01INK_R_20250010000_15M_00U_AA.nav")

    mo.md(f"""
    ```python
    from canvod.preflight import CanVODFilename

    CanVODFilename.from_filename("FANA01INK_R_20250010000_15M_00U_AA.nav")
    ```

    | Field | Value |
    |-------|-------|
    | **Site** | `{_nav.site}` |
    | **Receiver type** | `{_nav.receiver_type}` |
    | **Receiver number** | `{_nav.receiver_number}` |
    | **Year, day of year** | {_nav.year}, {_nav.doy} |
    | **Name** | `{_nav}` |
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## `final` is now called `precise`

    The ephemeris source of the SP3 and CLK products of an analysis center
    is now `precise`, the default. The product type, `final` or `rapid`,
    stays under `processing.aux_data.product_type`. The old name `final`
    still works until v2.0.0 and warns; stores created with `final` accept
    runs with `precise`:
    """)
    return


@app.cell
def _():
    import warnings

    from canvod.config.models import ProcessingParams

    with warnings.catch_warnings(record=True) as _caught:
        warnings.simplefilter("always")
        # as a settings file with the old name gives it
        _params = ProcessingParams.model_validate({"ephemeris_source": "final"})

    print("ephemeris_source:", _params.ephemeris_source)
    for _warning in _caught:
        print(f"{_warning.category.__name__}: {_warning.message}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    With `ephemeris_source: broadcast`, `processing.aux_data.agency` and
    `product_type` don't apply: a value other than the default warns that
    it is ignored, and a new store records them as empty.

    More: [Upgrading](https://canvodpy.eu/guides/upgrading/).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Satellites without a position

    A satellite has no position at an epoch when no orbit covers it: no
    navigation record of it is valid then (a broadcast run), or the orbit
    product lacks it (a precise run). Its angles are NaN there, never
    extrapolated, so these observations get no VOD. Every run now names
    them, with one line per receiver-day:

    ```
      no position: canopy_01 on 2025001: G08 (360 epochs), R19 (12 epochs)
    ```

    The run also logs a `satellites_without_position` warning, which the
    run history keeps, and the log book of the receiver's group has the
    same list per file in the column `satellites_without_position`. In
    Python, the pipeline hands them to a function of yours:

    ```python
    from canvodpy import Site

    def report(receiver, day, satellites):
        print(receiver, day, satellites)  # {"G08": 360, "R19": 12}

    site = Site("Fangorn")
    with site.pipeline(on_satellites_without_position=report) as pipeline:
        for unit in pipeline.run("2025001", "2025007"):
            print(sorted(unit.days), unit.vod.written)
    ```

    More: [Diagnostics](https://canvodpy.eu/guides/diagnostics/#satellites-without-a-position).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## SBAS satellites of SBF files keep their signals

    The SBF reader named SBAS satellites by their PRN (`S123`), while RINEX
    and canvodpy number them PRN - 100 (`S23`). With v1.0.0, every SBAS
    signal of an SBF file and its SatVisibility angles were lost. Now they
    have the RINEX names. The SBAS signals of the first demo SBF file of the
    canopy receiver:
    """)
    return


@app.cell
def _(mo):
    from canvod.readers.sbf import SbfReader
    from canvodpy import demo_data

    _file = sorted(
        (demo_data("sbf") / "sbf" / "01_Rosalia" / "02_canopy").glob("25001/*.sbf")
    )[0]
    _snr = SbfReader(fpath=_file).to_ds().SNR
    _sbas = _snr.where(_snr.system == "S", drop=True).dropna("sid", how="all")
    _rows = "\n".join(
        f"| `{_sid}` | {int(_sbas.sel(sid=_sid).notnull().sum())} |"
        for _sid in _sbas.sid.values
    )

    mo.md(f"""
    File: `{_file.name}`

    | Signal | Epochs with SNR |
    |--------|-----------------|
    {_rows}

    More: [SBF decoding](https://canvodpy.eu/packages/readers/sbf-decoding/).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The command line

    `canvodpy store log --path` shows the history of a store without a
    settings file, for example a copy or a store someone sent you, local or
    on S3 (`s3://bucket/prefix`). `--plain` draws the commit graph without
    colors, for a file or a CI log, and `--svg FILE` writes it as an image.
    Here, the history of the GNSS store of the demo data:
    """)
    return


@app.cell
def _():
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    # The canvodpy command of this notebook's environment; no banner, no colors.
    canvodpy_cmd = shutil.which("canvodpy", path=str(Path(sys.executable).parent))
    cli_env = {**os.environ, "CANVODPY_NO_BANNER": "1", "NO_COLOR": "1"}
    return Path, canvodpy_cmd, cli_env, subprocess


@app.cell
def _(Path, canvodpy_cmd, cli_env, mo, subprocess):
    import tempfile

    from canvodpy import demo_data as _demo_data

    _store = _demo_data("stores") / "stores" / "rosalia_rinex_v3_04" / "gnss"
    _svg = Path(tempfile.mkdtemp()) / "gnss-log.svg"
    subprocess.run(
        [canvodpy_cmd, "store", "log", "--path", str(_store), "--svg", str(_svg)],
        env=cli_env,
        check=True,
        capture_output=True,
    )

    mo.vstack(
        [
            mo.md("```bash\ncanvodpy store log --path <store> --svg gnss-log.svg\n```"),
            mo.Html(_svg.read_text()),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    `canvodpy --help-all` lists every command with its options on one
    screen:
    """)
    return


@app.cell
def _(canvodpy_cmd, cli_env, subprocess):
    _help = subprocess.run(
        [canvodpy_cmd, "--help-all"],
        env=cli_env,
        check=True,
        capture_output=True,
        text=True,
    )
    print(_help.stdout)
    return


@app.cell
def _(mo):
    mo.md(r"""
    More in the terminal:

    - **The run dashboard** of `canvodpy run --dashboard` says whether the
      run is still going and has a button, *Shut the dashboard down*, which
      stops the dashboard but never the run. `--dashboard-stop-at-end`
      stops it when the run ends. Each stage's bar shows its time.
    - **Colors that follow the terminal:** the help, the messages and the
      progress bars take the terminal's background, dark or light, and
      avoid red. `CANVODPY_TERMINAL_THEME=dark` or `light` sets it,
      `NO_COLOR=1` turns colors off. Every status has its symbol.
    - **A banner** with the logo, the version and the support address at
      the start of `canvodpy`, `canvodpy --version` and `canvodpy run`, in
      an interactive terminal only. `CANVODPY_NO_BANNER=1` turns it off.
    - After `canvodpy --install-completion`, the command says how to load
      the completion in the open terminal.

    More: [Command line](https://canvodpy.eu/api/cli/#in-the-terminal).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Deprecated

    - `ephemeris_source: final` and `--ephemeris-source final`: use
      `precise` (above).
    - `processing.icechunk.zarr_async_concurrency` has no effect: it
      limited Zarr's concurrent chunk writes for only some of the store's
      writes. Delete it from your settings.

    Both are removed with v2.0.0.

    ## Fixes

    - **Shared aux cache:** an entry keeps the signals of every site.
      Before, the first site's signals were cached, and a second site
      keeping more signals got no angles for the extra ones, without an
      error. The cache now holds the orbits once per satellite, which
      makes building an entry much faster; existing entries are computed
      again once.
    - The clock files of JPL and IAC are read.
    - The hint for a missing `canvod-filemap` points at PyPI.
    """)
    return


if __name__ == "__main__":
    app.run()
