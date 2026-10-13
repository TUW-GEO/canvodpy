# canvod-config

`canvod-config` reads `canvod-settings.yaml` and checks it with
[Pydantic](https://docs.pydantic.dev/) models. Every other canVODpy
package gets its settings from these models.

This page describes the Python side. To write the settings file, see the
[Configuration guide](../../guides/configuration.md).

---

## Load the settings

```python
from canvod.config import load_config

config = load_config()

config.processing.metadata.author
config.processing.storage.stores_root_dir
config.sites.sites["ExampleSite"].receivers["canopy_01"].directory
config.sids.mode
```

`load_config()` finds the settings file the same way the command line
does; see
[Where canVODpy finds the settings](../../guides/configuration.md#where-canvodpy-finds-the-settings).
To load a file from another folder, pass the folder:
`load_config(Path("my_config"))`. To apply an
[overlay file](../../guides/configuration.md#overlay-file), pass
`config_file=`.

Fields you leave out of the file take their defaults.

---

## The models

`load_config()` returns a `CanvodConfig`, with one model per section of
the file:

| Attribute | Model | Holds |
|-----------|-------|-------|
| `config.processing` | `ProcessingConfig` | metadata, credentials, ephemeris products, processing parameters, compression, storage, logging, preprocessing |
| `config.sites.sites` | `dict[str, SiteConfig]` | one entry per site with its receivers and VOD analyses |
| `config.sids` | `SidsConfig` | the signals to keep: `all`, a `preset`, or a `custom` list |

The [API reference](../../api/canvod-config.md) lists every field, its
type and its default.

---

## Errors

`load_config()` checks the whole file before any processing starts. A
wrong field raises `ConfigValidationError` with the location of the
error. A misspelled field name is never corrected; the error names the
closest allowed name:

```text
storage.gnss_store_stratgy
  Unknown key 'gnss_store_stratgy'. Did you mean 'gnss_store_strategy'?
```

From the command line, `canvodpy config validate` runs the same check.

!!! example "Try it in a notebook"

    Open [Configuration](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_configuration.py?mode=edit) in molab, the online notebook service of marimo.
