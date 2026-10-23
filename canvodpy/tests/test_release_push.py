"""The release script prints the tag pushes that start the release workflow.

GitHub creates no push event for tags when more than three tags are pushed
at once, so pushing every tag together never drafted the GitHub release of
canvodpy v1.0.0. The canvodpy tag goes in a push of its own.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_release():
    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


release = _load_release()

PACKAGE_TAGS = [
    "canvod-auxiliary-v1.0.0",
    "canvod-config-v1.0.0",
    "canvod-grids-v1.0.0",
    "canvod-store-v1.0.0",
]


def test_the_canvodpy_tag_is_pushed_on_its_own_first() -> None:
    commands = release._push_commands(["v1.0.0", *PACKAGE_TAGS])

    assert commands == [
        "git push origin v1.0.0",
        "git push origin " + " ".join(PACKAGE_TAGS),
    ]


def test_the_canvodpy_tag_comes_first_wherever_it_is_listed() -> None:
    commands = release._push_commands([*PACKAGE_TAGS[:2], "v1.1.0", *PACKAGE_TAGS[2:]])

    assert commands[0] == "git push origin v1.1.0"
    assert commands[1] == "git push origin " + " ".join(PACKAGE_TAGS)


def test_package_tags_alone_are_one_push() -> None:
    assert release._push_commands(PACKAGE_TAGS) == [
        "git push origin " + " ".join(PACKAGE_TAGS)
    ]


def test_the_canvodpy_tag_alone_is_one_push() -> None:
    assert release._push_commands(["v1.0.1"]) == ["git push origin v1.0.1"]


def test_a_package_whose_name_starts_with_v_is_a_package_tag() -> None:
    assert release._push_commands(["v1.2.0", "vortex-v1.0.0"]) == [
        "git push origin v1.2.0",
        "git push origin vortex-v1.0.0",
    ]
