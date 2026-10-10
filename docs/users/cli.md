---
title: CLI quickstart
description: Process your first day of GNSS data with the canvodpy command.
---

# CLI quickstart

This page assumes that you [installed and configured](index.md) canVODpy.

## Process one day

```bash
canvodpy run --site ExampleSite --start 2025001 --end 2025001
```

The run reads the files of each receiver, adds the satellite positions
from the ephemeris products, writes the observations to the site's
Icechunk store, and computes VOD for each receiver pair and writes it to
the VOD store.

To see what a run would process without running it, add `--dry-run`.

## Continue later

Leave out `--start` and the run continues from the last day in the store.
Leave out `--end` and it processes up to today:

```bash
canvodpy run --site ExampleSite
```

## Next steps

- [CLI and Python](../guides/api-levels.md): all options of
  `canvodpy run` and the other commands.
- [Parallel processing](../guides/parallel-processing.md): workers and
  memory limits.
- [Python quickstart](python.md): the same run from Python.
