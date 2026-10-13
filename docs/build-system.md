---
title: Build System
description: Package building and distribution for canVODpy
---

# Build system

canVODpy uses `uv_build` as its build backend: a modern, fast backend from the Astral ecosystem with native namespace package support.

---

## Distribution formats

=== "Wheel (preferred)"

    Pre-built, installed by copying to `site-packages`. No build step at install time.

    ```
    canvod_readers-0.1.0-py3-none-any.whl
    └── canvod/
        └── readers/          ← namespace package (no canvod/__init__.py)
            ├── __init__.py
            └── base.py
    ```

    Filename anatomy: `{name}-{version}-{python}-{abi}-{platform}.whl`.
    The `py3-none-any` suffix means: any Python 3, no native extensions, any platform.

=== "Source Distribution"

    `canvod_readers-0.1.0.tar.gz`: contains source code + metadata.
    Requires a build step during installation. Provided alongside wheels for PyPI.

---

## Build configuration

```toml
# packages/canvod-readers/pyproject.toml
[build-system]
requires      = ["uv_build>=0.13.0,<0.14.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"       # dot → namespace package
include     = ["src/canvod/readers/data/*.dat"]
exclude     = ["src/canvod/readers/tests/"]
```

---

## Building

```bash
# Single package
cd packages/canvod-readers
uv build
# → dist/canvod_readers-0.1.0.tar.gz
# → dist/canvod_readers-0.1.0-py3-none-any.whl

# All packages at once
just dist
```

---

## Package metadata

```toml
[project]
name            = "canvod-readers"
version         = "0.1.0"
description     = "GNSS data format readers for canVODpy"
readme          = "README.md"
license         = {text = "Apache-2.0"}
authors         = [{name = "Nicolas Bader", email = "support@canvodpy.eu"}]
requires-python = ">=3.14"
keywords        = ["gnss", "rinex", "geodesy", "vod"]

classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.14",
    "Topic :: Scientific/Engineering :: GIS",
]

dependencies = ["numpy>=2.0", "xarray>=2024.0"]

[project.urls]
Homepage   = "https://github.com/nfb2021/canvodpy"
Repository = "https://github.com/nfb2021/canvodpy"
Issues     = "https://github.com/nfb2021/canvodpy/issues"
```

---

## Publishing

=== "TestPyPI (test first)"

    ```bash
    cd packages/canvod-readers
    uv build
    uv publish --repository testpypi

    # Verify installation (dependencies come from PyPI)
    uv run --isolated --no-project --with canvod-readers \
      --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
      python -c "import canvod.readers"
    ```

=== "Production PyPI"

    ```bash
    uv build
    uv publish
    ```

=== "Automated (CI/CD)"

    `just release` prepares the release commit for the packages the
    maintainer chose; a maintainer tags the merged commit and starts the
    PyPI publish of the packages tagged there.
    See [Release process](RELEASING.md) for the full release workflow.

---

## Version management

Each package has its own version, following
[Semantic Versioning](https://semver.org/); `canvodpy` pins every package
exactly ([Versioning](VERSIONING.md)). The maintainer chooses the versions:

```bash
just release-status                               # commits per package since its last tag
just release canvod-store=1.1.0 canvodpy=1.1.0    # versions, pins, changelogs, uv.lock
```

`just release` updates `version` of each released package, canvodpy's pins,
the `CHANGELOG.md` files and `uv.lock`, and commits them on a release
branch; it makes no tag (`just tag-release` on the merged commit).

---

## Troubleshooting

!!! failure "`ModuleNotFoundError` after install"
    Verify `module-name` in `pyproject.toml` uses dotted notation:
    ```toml
    module-name = "canvod.readers"    # correct
    # module-name = "canvod_readers"  # wrong: creates regular package
    ```

!!! failure "Wrong package structure in wheel"
    Run `unzip -l dist/*.whl` to inspect contents.
    The wheel must contain `canvod/readers/` but **not** `canvod/__init__.py`.

!!! failure "Build failures"
    ```bash
    uv build --verbose    # detailed diagnostics
    ```
