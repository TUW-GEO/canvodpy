# What was done to stored data is recorded in the stores' log books, not in dataset attributes

Each store keeps a log book of what was written: the source files, their
hashes, and an ordered record of the preprocessing steps (operation,
settings, result) with the versions of the packages whose code ran. Stored
data carry no provenance attributes, so processed and unprocessed data
have the same shape. A write whose preprocessing settings differ from what
the store already holds is refused, and VOD is computed only from canopy
and reference data processed the same way.
