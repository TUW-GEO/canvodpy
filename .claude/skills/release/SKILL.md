---
name: release
description: Conduct a canvodpy release across canvodpy, canvodpy-test-data, canvodpy-demo and canvodpy-extensions - checks, versions, release commit, tags, GitHub release, PyPI, and the follow-ups in the other repositories. Use only when the user asks to release.
disable-model-invocation: true
---

# Release canvodpy

`docs/RELEASING.md` is the checklist; this skill holds no steps of its
own. Walk it phase by phase (Before, Release, After), tell the user where
you are, and stop at every gate below. Tags, GitHub releases and PyPI
uploads are public and permanent.

## Gates: the user decides, you never do these

| Gate | What you do | What the user does |
|---|---|---|
| Versions | run `just release-status`, show it, propose increments by the versioning rule (fix: patch; feature, setting or deprecation: minor; removal or store format: major) | chooses the packages and versions |
| Merges | push a feature branch, open the PR | reviews and merges |
| Tags | print `just tag-release` and the push commands | creates and pushes the tags |
| Draft release | check that it exists and links the release notebook | publishes it |
| PyPI | print `gh workflow run publish_pypi.yml --ref vX.Y.Z` | runs it, approves the `pypi` environment |

An agent never merges, approves, pushes `main` or tags, or force-pushes
(`CODING_STANDARDS.md`, Git and GitHub).

## Before

1. Ask the user for the canvodpy version, after showing `just release-status`.
2. Run `just release-check X.Y.Z` on an up-to-date `main` with both
   submodules initialised. Show the output.
3. For every ✗: fix it in a pull request of its own (in canvodpy-demo or
   canvodpy-test-data where the line says so), wait for the merge, run
   the check again. For every ⚠: show it and ask. Don't continue while a
   ✗ is left. A ✗ for an untagged test-data commit means the test data
   needs a release of its own: follow RELEASING.md's Test data item; the
   tag and the GitHub release are the user's.
4. Go through the items of RELEASING.md's Before list that the check can't
   judge (the release notebook and What's new describe the changes users
   notice; an upgrade guide for a major release). Ask the user to confirm
   them.

## Release

5. `just release <package>=X.Y.Z ... canvodpy=X.Y.Z` with the versions
   the user chose. Show `git show --stat`, push `release/vX.Y.Z`, open the
   PR. Wait for the user's merge.
6. Tags, draft release and PyPI: the gates above, in RELEASING.md's order
   (the canvodpy tag pushed on its own).
7. The extensions, canvodpy first: for each extension package the user
   wants released, follow the `release-package` skill of
   canvodpy-extensions. Its release notebook
   (`release-notes/<package>-vX.Y.Z.py`) goes into its release PR.

## After

8. Walk RELEASING.md's After list: PyPI, the published GitHub release,
   the docs site, the demo headers (script header only, prose stays), the
   demo pointer, the install line in `docs/users/index.md`, the
   extensions' docs and lock, Zenodo. Each change is a pull request; open
   them, the user merges.
9. Tell the user what is done and what is left.
