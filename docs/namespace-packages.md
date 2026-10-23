---
title: Namespace Packages
description: Implementation of Python implicit namespace packages in canVODpy
---

# Namespace packages

canVODpy uses Python 3.3+ **implicit namespace packages** to let eleven independent packages share the `canvod.*` import prefix: a unified API backed by separately installable wheels.

```python
from canvod.readers import Rnxv3Obs
from canvod.auxiliary import Sp3File
from canvod.grids import EqualAreaBuilder
from canvod.store import MyIcechunkStore
```

---

## How it works

A namespace package is created by **omitting `__init__.py`** from the shared parent directory. Python treats a directory without `__init__.py` as a namespace that multiple packages can contribute to.

=== "Namespace layout"

    ```
    canvod-readers/src/
      canvod/                  ← namespace directory, NO __init__.py
        readers/
          __init__.py          ← regular package starts here
          base.py

    canvod-auxiliary/src/
      canvod/                  ← same namespace, different package
        auxiliary/
          __init__.py
    ```

=== "Regular package (wrong)"

    ```
    src/
      canvod/
        __init__.py      ← Makes canvod a REGULAR package
        readers/         ← Blocks other packages from contributing
    ```

    If any installed package adds `canvod/__init__.py`, it claims
    exclusive ownership of `canvod`, breaking all other sub-packages.

=== "Combined site-packages"

    After `uv sync` installs all packages:

    ```
    site-packages/
      canvod/             ← Python merges all contributors here
        readers/          ← from canvod-readers
        auxiliary/        ← from canvod-auxiliary
        grids/            ← from canvod-grids
        vod/              ← from canvod-vod
        store/            ← from canvod-store
        store_metadata/   ← from canvod-store-metadata
        viz/              ← from canvod-viz
        config/           ← from canvod-config
        utils/            ← from canvod-utils
        ops/              ← from canvod-ops
        preflight/        ← from canvod-preflight
    ```

---

## Build configuration

The `uv_build` backend uses a dotted `module-name` to produce the correct wheel structure:

```toml
# packages/canvod-readers/pyproject.toml
[build-system]
requires      = ["uv_build>=0.13.0,<0.14.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"   # dot → namespace package
```

The dot in `"canvod.readers"` tells uv_build:

1. Treat `canvod/` as a namespace (do not include `__init__.py` for it).
2. Package only the `readers/` subdirectory and its contents.

---

## Wheel contents

```
canvod_readers-0.1.0-py3-none-any.whl
  canvod/
    readers/                 ← package starts here (has __init__.py)
      __init__.py
      base.py
  canvod_readers-0.1.0.dist-info/
    METADATA
    WHEEL
    RECORD
```

!!! note
    The wheel contains `canvod/readers/` but no `canvod/__init__.py`.
    This is correct: the absence of `__init__.py` is what makes it a namespace.

---

## Import resolution

When Python processes `from canvod.readers import Rnxv3Obs`:

1. `canvod`: no `__init__.py` found $\rightarrow$ **namespace package** (open for extension).
2. `readers`: has `__init__.py` $\rightarrow$ **regular package** (standard import).
3. `Rnxv3Obs`: imported from `canvod/readers/__init__.py`.

---

## Independent installation

Because each sub-package is self-contained, users install only what they need:

```bash
uv add canvod-readers                # readers only
uv add canvod-readers canvod-store   # subset
uv add canvodpy                      # everything
```

---

## Verification

```python
import canvod

print(canvod.__file__)  # AttributeError: namespace packages have no __file__

from canvod import readers

print(readers.__file__)  # e.g. …/site-packages/canvod/readers/__init__.py
```

---

## Common pitfalls

!!! failure "Adding `__init__.py` to the namespace directory"
    `src/canvod/__init__.py` converts the namespace into a regular package,
    preventing all other packages from contributing to `canvod.*`.

!!! failure "Incorrect `module-name`"
    ```toml
    # WRONG: creates a regular top-level package
    module-name = "canvod_readers"

    # CORRECT: creates a namespace sub-package
    module-name = "canvod.readers"
    ```
