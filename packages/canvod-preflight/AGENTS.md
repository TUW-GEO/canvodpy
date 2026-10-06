# canvod-preflight

The canonical canVOD file name: parsing, building, and finding files whose
named time spans overlap. canvodpy's file discovery and canvod-filemap
(canvodpy-extensions) both import it.

## Where things live

| Path (under `src/canvod/preflight/`) | What |
|---|---|
| `convention.py` | `CanVODFilename`, the field types, `find_overlaps`: the truth for the convention |
| `mapping.py`, `validator.py`, `patterns.py`, `config_models.py`, `cli.py` | Deprecated (mapping and validation API, the `canvod-preflight` command); replaced by naming recipes and `canvodpy config validate` |

Background: `docs/principles.md` (convention), `docs/packages/naming/overview.md`.

## Invariants

- One copy of the convention: here. canvod-filemap imports it; never copy
  it into another package.
- TYPE is a built-in `FileType` or the `file_type` of an installed reader
  plugin (`known_file_types`, which imports the plugins).
- A change to `convention.py` changes which files every run finds. Check
  canvodpy's discovery tests and canvod-filemap with it.

## Tests

```bash
just test-package canvod-preflight
```
