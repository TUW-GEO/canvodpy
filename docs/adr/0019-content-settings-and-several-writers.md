# One set of content settings per store, set by its creator; several runs may write one store

Several runs may write one store at the same time: on one machine to a
local store, and on several machines only to a store on S3. A store
shared by several machines through a network mount (SMB, NFS) is not
supported. Icechunk's commits on a file system are not safe from more
than one machine, and canVODpy's commit lock (a lock file next to the
store) does not hold across machines either. Runs write stores on S3 as
well as in local folders (`processing.storage.stores_root_dir` takes an
S3 URL).

Every canVODpy commit rewrites the attributes of the root group (ADR
0014), so two commits made at the same time always conflict, also when
they write different groups. On a local store `commit_lock` makes them
wait for each other. On S3 there is no lock: Icechunk refuses the commit
that comes second, and the run plans the day again on the new tip and
tries again. A commit is tried up to five times, with a growing, partly
random wait in between (ADR 0016). A file whose epochs are already in
the store from a file with another hash stops the run, checked at the
tip, so two runs that read different copies of a file never both write
it. The text of `uv.lock` is stored in a commit of its own, before the
first data commit that needs it, so two runs with a new lockfile don't
both try to store it in their data commits.

A store keeps one set of **content settings**: the settings that shape
its data. The run that creates the store records them as a fixed field
of its repository metadata. Every later run that writes to the store
must have the same ones, on any machine; a run with other content
settings stops, before it reads a file and again at the tip before each
commit. The error lists each setting with the store's value and the
run's value. There is no override: other content settings mean a new
store. `canvodpy config init --from-store <store>` writes a settings
file from a store's content settings, which is how a second machine
joins a store. The same rule holds for one run after another, since the
problem is not new with several writers: they only make it likelier.

The content settings are:

- the signals kept (the SID mode, preset or list, and the resolved list);
- the observables kept and how they are stored;
- how files are read and paired (RINEX v3 parser, file pairing, receiver
  position mode, ephemeris source);
- the orbit product (agency, product type, clock files);
- all of the preprocessing, statistics included;
- chunk sizes, compression method and level, inline chunk threshold and
  manifest splitting;
- maintenance;
- of each receiver: its type, reader format and paired canopies;
- of a VOD store, also the parameters of each VOD calculator and the
  content settings of the GNSS store the VOD was computed from.

They are stored with the keys of `canvod-settings.yaml`, every default
written out, with a format version, who set them and when, the canVODpy
version, and a hash. Settings that only change how a run is carried out
(workers, memory, caches, folders, logging, credentials, store
strategies) may differ from run to run. Descriptions, creator, publisher
and receiver hardware belong to the repository metadata and change only
by amendment (ADR 0014). The canVODpy version is not a content setting:
every commit records it.

A store moves to another orbit product only as new science, not by a
setting: a store is never written with two products. A later
**provisional branch** may hold the most recent days processed with a
quicker product of the same agency (only the product type differs), for
a near-real-time view. The main branch never holds those days; once the
days with the store's own product are on main, the branch is reset to
main's tip. Until that exists, another product is refused like any other
content setting.

Stores created before content settings existed get them once, with
`canvodpy store migrate-metadata`, from the settings recorded in the
store's first commit. A setting that commit doesn't record is not
guessed: the command stops and lists it. Runs refuse such a store until
then.

## Considered options

- **Record the settings per file and allow differences** (each log-book
  row carries the settings that made it; readers and VOD filter mixed
  data). Flexible for reprocessing, but a store could hold mixed data
  without anyone noticing, and VOD computed across the mix is wrong
  without a loud error.
- **The store holds the settings and runs take them from it**, keeping
  only machine settings local. One truth and no divergence, but it
  changes the settings model (what does a user edit, what does
  `config validate` check?) shortly before v1.0.0. `config init
  --from-store` gives most of its benefit: a run's settings start as the
  store's.
- **An override flag** (`--allow-settings-change`). Explicit, but it puts
  mixed data into a store with one keystroke, and nothing in the store
  would show it afterwards.
- **A `join` command** that fetches a store's settings and starts a run.
  `config init --from-store` does the same and leaves a settings file
  that records how the machine was set up.
- **Writers on several machines through a network mount.** Icechunk
  gives no guarantee there, and a lost commit would go unnoticed.
- **A lock on S3** as on local stores. Icechunk's conditional writes
  already refuse the second of two commits; a lock would need a lock
  service that every machine reaches. A CI test with two runs on one S3
  store (RustFS, the emulator Icechunk's own CI uses) checks that
  nothing is lost without it.

## Consequences

- Each machine keeps its own run history and file index (ADR 0018);
  `canvodpy store maintain-due` sees only the runs of its own machine.
  On S3, maintenance is a dry run only until maintenance with several
  writers is designed.
- A new content setting in a later version is a new format of the
  content settings and needs a migration for existing stores.
