# Contributor setup

This guide walks you through everything you need, from creating a GitHub account to running your first test, so you can start contributing to canVODpy even if you have never used Git, GitHub, or Python tooling before.

!!! tip "Just want to *use* canVODpy, not contribute?"

    See [Retrieve VOD](../users/index.md) instead.

<div class="grid cards" markdown>

-   :fontawesome-brands-github: &nbsp; **[Steps 1–5](#1-create-a-github-account)** &nbsp; GitHub + Git

    ---

    [GitHub account](#1-create-a-github-account) · [Homebrew](#2-install-homebrew-macos-only) · [Git install](#3-install-git) · [SSH keys](#4-set-up-an-ssh-key-for-github) · [Git identity](#5-configure-your-git-identity)

-   :fontawesome-solid-gear: &nbsp; **[Steps 6–9](#6-install-development-tools)** &nbsp; Tools + Repository

    ---

    [Install `uv` + `just`](#6-install-development-tools) · [Fork + clone](#7-fork-and-clone-the-repository) · [Submodules](#8-initialize-submodules) · [Development environment](#9-set-up-the-development-environment)

-   :fontawesome-solid-sliders: &nbsp; **[Step 10](#10-configure-and-run)** &nbsp; Configuration + First run

    ---

    Initialize `canvod-settings.yaml` · Set paths and credentials · Validate · Process your first day

-   :fontawesome-solid-circle-check: &nbsp; **[Steps 11–13](#11-verify-everything-works)** &nbsp; Verify + Contribute

    ---

    [Run tests](#11-verify-everything-works) · [Quality checks](#12-keeping-your-fork-up-to-date) · [Your first pull request](#13-your-first-contribution)

</div>

---

## 1. Create a GitHub account

GitHub is a website that hosts code and lets teams collaborate on software projects. If you don't already have an account, sign up at [github.com/signup](https://github.com/signup).

---

## 2. Install Homebrew (macOS only)

Homebrew is the standard package manager for macOS. It lets you install developer tools with a single command. Open **Terminal** (press ++cmd+space++, type "Terminal" and press ++enter++) and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the on-screen instructions. When it finishes, it tells you to run two commands to add Homebrew to your PATH: **copy and run them**. Then verify:

```bash
brew --version
```

!!! note
    If you already have Homebrew installed, run `brew update` to make sure it's current.

---

## 3. Install Git

Git is the version-control system that tracks changes in the codebase. Install it for your operating system:

=== "macOS"

    ```bash
    brew install git
    ```

=== "Linux (Debian/Ubuntu)"

    ```bash
    sudo apt update && sudo apt install git
    ```

=== "Linux (Fedora)"

    ```bash
    sudo dnf install git
    ```

=== "Windows"

    Download and run the installer from [git-scm.com](https://git-scm.com/download/win).
    Accept the default options during installation. Afterwards, open **Git Bash** (installed with Git) to run the commands in this guide.

Verify the installation:

```bash
git --version
```

You should see something like `git version 2.x.x`.

---

## 4. Set up an SSH key for GitHub

SSH keys let you securely connect to GitHub without typing your password every time.

### Generate a key

=== "macOS / Linux"

    ```bash
    ssh-keygen -t ed25519 -C "your_email@example.com"
    ```

    Press ++enter++ three times to accept the defaults (default file location, no passphrase).

=== "Windows (Git Bash)"

    ```bash
    ssh-keygen -t ed25519 -C "your_email@example.com"
    ```

    Press ++enter++ three times to accept the defaults.

### Add the key to the SSH agent

=== "macOS"

    ```bash
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_ed25519
    ```

=== "Linux"

    ```bash
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_ed25519
    ```

=== "Windows (Git Bash)"

    ```bash
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_ed25519
    ```

### Copy the public key

=== "macOS"

    ```bash
    pbcopy < ~/.ssh/id_ed25519.pub
    ```

=== "Linux"

    ```bash
    cat ~/.ssh/id_ed25519.pub
    ```

    Select and copy the output.

=== "Windows (Git Bash)"

    ```bash
    clip < ~/.ssh/id_ed25519.pub
    ```

### Add the key to GitHub

1. Go to [github.com/settings/keys](https://github.com/settings/keys).
2. Click **New SSH key**.
3. Give it a title (for example "Laptop"), paste the key, and click **Add SSH key**.

### Test the connection

```bash
ssh -T git@github.com
```

You should see: `Hi <username>! You've successfully authenticated...`

---

## 5. Configure your Git identity

Tell Git who you are (this information appears in your commits):

```bash
git config --global user.name "Your Name"
git config --global user.email "your_email@example.com"
```

Use the same email you registered on GitHub.

---

## 6. Install development tools

canVODpy uses two command-line tools to manage the project:

- **uv**: a fast Python package manager that handles dependencies and virtual environments.
- **just**: a command runner (like a simplified Makefile) that provides shortcuts for common tasks.

### Install uv

=== "macOS"

    ```bash
    brew install uv
    ```

=== "Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

### Install just

=== "macOS"

    ```bash
    brew install just
    ```

=== "Linux (any distribution)"

    This works on all Linux distributions (Ubuntu, Mint, Fedora, etc.):

    ```bash
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin
    ```

    Make sure `~/.local/bin` is on your PATH. Add this to your `~/.bashrc` or `~/.zshrc` if needed:

    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    ```

=== "Linux (Ubuntu 23.04+ / Debian 13+)"

    ```bash
    sudo apt install just
    ```

    !!! warning
        This does **not** work on Linux Mint or older Ubuntu versions.
        Use the "Linux (any distro)" tab instead.

=== "Windows"

    ```powershell
    winget install Casey.Just
    ```

### Verify both tools

```bash
uv --version
just --version
```

---

## 7. Fork and clone the repository

A **fork** is your own copy of the project on GitHub. You make changes in your fork and then propose them back to the original project via a "pull request."

### Fork on GitHub

1. Go to [github.com/nfb2021/canvodpy](https://github.com/nfb2021/canvodpy).
2. Click the **Fork** button in the top-right corner.
3. GitHub creates a copy at `github.com/YOUR_USERNAME/canvodpy`.

### Clone your fork

```bash
git clone git@github.com:YOUR_USERNAME/canvodpy.git
cd canvodpy
```

Replace `YOUR_USERNAME` with your actual GitHub username.

### Add the upstream remote

This lets you pull in updates from the original repository later:

```bash
git remote add upstream git@github.com:nfb2021/canvodpy.git
```

Verify your remotes:

```bash
git remote -v
```

You should see `origin` (your fork) and `upstream` (the original).

---

## 8. Initialize submodules

The repository uses two Git submodules that contain test data and demo data. Initialize them after cloning:

```bash
git submodule update --init --recursive
```

This pulls:

- **`packages/canvod-readers/tests/test_data`**: validation test data (falsified/corrupted RINEX files for testing)
- **`demo`**: clean real-world data for demos and documentation

If you skip this step, tests that require these datasets are skipped.

---

## 9. Set up the development environment

From inside the `canvodpy` directory, run:

```bash
# Verify required tools are available
just check-dev-tools

# Install all Python dependencies and the git hooks (code checks before
# each commit, code graph rebuild after each commit)
just sync

# First build of the code graph (free, local; see "Developing with coding agents")
just graph
```

---

## 10. Configure and run

Follow [Retrieve VOD](../users/index.md) to initialize `canvod-settings.yaml`, validate it, and process your first day of GNSS data.

---

## 11. Verify everything works

Run the test suite:

```bash
just test
```

Run code-quality checks (linting, formatting, type checking):

```bash
just check
```

If both commands complete without errors, your environment is ready.

---

## 12. Keeping your fork up to date

The upstream repository (`nfb2021/canvodpy`) receives regular updates. To incorporate these into your fork, you need to **fetch from upstream and merge into your local branch**. This section explains every step.

### Why this is necessary

When you forked the repository, GitHub created a snapshot of `main` at that moment. Any commits pushed to the upstream `main` after your fork was created are **not** automatically reflected in your fork. If you work on a feature branch for several days, the upstream `main` may have moved ahead, and your branch falls behind it. Merging upstream changes prevents conflicts from accumulating and ensures you are building on the latest codebase.

### One-time setup (already done if you followed step 7)

Verify that you have the `upstream` remote configured:

```bash
git remote -v
```

You should see two remotes:

```
origin    git@github.com:YOUR_USERNAME/canvodpy.git (fetch)
origin    git@github.com:YOUR_USERNAME/canvodpy.git (push)
upstream  git@github.com:nfb2021/canvodpy.git (fetch)
upstream  git@github.com:nfb2021/canvodpy.git (push)
```

If `upstream` is missing, add it:

```bash
git remote add upstream git@github.com:nfb2021/canvodpy.git
```

### Update your local `main` branch

Every time you want to sync with the latest upstream changes:

```bash
# 1. Switch to your local main branch
git checkout main

# 2. Fetch all new commits from the upstream repository
git fetch upstream

# 3. Merge upstream/main into your local main
#    This is a fast-forward merge (no merge commit) if you have not
#    committed directly to your local main, which you should not do.
git merge upstream/main

# 4. Push the updated main to your fork on GitHub
git push origin main
```

After these four commands, your fork's `main` branch on GitHub is identical to the upstream `main`.

### Update your feature branch

If you are working on a feature branch, incorporate the freshly updated `main`:

```bash
# Switch to your feature branch
git checkout feature/my-feature

# Rebase your feature branch onto the updated main
git rebase main
```

Rebasing replays your commits on top of the latest `main`, producing a linear history. If Git reports a **merge conflict** during rebase, it pauses and shows you which files conflict. Resolve each conflict by editing the file, then:

```bash
git add <resolved-file>
git rebase --continue
```

If you want to stop the rebase and return to the state before:

```bash
git rebase --abort
```

!!! warning "Force push after rebase"

    Rebasing rewrites commit history. If you have already pushed your feature
    branch to your fork, you will need to force-push after rebasing:

    ```bash
    git push --force-with-lease origin feature/my-feature
    ```

    `--force-with-lease` is safer than `--force` because it refuses to
    overwrite commits that someone else may have pushed to the same branch.

### Quick reference

```bash
# Full sync sequence (run periodically):
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
git checkout feature/my-feature
git rebase main
```

---

## 12b. Working in teams

During collaborative sprints, each team works on its own topic (often aligned with a package such as `canvod-grids` or `canvod-readers`). A shared **develop branch** acts as the integration point: no one commits to it directly. Instead, each team gets its own **team branch**.

### Branch structure

```
main
└── develop/sprint-2026              ← integration branch (shared by all teams)
    ├── team-grids/                  ← Team A
    │   ├── (direct commits)         ← Workflow A
    │   └── team-grids/add-new-grid   ← Workflow B feature branches
    ├── team-readers/                ← Team B
    └── team-vod/                    ← Team C
```

### Set up the team branch

The **team lead** creates the branch once:

```bash
git checkout develop/sprint-2026
git checkout -b team-grids
git push -u origin team-grids
```

**All other team members** fetch and switch to it:

```bash
git fetch origin
git checkout team-grids
```

From here, choose the workflow that fits your team:

=== "Workflow A, push to the team branch directly"

    Best for small teams (2–3 people) or when members work on separate files.

    Everyone commits and pushes to the team branch:

    ```bash
    # Make your changes, then:
    git add <files you changed>
    git commit -m "feat(grids): add new grid type"
    git push origin team-grids
    ```

    If someone else pushed before you, pull first:

    ```bash
    git pull --rebase origin team-grids
    git push origin team-grids
    ```

=== "Workflow B, feature branches with pull requests"

    Best for larger teams or when you want lightweight review within the team.

    Create a feature branch off the team branch:

    ```bash
    git checkout team-grids
    git checkout -b team-grids/add-new-grid
    ```

    Work, commit, and push your feature branch:

    ```bash
    git add <files you changed>
    git commit -m "feat(grids): add new grid tessellation"
    git push -u origin team-grids/add-new-grid
    ```

    Then open a pull request on GitHub targeting `team-grids`.

    To stay up to date with teammates' merged work:

    ```bash
    git checkout team-grids
    git pull origin team-grids
    git checkout team-grids/add-new-grid
    git rebase team-grids
    ```

### Merge the team's work into the develop branch

When your team's feature is ready, open **one pull request** from `team-grids` into the develop branch on GitHub. This is where the maintainer reviews the team's combined work.

---

## 13. Your first contribution

### Make your changes

Edit files with your favorite text editor or IDE.

### Run quality checks

```bash
just test
just check
```

### Stage and commit

```bash
git add <files you changed>
git commit -m "feat(grids): add new grid type"
```

Commit messages follow the [Conventional Commits](https://www.conventionalcommits.org/) format: `type(scope): description`. Common types: `feat`, `fix`, `docs`, `test`, `refactor`.

### Push

Push to your team branch or feature branch (see [Working in teams](#12b-working-in-teams)).

### Open a pull request

1. Go to your fork on GitHub. You'll see a banner suggesting to open a pull request.
2. Click **Compare & pull request**.
3. Set the **base** branch to your team branch (or the develop branch, depending on your workflow).
4. Add a title and description, then click **Create pull request**.

---

## 14. Pre-commit hooks and why your commit may be rejected

When you ran `just sync` in [step 9](#9-set-up-the-development-environment), a set of **pre-commit hooks** was installed into your local `.git/hooks/` directory. These hooks run automatically every time you execute `git commit`. If any hook fails, **the commit is aborted**: your changes remain staged but no commit is created.

This is intentional: it prevents code that does not meet the project's quality standards from entering the Git history. The hooks are defined in `.pre-commit-config.yaml` at the repository root.

### What runs on every commit

The following checks execute automatically in sequence. If any one fails, the commit is rejected.

| Hook                        | When it runs                               | What it checks                                                                                                            | Typical failure reason                                                  |
| --------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **ruff check**              | `pre-commit` (before commit is created)    | Python linting: unused imports, undefined names, style violations, type annotation issues                                | You have an unused import or a linting rule violation                   |
| **ruff format**             | `pre-commit`                               | Python formatting: consistent code style (indentation, line length, quote style, trailing commas)                        | Your code is not formatted according to the project style               |
| **uv-lock**                 | `pre-commit`                               | Lockfile consistency: verifies `uv.lock` matches `pyproject.toml`                                                        | You changed a dependency in `pyproject.toml` but did not run `uv sync`  |
| **trailing-whitespace**     | `pre-commit`                               | Removes trailing whitespace from all files                                                                                | A line ends with invisible spaces or tabs                               |
| **check-added-large-files** | `pre-commit`                               | Blocks files larger than the threshold from being committed                                                               | You are trying to commit a large binary, dataset, or log file           |
| **detect-private-key**      | `pre-commit`                               | Scans for accidentally staged private keys (SSH, PGP)                                                                     | You are about to commit a secret: **do not override this**             |
| **end-of-file-fixer**       | `pre-commit`                               | Ensures every file ends with exactly one newline                                                                          | A file is missing its final newline or has extra blank lines at the end |
| **check-agent-docs**        | `pre-commit`                               | Every path and `just` recipe named in `AGENTS.md` files and task guides exists                                       | You moved or renamed a file or recipe that an instruction file names    |
| **commitizen**              | `commit-msg` (after you write the message) | Validates that your commit message follows the [Conventional Commits](https://www.conventionalcommits.org/) specification | Your message does not match the `type(scope): subject` format           |
| **ty type check**           | `pre-push` (before `git push`)             | Type checking of the whole workspace with ty                                                                              | A type error; the push is aborted                                       |

CI also runs `just check-package-imports` (too slow for a hook, about two
minutes): it installs each package with only the dependencies its own
`pyproject.toml` declares and imports every module. It fails when a
package imports a library it does not declare, which the shared `.venv`
hides. Run it after you add an import of a new library to a package.

After a commit, merge or checkout, the **code graph** hook rebuilds the
code graph in the background (`.graphify/`, log in `.graphify/build.log`).
To move `demo` and the test data to their latest commits, run
`just update-submodules` on a feature branch; it commits the new pointers
there, and they reach `main` through a pull request.

### How to fix a rejected commit

When a hook fails, read the error output carefully. The most common scenarios:

=== "ruff linting or formatting failure"

    ruff will often **auto-fix** the issue. After the commit is rejected:

    ```bash
    # The hook already ran ruff --fix, so files may have been modified.
    # Check what changed:
    git diff

    # If the changes look correct, stage them and commit again:
    git add -u
    git commit -m "feat(readers): your original message"
    ```

    If ruff cannot auto-fix (e.g., an undefined variable), you must edit the code manually, then stage and commit again.

=== "commitizen message validation failure"

    Your commit message does not follow the Conventional Commits format. The error will say something like:

    ```
    commit validation: failed!
    please enter a commit message in the commitizen format.
    ```

    The required format is:

    ```
    type(scope): subject
    ```

    Where `type` is one of: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`, `style`

    And `scope` is one of: `readers`, `aux`, `grids`, `vod`, `store`, `viz`, `utils`, `naming`, `ops`, `docs`, `ci`, `deps`

    Examples of **valid** messages:

    ```bash
    git commit -m "feat(readers): add RINEX 4.0 parser"
    git commit -m "fix(store): handle empty epoch arrays"
    git commit -m "docs: update installation guide"
    git commit -m "test(vod): add tau-omega edge cases"
    ```

    Examples of **invalid** messages (will be rejected):

    ```bash
    git commit -m "added new feature"           # no type prefix
    git commit -m "feat: add stuff"              # too vague (but technically valid)
    git commit -m "FEAT(readers): add parser"    # type must be lowercase
    git commit -m "feat(readers) add parser"     # missing colon after scope
    ```

=== "uv-lock mismatch"

    You modified a `pyproject.toml` (added or changed a dependency) but the lockfile is out of date:

    ```bash
    uv sync          # regenerates uv.lock
    git add uv.lock
    git commit -m "feat(readers): your original message"
    ```

=== "Large file blocked"

    You are trying to commit a file that exceeds the size threshold (typically data files, `.zarr` stores, or log files). These should not be in the Git repository. Remove the file from staging:

    ```bash
    git reset HEAD <large-file>
    echo "<large-file>" >> .gitignore
    git add .gitignore
    git commit -m "chore: update gitignore"
    ```

### Bypassing hooks (emergency only)

In rare situations where you need to commit despite a hook failure (for example, you are certain the failure is a false positive), you can skip hooks:

```bash
git commit --no-verify -m "fix(store): emergency hotfix"
```

!!! danger "Use `--no-verify` with extreme caution"

    Skipping hooks defeats their purpose. The CI pipeline on GitHub runs the
    same checks: your pull request will fail if the code does not pass ruff,
    formatting, and commit message validation. Only use `--no-verify` when you
    fully understand why the hook is failing and are certain the failure is not
    a genuine code quality issue.

---

## 15. Continuous integration and test coverage

Every push to a branch and every pull request triggers automated checks on GitHub Actions. These are the same checks that run locally via `just check` and `just test`, but they execute in a clean environment to ensure reproducibility.

### CI pipelines

| Workflow               | Trigger                    | What it does                                                                                                                           |
| ---------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Code Quality**       | Every push and PR, weekly  | Checks lockfile consistency, runs ruff linting, checks formatting, runs type checking with ty, checks the agent instruction files       |
| **Test with Coverage** | Push to `main`, all pull requests, weekly | Runs `uv run pytest` (coverage is on by default in `pyproject.toml`), uploads results to Coveralls, posts a coverage summary comment on the PR |
| **Platform Tests**     | Every push and PR, weekly  | Runs the test suite on Linux, macOS, and Windows with Python 3.14                                                                       |
| **Docs Quality**       | Push to `main`, every pull request, weekly | Checks the language of the docs pages a pull request changes with Vale, and every link of the built site with lychee |
| **Deploy Docs**        | A published release, or started by hand | Builds and deploys the documentation site                                                                                |

The test runs in CI check out the test-data submodule
(`packages/canvod-readers/tests/test_data`), so tests that need it run
there too.

### Test coverage with Coveralls

The project uses [Coveralls](https://coveralls.io/) to track test coverage over time. After each test run in CI:

1. pytest generates a coverage report in LCOV format (`coverage.lcov`)
2. The report is uploaded to [coveralls.io/github/nfb2021/canvodpy](https://coveralls.io/github/nfb2021/canvodpy)
3. A coverage summary is posted as a comment on the pull request, showing which lines are covered and which are not

Coverage is **not** a gate (low coverage does not block your PR), but it is visible to reviewers. When adding new code, include tests. This is both good scientific practice (every computation should be verifiable) and a courtesy to future contributors who need to understand what the code does.

To measure coverage locally before pushing:

```bash
just test-coverage
# Opens an HTML report in your browser showing line-by-line coverage
```

---

## 16. Common commands cheat sheet

!!! tip "Print this"

    | Command                           | What it does                                   |
    | --------------------------------- | ---------------------------------------------- |
    | `just test`                       | Run all tests                                  |
    | `just check`                      | Lint, format, and type-check all code          |
    | `just sync`                       | Install dependencies and git hooks             |
    | `just hooks`                      | Install the git hooks only                     |
    | `just graph`                      | Rebuild the code graph (free, local)           |
    | `just check-dev-tools`            | Verify uv, just, and python3 are installed     |
    | `just config-init`                | Scaffold `canvod-settings.yaml` from template           |
    | `just config-validate`            | Validate the current configuration             |
    | `just config-show`                | Show the resolved configuration                |
    | `just config-check-data <site>`   | Check a site's data files as a run reads them  |
    | `just docs`                       | Preview documentation locally                  |
    | `just docs-lint`                  | Check the language of the docs (Vale)          |
    | `just docs-lint-changed`          | Vale on the pages changed since `origin/main`  |
    | `just docs-links`                 | Check every link of the built docs (lychee)    |
    | `just cli-docs`                   | Write the command-line reference from `--help` |
    | `just cli-docs-check`             | Check that reference against the `--help` texts |
    | `just test-coverage`              | Run tests with coverage report                 |
    | `just clean`                      | Remove build artifacts and caches              |
    | `uv sync`                         | Install/update Python dependencies             |

---

??? question "17. Troubleshooting"

    **"command not found" for uv, just, or git**
    :   The tool is not installed or not on your `PATH`. Re-run the installation step and, if needed, open a new terminal window so your shell picks up the updated `PATH`.

    **"Permission denied (publickey)" when pushing or cloning**
    :   Your SSH key is not set up correctly. Go back to [step 4](#4-set-up-an-ssh-key-for-github) and make sure the key is added to both the SSH agent and your GitHub account.

    **`uv sync` fails with a Python version error**
    :   canVODpy requires Python 3.14. Install a supported version with `uv python install 3.14` and try again.

    **Pre-commit hook fails on commit**
    :   Run `just check`. It will auto-fix most linting and formatting issues. Stage the fixed files and commit again.

    **"push rejected" or "failed to push"**
    :   Your branch is behind the remote. Pull the latest changes first:

        ```bash
        git pull --rebase origin my-feature
        ```

    **Windows: `just` says "could not find the shell" or "system cannot find the path"**
    :   The Justfile expects Git Bash at `C:\Program Files\Git\bin\bash.exe` (the default Git for Windows location). If Git is installed elsewhere, find its location by running in PowerShell:

        ```powershell
        where.exe bash
        ```

        Then update the path in the first lines of the Justfile:

        ```
        set windows-shell := ["C:/YOUR/ACTUAL/PATH/TO/bash.exe", "-c"]
        ```

        !!! warning
            Do **not** commit this change: it's specific to your machine. The default path works for most installations and for CI.

    **Windows: uv install fails with "execution of scripts is disabled"**
    :   PowerShell's default execution policy blocks scripts. Use the bypass flag:

        ```powershell
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        ```

    **Windows: line ending warnings (`LF will be replaced by CRLF`)**
    :   Configure Git to keep Unix-style line endings:

        ```bash
        git config --global core.autocrlf input
        ```

---

**Next in the trail:** [configuration](configuration.md) · [API levels](api-levels.md) · [architecture](../architecture.md) · [AI development](ai-development.md)
