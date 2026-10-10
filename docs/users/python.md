---
title: Python quickstart
description: Process your first day of GNSS data with Site.pipeline().
---

# Python quickstart

This page assumes that you [installed and configured](index.md) canVODpy.

## Process one day

```python
from canvodpy import Site

site = Site("ExampleSite")
with site.pipeline() as pipeline:
    data = pipeline.process_date("2025001")
vod = site.vod.compute_day_all(data)
```

`process_date` reads the files of each receiver, adds the satellite
positions from the ephemeris products, and writes the observations to the
site's Icechunk store. It returns one dataset per receiver.
`compute_day_all` computes VOD for every receiver pair in
`canvod-settings.yaml` and writes it to the site's VOD store.

## Process a period

`process_range` processes several days and returns the datasets of one
day at a time:

```python
with site.pipeline() as pipeline:
    for date, data in pipeline.process_range("2025001", "2025007"):
        vod = site.vod.compute_day_all(data)
```

## Next steps

- [CLI and Python](../guides/api-levels.md): the `Site` and `Pipeline`
  objects in detail.
- [Parallel processing](../guides/parallel-processing.md): `n_workers`
  and memory limits.
- [CLI quickstart](cli.md): the same run from the command line.
