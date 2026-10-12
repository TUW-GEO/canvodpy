"""Reading the metadata of any snapshot as it was (ADR 0014, #204)."""

from pathlib import Path

import icechunk
import pytest
import zarr

from canvod.store_metadata import (
    RESERVED_GROUP,
    commit_with_rebase,
    read_metadata,
    show_metadata,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    Summaries,
    TemporalExtent,
)

_CONFIG = {"processing": {"batch_hours": 24}}


def _metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="fangorn-gnss",
            uuid="00000000-0000-4000-8000-000000000001",
            naming_authority="org.middle-earth",
            stac_link="../../x/x/x.json",
            title="Fangorn GNSS Store",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(name="T", email="t@example.org", institution="U"),
        temporal=TemporalExtent(created="2026-01-01T00:00:00Z", updated="x"),
        spatial=SpatialExtent(site=SiteInfo(name="Fangorn")),
    )


def _repo(path: Path) -> icechunk.Repository:
    return icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(path))
    )


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    icechunk.Repository.create(storage=icechunk.local_filesystem_storage(str(path)))
    write_metadata(path, _metadata())
    return path


def _commit(path: Path, message: str) -> str:
    session = _repo(path).writable_session("main")
    zarr.open_group(session.store, mode="a").require_group(message)
    return commit_with_rebase(session, message, store_path=path, config=_CONFIG)


def _amend_title(path: Path, title: str) -> None:
    """An amendment as amend_metadata makes it (#205): repository metadata first."""
    repo = _repo(path)
    meta = repo.get_metadata()
    old = meta["identity"]["title"]
    meta["identity"] = {**meta["identity"], "title": title}
    meta["amendments"] = [
        *meta["amendments"],
        {
            "field": "identity.title",
            "old": old,
            "new": title,
            "reason": "clearer title",
            "who": "jane@host",
            "when": "2026-02-01T00:00:00+00:00",
        },
    ]
    repo.set_metadata(meta)


def _old_form_store(tmp_path: Path) -> Path:
    path = tmp_path / "old"
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    old = _metadata().model_copy(
        update={"summaries": Summaries(history=["2025-01-01: Store created"])}
    )
    zarr.open_group(session.store, mode="w").attrs.update(
        {"canvod_metadata": old.model_dump(mode="json")}
    )
    session.commit("old form")
    return path


class TestReadSnapshot:
    def test_a_snapshot_reads_as_it_was_after_a_later_amendment(self, tmp_path):
        path = _store(tmp_path)
        before = _commit(path, "canopy_01")
        _amend_title(path, "Fangorn GNSS")
        _commit(path, "reference_01")

        assert read_metadata(path, snapshot_id=before).identity.title == (
            "Fangorn GNSS Store"
        )
        assert read_metadata(path).identity.title == "Fangorn GNSS"
        assert read_metadata(path, branch="main").amendments[0].reason == (
            "clearer title"
        )

    def test_a_snapshot_before_the_migration_is_read_and_marked(self, tmp_path):
        path = _old_form_store(tmp_path)

        meta = read_metadata(path)

        assert meta.identity.title == "Fangorn GNSS Store"
        assert meta.written_before_migration

    def test_a_current_snapshot_is_not_marked(self, tmp_path):
        path = _store(tmp_path)
        assert not read_metadata(path).written_before_migration


class TestShowMetadata:
    def test_show_names_the_amendments_made_since_the_snapshot(self, tmp_path, capsys):
        path = _store(tmp_path)
        before = _commit(path, "canopy_01")
        _amend_title(path, "Fangorn GNSS")

        show_metadata(path, snapshot_id=before)

        out = capsys.readouterr().out
        assert "Amended since this snapshot" in out
        assert "identity.title" in out
        assert "clearer title" in out

    def test_show_lists_the_history_from_the_commit_log(self, tmp_path, capsys):
        path = _store(tmp_path)
        _commit(path, "canopy_01")
        _commit(path, "reference_01")

        show_metadata(path)

        out = capsys.readouterr().out
        assert out.index("reference_01") < out.index("canopy_01")
        assert "Write store metadata" in out

    def test_show_gives_the_store_size(self, tmp_path, capsys):
        path = _store(tmp_path)
        _commit(path, "canopy_01")

        show_metadata(path, section="summaries")

        assert "Store size (MB)" in capsys.readouterr().out

    def test_show_marks_a_snapshot_before_the_migration(self, tmp_path, capsys):
        show_metadata(_old_form_store(tmp_path))

        out = capsys.readouterr().out
        assert "written before migration" in out
        assert "Store created" in out


class TestDeprecations:
    def test_summaries_history_warns_and_still_reads(self, tmp_path):
        meta = read_metadata(_old_form_store(tmp_path))

        with pytest.warns(FutureWarning, match="commit log"):
            history = meta.summaries.history
        assert history == ["2025-01-01: Store created"]

    def test_from_root_attrs_warns_and_still_reads(self):
        attrs = {"canvod_metadata": _metadata().model_dump(mode="json")}

        with pytest.warns(FutureWarning, match="read_metadata"):
            meta = StoreMetadata.from_root_attrs(attrs)
        assert meta.identity.id == "fangorn-gnss"


def test_the_reserved_group_is_named_canvod():
    assert RESERVED_GROUP == "canvod"
