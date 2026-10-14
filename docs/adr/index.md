---
title: Decisions
description: The decisions behind canVODpy that are hard to reverse or surprising without their reasons (architecture decision records)
---

# Decisions

Each page records one decision about canVODpy that is hard to reverse,
would surprise a reader of the code, and was a real choice between
alternatives: what was decided and why. Read the ones about your
change before you start; if your change contradicts one, say so in the
issue or pull request rather than working around it.

New decisions are added while a change is designed
(`/mattpocock-skills:grill-with-docs`, see
[Developing with coding agents](../guides/ai-development.md)), numbered in
order. A decision that is reversed is not deleted: it gets a status
that names the decision replacing it.

| | Decision |
|---|---|
| [0001](0001-versioned-stores.md) | Data live in versioned Icechunk stores: one GNSS store and one VOD store per site |
| [0002](0002-gps-time.md) | All stored epochs are GPS time |
| [0003](0003-receivers-share-a-file-format.md) | The canopy and the reference receiver record the same file format |
| [0004](0004-explicit-over-implicit.md) | Explicit over implicit: fail loudly, no hidden defaults |
| [0005](0005-deprecate-until-next-major.md) | Superseded public code is deprecated, and removed only with the next major version |
| [0006](0006-preprocessing-only-when-set.md) | Preprocessing runs only when the settings ask for it |
| [0007](0007-provenance-in-log-books.md) | What was done to stored data is recorded in the stores' log books |
| [0008](0008-files-found-by-name.md) | Runs find files by their names, in any folder layout |
| [0009](0009-plugins-via-entry-points.md) | Readers and VOD calculators from other packages are plugins |
| [0010](0010-per-package-versions.md) | Each package has its own version; canvodpy pins the exact mix |
| [0011](0011-free-tools-only.md) | Only free tools |
| [0012](0012-agent-development-workflow.md) | Contributors develop with agents through one shared workflow |
| [0013](0013-agents-never-merge.md) | Agents open pull requests; people merge |
| [0014](0014-store-metadata-split.md) | A store's description lives in its repository metadata; each snapshot carries a checked copy |
| [0015](0015-stac-catalog-at-data-root.md) | The STAC catalog sits beside the stores; a release is a tag in each store plus a pinned catalog |
| [0016](0016-day-blocks-and-forked-writes.md) | Each receiver-day is a day block at its own cadence; workers write forks, one commit per day |
| [0018](0018-run-history-in-sqlite.md) | Every run records itself in a run history, one SQLite file per machine |
