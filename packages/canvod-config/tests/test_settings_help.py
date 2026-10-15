"""Tests for the setting help texts and the template's links to them."""

from __future__ import annotations

import re

import pytest

from canvod.config.loader import get_template_dir
from canvod.config.settings_help import (
    DOCS_URL,
    SettingHelp,
    UnknownSettingError,
    all_settings,
    children,
    explain,
    find_setting,
)


def test_every_setting_has_a_description() -> None:
    missing = [s.path for s in all_settings() if not s.description]

    assert missing == []


def test_reserved_settings_are_left_out() -> None:
    paths = {s.path for s in all_settings()}

    assert "processing.storage.statistics_store_name" not in paths
    assert not any(p.startswith("processing.preprocessing.statistics") for p in paths)


def test_a_section_sets_the_defaults_of_its_settings() -> None:
    # epoch has no default on its own model; the GNSS store's section has.
    assert (
        find_setting("processing.icechunk.chunk_strategies.gnss_store.epoch").default
        == "180"
    )
    assert find_setting("vod_store.epoch").default == "17280"


def test_a_setting_without_default_has_to_be_set() -> None:
    assert find_setting("processing.storage.stores_root_dir").default is None


def test_limits_come_from_the_model() -> None:
    assert find_setting("processing.icechunk.compression_level").limits == (
        ">= 0",
        "<= 22",
    )


@pytest.mark.parametrize(
    ("asked", "path"),
    [
        (
            "sites.Fangorn.receivers.canopy_01.directory",
            "sites.<site>.receivers.<receiver>.directory",
        ),
        ("sites.Fangorn", "sites.<site>"),
        ("sites.Fangorn.receivers.canopy_01", "sites.<site>.receivers"),
        ("gnss_store.epoch", "processing.icechunk.chunk_strategies.gnss_store.epoch"),
        ("stores_root_dir", "processing.storage.stores_root_dir"),
        (
            "processing.references.funding[0].funder",
            "processing.references.funding[].funder",
        ),
    ],
)
def test_a_setting_is_found_as_written_in_the_file(asked: str, path: str) -> None:
    assert find_setting(asked).path == path


def test_a_name_of_two_settings_is_refused_with_both() -> None:
    with pytest.raises(UnknownSettingError) as exc:
        find_setting("epoch")

    assert "gnss_store.epoch" in exc.value.args[0]
    assert "vod_store.epoch" in exc.value.args[0]


def test_a_misspelled_setting_names_the_closest() -> None:
    with pytest.raises(UnknownSettingError) as exc:
        find_setting("processing.icechunk.compresion_level")

    assert "processing.icechunk.compression_level" in exc.value.args[0]


def test_a_section_lists_its_settings() -> None:
    names = [
        s.path.rsplit(".", 1)[-1] for s in children(find_setting("chunk_strategies"))
    ]

    assert names == ["gnss_store", "vod_store"]


def test_explain_gives_the_description_default_and_link() -> None:
    setting = find_setting("gnss_store.epoch")

    text = explain("gnss_store.epoch")

    assert setting.description in text
    assert "Default: 180" in text
    assert f"{DOCS_URL}#processing-icechunk-chunk_strategies-gnss_store-epoch" in text


# ── The template links every setting to the reference page ─────────────────

_KEY = re.compile(
    r"^(?P<lead> *)(?P<hash># +)?(?P<dash>- )?(?P<key>[a-z_][a-z0-9_]*):(?: |$)"
)


def _setting_lines(lines: list[str]) -> list[tuple[int, SettingHelp]]:
    """Every line of *lines* that sets a setting, active or commented out."""
    found = []
    stack: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _KEY.match(line)
        if not match:
            continue
        # A commented-out line is indented after its "# ".
        indent = len(match["lead"]) + (len(match["hash"]) - 2 if match["hash"] else 0)
        if match["dash"]:
            indent += 2
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, match["key"]))
        try:
            setting = find_setting(".".join(key for _, key in stack))
        except UnknownSettingError:
            continue  # a word followed by a colon in a comment
        if not setting.section and setting.path.endswith(match["key"]):
            found.append((index, setting))
    return found


def _template() -> list[str]:
    return (
        (get_template_dir() / "canvod-settings.yaml.example").read_text().splitlines()
    )


def test_the_template_links_every_setting_it_names_to_its_entry() -> None:
    lines = _template()
    first: dict[str, int] = {}
    for index, setting in _setting_lines(lines):
        first.setdefault(setting.path, index)

    unlinked = [
        path
        for path, index in first.items()
        if not lines[index - 1].rstrip().endswith("# " + find_setting(path).docs_url)
    ]

    assert len(first) > 80
    assert unlinked == []


def test_every_link_of_the_template_names_a_setting() -> None:
    anchors = {s.anchor for s in all_settings()}
    links = re.findall(re.escape(DOCS_URL) + r"#([\w-]+)", "\n".join(_template()))

    assert links
    assert set(links) <= anchors
