# ============================================================================
# canVODpy Monorepo - Root Justfile
# ============================================================================

# Use Git Bash on Windows (installed with Git for Windows)
# Full path avoids resolving to WSL's bash on GitHub Actions runners
set windows-shell := ["C:/Program Files/Git/bin/bash.exe", "-c"]

# ANSI color codes
GREEN := '\033[0;32m'
BOLD := '\033[1m'
NORMAL := '\033[0m'

# Configuration directory for the canvodpy commands below, e.g.
#   just config_dir=~/my_config config-check-data rosalia
# Empty: $CANVOD_CONFIG_DIR, else config/, else ~/.config/canvodpy.
config_dir := ""
config_flag := if config_dir != "" { "--config-dir " + quote(config_dir) } else { "" }

# Default command lists all available recipes
_default:
    @just --list --unsorted

alias c := clean
alias d := dist
alias h := hooks
alias q := check
alias t := test

# ============================================================================
# Code graph (graphify): free and local, no LLM, no API key
# ============================================================================

# graphify builds a graph of the code from its syntax tree. Only commands that
# never call an LLM are used here (`extract --code-only`, `affected`, `path`,
# `explain`); LLM API keys are removed from their environment as well.
# Never run `graphify label`, `graphify cluster-only` (its output suggests it),
# a full `graphify extract`, or its assistant skill:
# those call paid language-model APIs.
graphify := "env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u OPENAI_API_KEY -u OPENAI_BASE_URL -u GEMINI_API_KEY -u GOOGLE_API_KEY -u MOONSHOT_API_KEY -u DEEPSEEK_API_KEY -u AZURE_OPENAI_API_KEY -u OLLAMA_API_KEY GRAPHIFY_NO_TIPS=1 uvx -q --from graphifyy==0.9.75 graphify"
graph_file := ".graphify/graphify-out/graph.json"

# rebuild the code graph (.graphify/, git-ignored; git hooks run this after commits, merges and checkouts)
graph:
    @{{ graphify }} extract . --code-only --force --out .graphify

# everything that calls, imports or subclasses NAME (impact of a change)
graph-affected NAME:
    @{{ graphify }} affected {{ quote(NAME) }} --graph {{ graph_file }}

# how NAME_A reaches NAME_B (caller first), e.g. just graph-path VodComputer TauOmegaZerothOrder
graph-path NAME_A NAME_B:
    @{{ graphify }} path {{ quote(NAME_A) }} {{ quote(NAME_B) }} --graph {{ graph_file }}

# a node and its neighbours in plain words
graph-explain NAME:
    @{{ graphify }} explain {{ quote(NAME) }} --graph {{ graph_file }}

# ============================================================================
# Agent workflow (mattpocock-skills, see docs/guides/ai-development.md)
# ============================================================================

# install or update the shared agent workflow skills (Claude Code plugin from GitHub mattpocock/skills, enabled in .claude/settings.json)
agent-skills:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v claude >/dev/null 2>&1; then
        echo "Claude Code ('claude') is not installed: https://code.claude.com/docs" >&2
        echo "Other coding agents: npx skills@latest add mattpocock/skills" >&2
        exit 1
    fi
    # the author's own marketplace (GitHub mattpocock/skills): its latest release,
    # which the official Claude marketplace may lag behind
    claude plugin marketplace add mattpocock/skills --scope project
    claude plugin install mattpocock-skills@mattpocock --scope project
    claude plugin marketplace update mattpocock
    claude plugin update mattpocock-skills@mattpocock --scope project
    echo "Done. Restart Claude Code in this repository; /ask-matt shows which skill fits a task."

# ============================================================================
# Code Quality (All Packages)
# ============================================================================

# check uv.lock is up to date
check-lock:
    uv lock --check

# lint python code using ruff
[private]
check-lint:
    uv run ruff check . --fix

# lint python code without auto-fixing (for CI)
check-lint-only:
    uv run ruff check .

# format python code using ruff
# Markdown: ruff format also formats the fenced Python code blocks in
# Markdown files, so the examples in the docs look like the code; put a
# long trailing comment on its own line above, or ruff wraps the statement.
# --exclude "demo": same nested-config issue -- root's `exclude = ["demo"]`
# only actually takes effect for pre-commit's explicit-filename hook
# invocation (force-exclude); a directory walk from `.` (what this recipe
# and CI do) still descends into demo/ once it finds demo/pyproject.toml,
# even though that file has no [tool.ruff] section of its own. Verified
# empirically: root's `exclude` alone does not stop demo/*.py from being
# reformatted here, only a CLI-level --exclude does.
[private]
check-format:
    uv run ruff format . --exclude "demo"

# check formatting without modifying files (for CI)
check-format-only:
    uv run ruff format --check . --exclude "*.ipynb" --exclude "demo"

# run the type checker ty (config lives in [tool.ty] in pyproject.toml)
check-types:
    uv run ty check

# check that every file has its license and copyright (REUSE 3.3)
check-reuse:
    uvx --from 'reuse[charset-normalizer]' reuse lint

# check that AGENTS.md files and skills name only existing paths and recipes
check-agent-docs:
    uv run --no-sync python scripts/check_agent_docs.py

# check that each package imports with only its own declared dependencies
check-package-imports *PACKAGES:
    uv run --no-sync python scripts/check_package_imports.py {{PACKAGES}}

# lint, format and type-check (all packages), check the agent docs
check: check-lint check-format check-types check-agent-docs

# ============================================================================
# Testing (All Packages)
# ============================================================================

# run tests for all packages
test:
    uv run pytest

# run tests for all packages, skipping integration tests that need real
# credentials/network/test data (e.g. NASA Earthdata for ephemeris downloads)
test-fast:
    uv run pytest -m "not integration"

# run tests for all supported Python versions
testall:
    uv run --python=3.14 pytest

# run tests per package to avoid namespace collisions (for CI)
test-all-packages:
    @echo "Running tests per package to avoid namespace collisions..."
    uv run pytest canvodpy/tests/ --verbose --color=yes
    uv run pytest packages/canvod-auxiliary/tests/ --verbose --color=yes
    uv run pytest packages/canvod-config/tests/ --verbose --color=yes
    uv run pytest packages/canvod-readers/tests/ --verbose --color=yes
    uv run pytest packages/canvod-store/tests/ --verbose --color=yes
    uv run pytest packages/canvod-grids/tests/ --verbose --color=yes
    uv run pytest packages/canvod-viz/tests/ --verbose --color=yes
    uv run pytest packages/canvod-preflight/tests/ --verbose --color=yes
    uv run pytest packages/canvod-vod/tests/ --verbose --color=yes
    uv run pytest packages/canvod-ops/tests/ --verbose --color=yes
    uv run pytest packages/canvod-store-metadata/tests/ --verbose --color=yes

# run tests with coverage report
test-coverage:
    uv run pytest

# run all formatting, linting, and testing commands
ci PYTHON="3.14":
    uv run --python={{ PYTHON }} ruff format .
    uv run --python={{ PYTHON }} ruff check . --fix
    uv run --python={{ PYTHON }} ty check .
    uv run --python={{ PYTHON }} pytest

# ============================================================================
# Configuration
# ============================================================================

# validate canvod-settings.yaml and the receiver data of all sites
config-validate:
    uv run canvodpy config validate {{ config_flag }}

# check one site's receiver data (alias of: canvodpy config validate --site SITE)
config-check-data SITE:
    uv run canvodpy config validate --site {{ SITE }} {{ config_flag }}

# process a site's GNSS data and compute VOD for days START to END (YYYYDOY)
run SITE START END:
    uv run canvodpy run --site {{ SITE }} --start {{ START }} --end {{ END }} {{ config_flag }}

# create naming recipe NAME of SITE in <config dir>/recipes/SITE/ (non-canonical filenames)
naming-init SITE NAME:
    #!/usr/bin/env -S uv run python
    import os
    import sys

    os.environ["CANVOD_CONFIG_DIR"] = {{ quote(config_dir) }}
    from canvod.config.loader import get_default_config_dir
    from canvodpy.orchestrator.discovery import FILEMAP_INSTALL_HINT

    try:
        from canvod.filemap import create_recipe
    except ImportError:
        sys.exit(f"Naming recipes need canvod-filemap. {FILEMAP_INSTALL_HINT}")
    try:
        path = create_recipe(get_default_config_dir(), {{ quote(SITE) }}, {{ quote(NAME) }})
    except FileExistsError as exc:
        sys.exit(f"{exc}. Edit it directly, or delete it first to start over.")
    print(f"Created {path}")
    print("Next: fill in the receiver identity and the fields of your file names,")
    print("then check them with: just config-check-data {{ SITE }}")

# check every orbit/clock product of the registry against the FTP servers (days as YYYYDOY; default: 2025001 and three weeks ago)
check-products *DAYS:
    #!/usr/bin/env -S uv run python
    import os
    import sys

    os.environ["CANVOD_CONFIG_DIR"] = {{ quote(config_dir) }}
    from canvod.auxiliary.products.check import main
    from canvod.config import load_config

    mail = load_config().nasa_earthdata_acc_mail
    sys.exit(main("{{ DAYS }}".split() + (["--cddis-mail", mail] if mail else [])))

# show the current configuration
config-show:
    uv run canvodpy config show {{ config_flag }}

# initialize configuration from template
config-init:
    uv run canvodpy config init {{ config_flag }}

# initialize configuration via guided interactive wizard
config-init-interactive:
    uv run canvodpy config init --interactive {{ config_flag }}

# open canvod-settings.yaml in $EDITOR
config-edit:
    uv run canvodpy config edit {{ config_flag }}

# report canvodpy's version, environment, and config resolution
doctor:
    uv run canvodpy doctor {{ config_flag }}

# delete canvod-settings.yaml (destructive, requires typed confirmation)
config-delete CONFIG_DIR="config":
    #!/usr/bin/env bash
    set -euo pipefail
    target="{{ CONFIG_DIR }}/canvod-settings.yaml"
    if [ ! -f "$target" ]; then
        echo "Nothing to delete: $target does not exist."
        exit 0
    fi
    echo -e "{{ BOLD }}This will permanently delete: $target{{ NORMAL }}"
    read -p "Type 'yes' to confirm: " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted -- no changes made."
        exit 1
    fi
    rm -f "$target"
    echo -e "{{ GREEN }}Deleted $target{{ NORMAL }}"

# ============================================================================
# Store Inspection
# ============================================================================

# list every configured site's gnss/vod store paths and status
store-list:
    uv run canvodpy store list {{ config_flag }}

# show branches, groups, and stats for one site's store (STORE: gnss|vod)
store-info SITE STORE="gnss":
    uv run canvodpy store info {{ SITE }} --store {{ STORE }} {{ config_flag }}

# show a group's full dataset + metadata table for one site's store
store-info-group SITE GROUP STORE="gnss":
    uv run canvodpy store info {{ SITE }} --store {{ STORE }} --group {{ GROUP }} {{ config_flag }}

# show commit history as a graph for one site's store (STORE: gnss|vod)
store-log SITE STORE="gnss":
    uv run canvodpy store log {{ SITE }} --store {{ STORE }} {{ config_flag }}

# show the ops audit trail for one site's store (STORE: gnss|vod)
store-ops SITE STORE="gnss":
    uv run canvodpy store log {{ SITE }} --store {{ STORE }} --ops {{ config_flag }}

# write the STAC catalog of every store under the data root (storage.stores_root_dir), beside the stores
stac-write:
    uv run canvodpy stac write {{ config_flag }}

# publish a release: tag every store under the data root with TAG and write releases/TAG/ (no '/' in TAG)
stac-release TAG:
    uv run canvodpy stac release {{ TAG }} {{ config_flag }}

# ============================================================================
# Store Metadata
# ============================================================================

# show full metadata report for a store
metadata-show STORE_PATH:
    uv run python -m canvod.store_metadata.show {{ STORE_PATH }}

# show a specific metadata section (identity, creator, temporal, spatial, env, processing, summaries, validation, reproduce, uv, toml)
metadata-section STORE_PATH SECTION:
    uv run python -m canvod.store_metadata.show {{ STORE_PATH }} {{ SECTION }}

# validate store metadata against zarr conventions, ACDD, DataCite, STAC and FAIR;
# fails on a failure, not on recommendations, FAIR advice or warnings
metadata-validate STORE_PATH:
    uv run python -c "import sys; from pathlib import Path; from canvod.store_metadata import read_metadata, validate_all; from canvod.store_metadata.show import format_validation; meta = read_metadata(Path('{{ STORE_PATH }}')); print(format_validation(meta, Path('{{ STORE_PATH }}'))); sys.exit(1 if any(validate_all(meta, recommended=False).values()) else 0)"

# scan a directory for stores and print inventory table
metadata-inventory ROOT_DIR:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import scan_stores; df = scan_stores(Path('{{ ROOT_DIR }}')); print(df)"

# extract pyproject.toml + uv.lock from a store for environment reproduction
metadata-extract-env STORE_PATH OUTPUT_DIR:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import extract_env; p = extract_env(Path('{{ STORE_PATH }}'), Path('{{ OUTPUT_DIR }}')); print(f'Extracted to {p}. Run: cd {p} && uv sync --frozen')"

# run canvod-store-metadata tests
metadata-test:
    uv run pytest packages/canvod-store-metadata/tests/ -v

# ============================================================================
# Utilities
# ============================================================================

# check if required development tools are installed
check-dev-tools:
    @bash scripts/check_dev_tools.sh

# setup the pre-commit hooks
hooks:
    uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push --hook-type post-merge --hook-type post-commit --hook-type post-checkout

# ============================================================================
# uv venv and Dependency Management
# ============================================================================

venv-upgrade:
    uv lock --upgrade
    uv sync

# ============================================================================
# Release Management
# ============================================================================

# Lists the commits since each package's last release tag that touched its
# folder, to choose the versions of a release.
# show each package's version, last tag and commits since
release-status:
    uv run --no-sync python scripts/release.py status

# Runs the tests, checks the choice (canvodpy always included, its
# increment at least the largest, ranges admit the new versions), writes the
# versions, canvodpy's pins, the changelogs, the citation files and uv.lock,
# and commits them on release/v<canvodpy version>; no tag (docs/RELEASING.md).
# prepare a release: just release canvod-store=1.1.0 canvodpy=1.1.0
release +VERSIONS: test
    uv run --no-sync python scripts/release.py prepare {{VERSIONS}}

# Run on the merged release commit on main; does not push.
# tag every package version without a tag (canvod-store-v1.1.0, v1.1.0)
tag-release:
    uv run --no-sync python scripts/release.py tag

# ============================================================================
# Build & Publish Recipes
# ============================================================================

# Build all packages (outputs to workspace root dist/)
build-all:
    @echo "🔨 Building every workspace package..."
    @rm -rf dist/
    @mkdir -p dist/
    uv build --all-packages --out-dir dist/
    @echo "✅ Built $(ls dist/*.whl | wc -l | tr -d ' ') wheels to dist/"
    @ls -lh dist/*.whl

# Publish all packages to TestPyPI (requires credentials)
publish-testpypi:
    @echo "📦 Publishing to TestPyPI..."
    @if [ ! -d "dist" ] || [ -z "$$(ls -A dist)" ]; then \
        echo "❌ No dist/ found. Run 'just build-all' first"; \
        exit 1; \
    fi
    uv tool run twine upload --repository testpypi dist/*
    @echo "✅ Published to https://test.pypi.org"

# Publish all packages to PyPI (requires credentials or OIDC)
publish-pypi:
    @echo "📦 Publishing to PyPI..."
    @if [ ! -d "dist" ] || [ -z "$$(ls -A dist)" ]; then \
        echo "❌ No dist/ found. Run 'just build-all' first"; \
        exit 1; \
    fi
    uv tool run twine upload dist/*
    @echo "✅ Published to https://pypi.org"

# print the current status of the project
status:
    @echo "canVODpy Monorepo"
    @echo "Running on: `uname`"

# clean all python build/compilation files and directories
clean: clean-build clean-pyc clean-test

# remove build artifacts
[private]
clean-build:
    rm -fr build/
    rm -fr _build/
    rm -fr dist/
    rm -fr .eggs/
    find . -name '*.egg-info' -exec rm -fr {} +
    find . -name '*.egg' -exec rm -f {} +

# remove Python file artifacts
[private]
clean-pyc:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -fr {} +

# remove test and coverage artifacts
[private]
clean-test:
    rm -f .coverage
    rm -fr htmlcov/
    rm -fr .pytest_cache

# install all packages in workspace and ensure all git hooks are active
sync:
    uv sync
    uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push --hook-type post-merge --hook-type post-commit --hook-type post-checkout

# update the submodules (demo + test_data) to their latest remote commits and commit the new
# pointers on the current feature branch (refused on main: pointers reach main through a PR)
update-submodules:
    @if [ "$(git branch --show-current)" = "main" ]; then echo "On main: switch to a feature branch first" >&2; exit 1; fi
    git submodule update --remote --merge demo
    git submodule update --remote --merge packages/canvod-readers/tests/test_data
    git add demo packages/canvod-readers/tests/test_data
    git diff --cached --quiet -- demo packages/canvod-readers/tests/test_data || git commit -m "chore: update submodule pointers (demo + test_data)" -- demo packages/canvod-readers/tests/test_data

# ============================================================================
# Version Management
# ============================================================================
# Note: Version management should be done at the package level
# Use: just build-package <package-name>
# Workspace root does not have a version

# [confirm("Do you really want to bump? (y/n)")]
# [private]
# prompt-confirm:

# bump the version, commit and add a tag <major|minor|patch|...>
# bump INCREMENT="patch": && tag
#     @uv version --bump {{ INCREMENT }} --dry-run
#     @just prompt-confirm
#     uv version --bump {{ INCREMENT }}

# tag the latest version
# tag VERSION=`uv version --short`:
#     git add pyproject.toml
#     git add uv.lock
#     git commit -m "Bumped version to {{VERSION}}"
#     git tag -a "v{{VERSION}}"
#     @echo "{{ GREEN }}{{ BOLD }}Version has been bumped to {{VERSION}}.{{ NORMAL }}"

# ============================================================================
# Building & Distribution
# ============================================================================

# build the source distribution and wheel file
dist:
    uv build

# ============================================================================
# Per-Package Commands
# ============================================================================

# run check for a specific package (canvodpy or canvod-*)
check-package PACKAGE:
    cd {{ if PACKAGE == "canvodpy" { "canvodpy" } else { "packages/" + PACKAGE } }} && uv run ruff check . --fix && uv run ruff format . && uv run ty check

# run tests for a specific package, e.g. canvod-readers (canvodpy: the umbrella package)
test-package PACKAGE:
    cd {{ if PACKAGE == "canvodpy" { "canvodpy" } else { "packages/" + PACKAGE } }} && uv run pytest

# build a specific package
build-package PACKAGE:
    cd {{ if PACKAGE == "canvodpy" { "canvodpy" } else { "packages/" + PACKAGE } }} && uv build

# ============================================================================
# Notebooks (marimo)
# ============================================================================

# list all marimo notebooks in demo/ (numbered files only -- excludes
# helper modules like _paths.py, _download.py, _live_store.py)
notebooks:
    @echo "{{ GREEN }}{{ BOLD }}Available notebooks:{{ NORMAL }}"
    @ls demo/[0-9]*.py | sed 's|demo/||' | sort

# open a marimo notebook for editing (e.g. just open-notebook grids_overview.py)
# uvx (not `uv run`) so this never touches the workspace venv/uv.lock --
# --sandbox installs the notebook's own PEP 723 deps into a throwaway venv
open-notebook NAME:
    uvx marimo edit --sandbox demo/{{ NAME }}

# run a marimo notebook as a read-only app (e.g. just app-notebook grids_overview.py)
app-notebook NAME:
    uvx marimo run --sandbox demo/{{ NAME }}

# start the hemisphere API server (run from repo root; see .icechunk_gridding_claude/RUNNING.md)
hemi-serve:
    CATALOG=.icechunk_gridding_claude/_out/catalog.json \
      uv run --with fastapi --with uvicorn --with xpublish \
      python .icechunk_gridding_claude/serve_hemisphere.py

# open the VOD hemisphere viewer notebook for interactive editing
hemi-view:
    uv run --with marimo --with plotly --with wigglystuff --with httpx \
      --with ipywidgets \
      marimo edit .icechunk_gridding_claude/view_vod_cube.py

# ============================================================================
# Documentation
# ============================================================================

# preview the documentation locally
docs:
    uv run zensical serve --open

# build the documentation
docs-build:
    uv run zensical build

# check the language of the docs pages (Vale, Google style)
docs-lint *FILES="docs":
    uvx --from vale vale sync
    uvx --from vale vale {{ FILES }}

# check the language of the docs pages changed since BASE (Vale; what CI runs)
docs-lint-changed BASE="origin/main":
    #!/usr/bin/env bash
    set -euo pipefail
    files=$(git diff --name-only --diff-filter=d "{{ BASE }}...HEAD" -- 'docs/*.md' 'docs/**/*.md')
    if [ -z "$files" ]; then echo "No docs pages changed since {{ BASE }}."; exit 0; fi
    uvx --from vale vale sync
    uvx --from vale vale $files

# write the command-line reference page (docs/api/cli.md) from the --help texts
cli-docs:
    uv run python scripts/cli_docs.py

# check that the command-line reference page matches the --help texts
cli-docs-check:
    uv run python scripts/cli_docs.py --check

# check every link of the built docs site (lychee; brew install lychee)
docs-links:
    @command -v lychee >/dev/null || { echo "lychee is not installed: brew install lychee" >&2; exit 1; }
    uv run zensical build --clean
    lychee --root-dir "$(pwd)/site" 'site/**/*.html'


# deploy the documentation via GitHub Actions
docs-deploy:
    gh workflow run "Deploy Docs"

# ============================================================================
# Dependency Analysis
# ============================================================================

# dependencies between the packages, coupling per package (Markdown; fails on a dependency on a higher layer)
deps-report:
    @uv run --no-sync python scripts/analyze_dependencies.py --format report

# dependency graph of the packages, grouped by layer (Mermaid)
deps-mermaid:
    @uv run --no-sync python scripts/analyze_dependencies.py --format mermaid

# ============================================================================
# Initialization
# ============================================================================

# ============================================================================
# Danger Zone (destructive operations with confirmation)
# ============================================================================

# delete all log files
[confirm("This will delete ALL log files. Continue? (y/n)")]
danger-delete-logs:
    uv run python scripts/danger_zone.py delete-logs

# delete downloaded auxiliary data (SP3, CLK) and Zarr caches
[confirm("This will delete auxiliary data. Continue? (y/n)")]
danger-delete-aux:
    uv run python scripts/danger_zone.py delete-aux

# delete a specific Icechunk store (rinex or vod) for a site
[confirm("This will PERMANENTLY delete store data. Continue? (y/n)")]
danger-delete-store SITE STORE:
    uv run python scripts/danger_zone.py delete-store {{ SITE }} {{ STORE }}

# delete ALL Icechunk stores for a site
[confirm("This will PERMANENTLY delete ALL stores. Continue? (y/n)")]
danger-delete-all-stores SITE:
    uv run python scripts/danger_zone.py delete-all-stores {{ SITE }}

# ============================================================================
# Initialization
# ============================================================================

# initialize a git repo and add all files
init: sync
    git init --initial-branch=main
    git add .
    git commit -m "initial commit"
    @echo "{{ GREEN }}{{ BOLD }}Git has been initialized{{ NORMAL }}"
