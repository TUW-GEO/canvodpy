# canvod.store API Reference

Versioned data storage using Icechunk.

## Package

::: canvod.store
    options:
      members:
        - MyIcechunkStore
        - create_gnss_store
        - create_vod_store
        - GnssResearchSite
        - IcechunkDataReader

## Store Manager

::: canvod.store.manager

## Data Store

::: canvod.store.store

## Data Reader (deprecated)

`IcechunkDataReader` is left over from development and will be removed with
the next major version. Use `canvodpy run` or
`canvodpy.Site(<site>).pipeline().process_date(<date>)` instead.

::: canvod.store.reader

## Preprocessing

::: canvod.store.preprocessing
