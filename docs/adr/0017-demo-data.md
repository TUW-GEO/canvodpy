# The demo notebooks use only the public interface and fetch demo data by file type from Zenodo

The canvodpy-demo notebooks are tutorials first and a showcase second:
they must run, and they use only what canvodpy offers its users. They
run, in this order of priority, inside a clone of canvodpy-demo, as a
single downloaded file (`uvx marimo edit --sandbox <file or URL>`, also in
VS Code or a container), and on molab. A notebook therefore imports
nothing that sits next to it: none of the helper modules of the
canvodpy-demo repository (paths, downloads, live store, widgets). The only file it may reference is
its style sheet: marimo reads it from a local path only, so a notebook
run as a single file runs without it.

Their input is **demo data**: a small, published subset of the test data
(one day of RINEX 3.04 for both receivers of the Rosalia site, SBF from
00:00 to 02:00; no NMEA until a notebook needs it). `canvodpy.demo_data()`
downloads only the files of the type asked for (`file_type`: RINEX,
SBF, auxiliary files), checks each against an md5 written into
canvodpy, unpacks it, caches it in the OS cache folder (`canvodpy` folder in it, one
folder per data version), and returns the root of that folder, laid out
like the test data, so settings written in code can point at it. Once cached, a
notebook needs no network. It downloads with the download code of
canvod-auxiliary, not a second copy of it.

The demo data sits in three Zenodo records, created and versioned by
hand by the maintainers, under their own account in the canVODpy
community, with the same license and creators as the test data:

1. demo input data, one zip per file type and receiver (Zenodo takes
   about 100 files per record, the demo day has over 200);
2. the auxiliary data of the demo day (SP3 and CLK files and the
   processed Zarr store), marked as possibly out of date;
3. reference stores: one GNSS store per input file type and one VOD
   store each, for tests, development, comparison, and showcasing.

SP3 and CLK files are always fetched from the agencies (ESA without an
account, NASA CDDIS when an Earthdata email is set); record 2 is only
the fallback, used by `demo_data()` and never by the pipeline. The
notebooks show which source the files came from, and compute the
auxiliary data themselves so users see that step. A notebook that needs a
store writes its settings in code and runs `Site(...).pipeline()`; the
store goes into the cache, not a temporary folder.

The records are published with the first release that uses them
(rehearsal `1.0.0b1`). Until canvodpy is on PyPI the notebooks pin it
through git; then each `canvod-*` package is pinned to the released version.

## Considered options

- **The test-data archive (Zenodo record 19708760).** The GitHub
  integration archives the whole canvodpy-test-data repository as one
  1.69 GB zip; every notebook downloaded and unpacked all of it to read a
  few files, and SBF alone is 2.3 GB of it.
- **GitHub release assets or raw files from the test-data repository.**
  Free and per file, but no DOI, and git refuses files over 100 MB.
- **Helper modules next to the notebooks.** They work inside a clone
  only; a single file opened from a URL cannot import its neighbors, and
  a tutorial would teach calls users cannot make.
- **A ready-made store instead of running the pipeline.** Hides the step
  the tutorial is about; the reference stores are offered in addition,
  not instead.
- **A cloud drive or object store opened from the notebook** (molab's
  remote storage, `fsspec`). Google Drive needs every reader to log in; a
  public bucket needs a host and has no DOI; molab's file panel helps
  only the lowest-priority way of running.
- **The OS temp folder for the cache.** Cleared at reboot or after a few
  days, so the data would download again; the cache folder also leaves
  no trace in a sandbox or container that is thrown away.
- **Zenodo as a source for the pipeline.** It holds one demo day only.

## Consequences

- New public function `canvodpy.demo_data()`; the hemisphere selectors in
  `demo/_widgets` move to canvod-viz as `canvod.viz.widgets` with
  anywidget as an optional extra.
- A new data version means a new version of the Zenodo record and new
  checksums in canvodpy, in one pull request.
- Building the reference stores is part of the v1.0.0 release work.
