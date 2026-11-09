"""The saved fuzz inputs replay on every platform, without atheris.

``fuzz/corpus/<target>`` holds the seed inputs, ``fuzz/crashes/<target>``
the inputs that once found a bug. Each must end as the harness
``fuzz/fuzz_<target>.py`` allows, so a fixed bug stays fixed.
"""

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

FUZZ = Path(__file__).resolve().parents[1]
TARGETS = sorted(path.stem.removeprefix("fuzz_") for path in FUZZ.glob("fuzz_*.py"))
INPUTS = sorted(
    path
    for folder in ("corpus", "crashes")
    for path in (FUZZ / folder).glob("*/*")
    if path.is_file()
)


@cache
def _harness(target: str) -> ModuleType:
    # the harnesses import their shared module, fuzz/fuzzing.py
    if str(FUZZ) not in sys.path:
        sys.path.insert(0, str(FUZZ))
    path = FUZZ / f"fuzz_{target}.py"
    spec = importlib.util.spec_from_file_location(f"fuzz_{target}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("target", TARGETS)
def test_every_target_has_seed_inputs(target: str) -> None:
    assert any((FUZZ / "corpus" / target).iterdir())


@pytest.mark.parametrize(
    "path",
    INPUTS,
    ids=lambda path: f"{path.parent.parent.name}/{path.parent.name}/{path.name}",
)
def test_saved_input_replays(path: Path) -> None:
    _harness(path.parent.name).fuzz_one_input(path.read_bytes())
