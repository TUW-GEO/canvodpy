"""The release script writes the release version into the citation files.

Zenodo takes a record's version from ``CITATION.cff`` and ``.zenodo.json``;
when they are not updated, a release is archived under the previous version
(canvodpy v0.3.0 became Zenodo version "0.2.2").
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from packaging.version import Version

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

CFF = """cff-version: 1.2.0
title: "Example"
version: 0.2.2
date-released: "2026-04-06"
license: Apache-2.0
"""
ZENODO = {
    "title": "Example",
    "version": "0.2.2",
    "publication_date": "2026-04-06",
    "related_identifiers": [{"identifier": "x", "relation": "isSupplementTo"}],
}
CODEMETA = {"name": "Example", "version": "0.1.0", "datePublished": "2026-02-13"}


@pytest.fixture
def citation_root(tmp_path: Path) -> Path:
    (tmp_path / "CITATION.cff").write_text(CFF)
    (tmp_path / ".zenodo.json").write_text(json.dumps(ZENODO, indent=2) + "\n")
    (tmp_path / "codemeta.json").write_text(json.dumps(CODEMETA, indent=2) + "\n")
    return tmp_path


def test_set_citation_writes_version_and_date(citation_root: Path) -> None:
    release._set_citation(Version("1.0.0b1"), dt.date(2026, 10, 20), citation_root)

    cff = (citation_root / "CITATION.cff").read_text()
    assert "version: 1.0.0b1\n" in cff
    assert 'date-released: "2026-10-20"\n' in cff
    zenodo = json.loads((citation_root / ".zenodo.json").read_text())
    assert zenodo["version"] == "1.0.0b1"
    assert zenodo["publication_date"] == "2026-10-20"
    codemeta = json.loads((citation_root / "codemeta.json").read_text())
    assert codemeta["version"] == "1.0.0b1"
    assert codemeta["datePublished"] == "2026-10-20"


def test_set_citation_changes_nothing_else(citation_root: Path) -> None:
    release._set_citation(Version("1.0.0"), dt.date(2026, 10, 20), citation_root)

    zenodo = json.loads((citation_root / ".zenodo.json").read_text())
    assert zenodo["related_identifiers"] == ZENODO["related_identifiers"]
    assert zenodo["title"] == ZENODO["title"]
    cff = (citation_root / "CITATION.cff").read_text()
    assert cff.replace("1.0.0", "0.2.2").replace("2026-10-20", "2026-04-06") == CFF


def test_set_citation_refuses_a_file_without_the_field(citation_root: Path) -> None:
    (citation_root / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "Example"\n'
    )

    with pytest.raises(SystemExit, match=r"CITATION\.cff"):
        release._set_citation(Version("1.0.0"), dt.date(2026, 10, 20), citation_root)


def test_missing_fields_are_listed_before_anything_is_written(
    citation_root: Path,
) -> None:
    (citation_root / ".zenodo.json").write_text('{"title": "Example"}\n')
    (citation_root / "codemeta.json").unlink()

    missing = release._missing_citation_fields(citation_root)

    assert any(".zenodo.json" in m and "version" in m for m in missing)
    assert any(".zenodo.json" in m and "publication_date" in m for m in missing)
    assert "codemeta.json is missing." in missing
    assert not any("CITATION.cff" in m for m in missing)


def test_the_repository_citation_files_have_every_field() -> None:
    assert release._missing_citation_fields() == []


def test_citation_files_are_release_files() -> None:
    files = release._release_files(release._packages())

    for name in ("CITATION.cff", ".zenodo.json", "codemeta.json"):
        assert ROOT / name in files
