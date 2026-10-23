# The demo notebooks use only the public interface and fetch demo data by file type from Hugging Face

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
downloads only the kind of data asked for (`kind`: RINEX,
SBF, auxiliary files), checks each against a sha256 written into
canvodpy, unpacks it, caches it in the OS cache folder (`canvodpy` folder in it, one
folder per data version), and returns the root of that folder, laid out
like the test data, so settings written in code can point at it. Once cached, a
notebook needs no network. It downloads with the download code of
canvod-auxiliary, not a second copy of it.

The demo data sits in one public Hugging Face dataset,
[nfb2021/canvodpy-demo-data](https://huggingface.co/datasets/nfb2021/canvodpy-demo-data),
uploaded and versioned by hand by the maintainers, with the same
license as the test data. `demo_data()` names one commit of it, so the
files can't change under a released canvodpy. It holds:

1. demo input data, one zip per file type and receiver;
2. the auxiliary data of the demo day (SP3 and CLK files and the
   processed Zarr store), marked as possibly out of date;
3. reference stores: one GNSS store per input file type and one VOD
   store each, for tests, development, comparison, and showcasing.

The demo data must download fast: a user trying canvodpy waits for it.
The dataset serves 13 to 26 MB/s (measured 2026-10-14), so all five
zips (353 MB) take about 20 seconds; SBF stays at two hours for the
same reason. The demo data is a subset of the test data, which is
archived on Zenodo ([all versions](https://doi.org/10.5281/zenodo.19708759)), and `just demo-archives`
rebuilds the zips from it byte for byte, so the dataset needs no archive
of its own.

SP3 and CLK files are always fetched from the agencies (ESA without an
account, NASA CDDIS when an Earthdata email is set); the auxiliary zip is only
the fallback, used by `demo_data()` and never by the pipeline. The
notebooks show which source the files came from, and compute the
auxiliary data themselves so users see that step. A notebook that needs a
store writes its settings in code and runs `Site(...).pipeline()`; the
store goes into the cache, not a temporary folder.

The dataset is published with the first release that uses it
(rehearsal `1.0.0b1`). Until canvodpy is on PyPI the notebooks pin it
through git; then each `canvod-*` package is pinned to the released version.

## Considered options

- **The test-data archive (Zenodo record 19708760).** The GitHub
  integration archives the whole canvodpy-test-data repository as one
  1.69 GB zip; every notebook downloaded and unpacked all of it to read a
  few files, and SBF alone is 2.3 GB of it.
- **Zenodo records for the demo data.** Two were published on
  2026-10-14 and dropped the same day: Zenodo served 0.07 to 1.4 MB/s,
  so the auxiliary zip took 18 minutes (7 seconds from Hugging Face),
  and a second DOI for a subset of archived test data only confused.
- **Hugging Face and Zenodo together** (Hugging Face first, Zenodo as
  fallback): two uploads and two hashes to keep in step for every data
  version.
- **Raw files instead of zips on Hugging Face.** Easy to browse, and per
  hour, but `demo_data()` would send hundreds of requests per call, and
  Hugging Face limits anonymous ones.
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
- A new data version means a new commit of the Hugging Face dataset and
  the new commit and checksums in canvodpy, in one pull request.
- Building the reference stores is part of the v1.0.0 release work.
