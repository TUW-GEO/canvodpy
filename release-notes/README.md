# Release notebooks

Every minor and major release of canVODpy has a [marimo](https://marimo.io)
notebook here that shows what is new and how to use it, next to the
[changelog](../CHANGELOG.md). Each pins the release it describes. Cells run
on the demo data where they can; others show code that needs your own data.

| Release | Open |
|---|---|
| [v1.1.0](v1.1.0.py): broadcast ephemeris from RINEX navigation files | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/TUW-GEO/canvodpy/blob/main/release-notes/v1.1.0.py) |

To write one, copy `_template.py` to `vX.Y.Z.py`;
[Release process](https://canvodpy.eu/RELEASING/) says when. CI checks
their format (`just check-release-notes`) but doesn't run them.
