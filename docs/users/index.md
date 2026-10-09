---
title: Retrieve VOD
description: Retrieve GNSS-T VOD with canVODpy, from the command line or from Python.
---

# Retrieve VOD from your GNSS data

**The CLI is the main way to use canVODpy** — a complete, terminal-first
entrypoint designed to run unattended: cron jobs, HPC/remote machines,
scheduled batch processing. Most users should start there, even if they
plan to wrap it in their own scripts later.

From Python, `Site.pipeline()` runs the same processing for scripted or
notebook-driven runs and gives the same results.

<div class="grid cards" markdown>

-   :fontawesome-solid-terminal: &nbsp; **CLI — start here**

    ---

    The recommended entrypoint for production runs, cron jobs, and remote/HPC
    deployments. Complete on its own — no Python required.

    [:octicons-arrow-right-24: CLI Quickstart](cli.md){ .md-button .md-button--primary }

-   :fontawesome-brands-python: &nbsp; **Python — for scripting**

    ---

    `Site.pipeline()` for scripted/notebook-driven runs, with the same
    results as the CLI.

    [:octicons-arrow-right-24: Python Quickstart](python.md){ .md-button .md-button--primary }

</div>

---

Both paths share the same installation and the same `canvod-settings.yaml`
configuration file — see whichever guide you pick for the full walkthrough.

---

To work on canVODpy itself, see
[Contributor setup](../guides/contributor-setup.md): the development
environment, tests and the pull request workflow.
