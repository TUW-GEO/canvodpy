# The STAC catalog sits beside the stores; a release is a tag in each store plus a pinned catalog

All stores under one data root (the `stores_root_dir` of the settings)
are described by one static STAC catalog, written as JSON files at that
root: beside the stores, never inside a store. The catalog has three
collections, `gnss-observations`, `vod` and `gnss-geodesy` (the stores of
the canvod-gnssgeodesy extension), with one item per store. An
item has the site as its point geometry, the time range of the store,
and one asset per stored dataset (a receiver's observations, its SBF
metadata, its log book; a VOD analysis and its log book). Every asset
points at the store and says which group to open. All links and `href` values
are relative, so the same files work on a local disk and on S3, and the
whole data root can be copied or moved.

The catalog is derived: it is written only on request (`write_catalog`
in Python, `--write-catalog` on a run, or the catalog command), and each
write replaces the previous one, rebuilt from every store. If any store
cannot be read, nothing is written and one error lists every such store
(ADR 0004). Links go from the catalog to the stores; a store records no
catalog location except one fixed, relative `stac:link` to where its
own item is.

A store has two identifiers, both fixed fields (ADR 0014): a readable id
`{site}-{gnss|vod|geodesy}`, which with the required naming authority gives a
network-unique item id such as `at.ac.tuwien.rosalia-vod`, and a UUID
generated when the store is created. The UUID is in the item, so opening
a store from an item can refuse a store that was replaced behind the
same path.

A **release** is an Icechunk tag with the same name in every store plus
one catalog under `releases/<tag>/` that pins each store's tag and
snapshot id. Tags never move, so a release catalog stays valid as long
as its tags exist, and it is never rewritten. The catalog written without
a release describes `main` as it was at writing time and records the
snapshot ids too. A release covers every store under the data root;
releasing part of the data is issue #200.

## Considered options

- **The catalog inside each store** (a STAC collection file in the
  store directory, as before). An Icechunk repository directory is not
  a place for other files, nothing links the stores of a network, and a
  release of several stores has nowhere to live.
- **The catalog in a separate place, with absolute `href` values.** The catalog
  would need to know every store's location and each store every
  catalog's location; moving the data breaks it. Absolute URLs for a
  copy published elsewhere can be added later as an option.
- **A STAC API.** A server to run and keep alive; a static catalog is
  read by `pystac`, STAC Browser and `xpystac` and can be loaded into an API
  later.
- **One collection per site.** Sites differ in receivers, not in what
  they produce; grouping by product (observations, VOD) is what users
  search by, and a `related` link joins a site's two items.
- **One asset per store.** A receiver group holds several datasets
  (observations, SBF metadata, log book) with different dimensions; one
  asset could not describe them.
- **Writing the catalog after every run.** A run would fail or slow down
  because of another site's store; writing on request keeps runs
  independent.
- **A release as a catalog only, pinning snapshot ids.** Snapshots expire
  with maintenance; a tag keeps the released state readable.
- **Readable id only, or UUID only.** A readable id can come back for a
  new store at the same path; a UUID alone means nothing to a reader.
