# A store's description lives in its repository metadata; each snapshot carries a checked copy

A store's metadata has three parts, each kept where Icechunk keeps that
kind of information:

- **Repository metadata** (Icechunk's repository-level metadata, on no
  branch and in no snapshot) is the source of truth for what describes
  the store as a whole: identity, creator, publisher and license, site
  and position, receivers or VOD analyses, references. It is written
  once, by the call that creates the store. Its **fixed fields** (id,
  UUID, store type, source format, naming authority, creation date)
  never change. The id is `{site}-{gnss|vod|geodesy}`, from the site name made
  lowercase and checked; the UUID is generated when the store is
  created; the naming authority (reverse DNS) is required then (ADR
  0015), and so are a description of the site's stores (set per site),
  the publisher (DataCite) and the license (STAC). Its **amendable fields** change only by **amendment**: one
  explicit command (`canvodpy store amend`, or `amend_metadata` in
  Python) that needs a reason and records the old and new value, the
  reason, who and when.
- The **snapshot summary** (time coverage, per-receiver counts,
  ranges and position, constellations, variables, size) describes what
  one snapshot holds. It is computed when data is written and stored in the root
  group in the same commit, so it cannot disagree with the data.
- **Commit metadata** (Icechunk's per-commit metadata) records how a
  commit was made: software versions, environment, the settings and
  their hash, and the hash of the `uv.lock` in use. The text of
  `uv.lock` and `pyproject.toml` is stored once per distinct hash, in
  the group environments inside the reserved group `canvod`, in the
  commit that first uses it.

The root group carries a lossless copy of the repository metadata in
standard form (flat CF and ACDD global attributes, `featureType =
"timeSeries"`, `zarr_conventions` for `cf`, `proj:`, `license`, `uom`
and `stac`, whose `stac:link` points to the store's item in the catalog,
ADR 0015), with the fields that have no standard name under the
`canvod:` prefix, plus the snapshot summary. Every commit goes through
one commit function that generates this copy from the current repository
metadata and refuses the commit if the copy differs. Each snapshot
therefore shows its store as it was when it was committed, also after an
amendment, on every branch, and to every tool that reads only the
Zarr metadata of the root group.

A run that writes a receiver (GNSS store) or a VOD analysis (VOD store)
not listed in the repository metadata is refused; the error names the
amend command that adds it. A failed metadata write fails the commit and
the run (ADR 0004), with a message that says how to fix it. Existing
stores are moved to this form by one explicit command; a store not yet
moved is refused with a message naming that command. Snapshots from
before the move keep the old single `canvod_metadata` attribute and are
read as such until v2.0.0. The run history is read from the commit log;
the stored `summaries.history` is deprecated (ADR 0005).

## Considered options

- **Root group attributes only**, as before. They are part of every
  snapshot, so each branch carries its own copy, nothing stops a later
  write from changing the store's identity, and checking against the
  first snapshot fails once old snapshots expire.
- **Repository metadata only.** xarray, compliance-checker, `zarr-cm` and
  the Zarr STAC convention read only the Zarr metadata of the root group, so the
  standard forms would be invisible.
- **Never changeable.** Typos happen, and new publications with their DOI appear; with
  no recorded way to change them, people would edit stores by hand.
  Icechunk cannot make repository metadata immutable anyway (it can be
  replaced); canVODpy refuses changes and Icechunk's operations log keeps
  a backup of every change.
- **Snapshot summary computed on read.** Always current, but every read
  scans the coordinates of every group, and standard tools see nothing.
- **The lockfile text in the metadata of every commit.** About 160 KB
  compressed per commit, read with every snapshot; stored once per hash,
  the hash of each commit points to text that its own snapshot holds.
- **Reading both the old and the new form until v2.0.0** for whole
  stores. Two readers for one job, and a store's state would depend on
  which one ran; one explicit migration keeps a single form.
