"""The one commit function: root copy, snapshot summary, commit metadata (ADR 0014)."""

from pathlib import Path

import icechunk
import numpy as np
import pytest
import zarr
from canvod.utils import testing

from canvod.store_metadata import commit_with_rebase, write_metadata
from canvod.store_metadata.schema import (
    Creator,
    Instruments,
    Publisher,
    ReceiverInfo,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)

_CONFIG = {"processing": {"batch_hours": 24}}
_UUID = "00000000-0000-4000-8000-000000000001"


def _metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="fangorn-gnss",
            uuid=_UUID,
            naming_authority="org.middle-earth",
            stac_link=(
                "../../gnss-observations/org.middle-earth.fangorn-gnss/"
                "org.middle-earth.fangorn-gnss.json"
            ),
            title="Fangorn GNSS Store",
            description="GNSS observations at Fangorn",
            store_type="gnss_store",
            source_format="rinex3",
            keywords=["GNSS", "VOD"],
        ),
        creator=Creator(
            name="Jane Doe", email="jane@example.org", institution=testing.INSTITUTION
        ),
        publisher=Publisher(name=testing.PUBLISHER, license="CC-BY-4.0"),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00+00:00", updated="2026-01-01T00:00:00+00:00"
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="Fangorn"),
            geospatial_lat=testing.LATITUDE,
            geospatial_lon=testing.LONGITUDE,
            geospatial_alt_m=testing.ALTITUDE_M,
        ),
        instruments=Instruments(
            receivers={
                "canopy_01": ReceiverInfo(type="canopy", directory="canopy"),
                "reference_01": ReceiverInfo(type="reference", directory="reference"),
            }
        ),
    )


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(path))
    )
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")
    write_metadata(path, _metadata())
    return path


def _repo(path: Path) -> icechunk.Repository:
    return icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(path))
    )


def _write_receiver(session: icechunk.Session, name: str, start: str, n: int) -> None:
    group = zarr.open_group(session.store, mode="a").require_group(name)
    epochs = np.arange(
        np.datetime64(start, "ns"), np.timedelta64(n * 5, "s"), np.timedelta64(5, "s")
    )
    group.create_array("epoch", data=epochs.astype("M8[ns]"))
    group.create_array("sid", data=np.array(["G01|L1|C", "E05|E1|C"]))
    group.create_array("SNR", data=np.zeros((n, 2), dtype="f4"))


def _commit(path: Path, write, message: str = "write") -> str:
    session = _repo(path).writable_session("main")
    write(session)
    return commit_with_rebase(session, message, store_path=path, config=_CONFIG)


def _root_attrs(path: Path) -> dict:
    session = _repo(path).readonly_session(branch="main")
    return dict(zarr.open_group(session.store, mode="r").attrs)


def _commit_metadata(path: Path) -> dict:
    repo = _repo(path)
    tip = repo.lookup_branch("main")
    return next(iter(repo.ancestry(snapshot_id=tip))).metadata


class TestRootCopy:
    def test_root_group_carries_cf_and_acdd_attributes(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))

        attrs = _root_attrs(path)
        assert attrs["Conventions"] == "CF-1.11, ACDD-1.3"
        assert attrs["featureType"] == "timeSeries"
        assert attrs["title"] == "Fangorn GNSS Store"
        assert attrs["summary"] == "GNSS observations at Fangorn"
        assert attrs["id"] == "fangorn-gnss"
        assert attrs["naming_authority"] == "org.middle-earth"
        assert attrs["keywords"] == "GNSS, VOD"
        assert attrs["creator_name"] == "Jane Doe"
        assert attrs["creator_type"] == "person"
        assert attrs["publisher_type"] == "institution"
        assert attrs["date_created"] == "2026-01-01T00:00:00+00:00"
        assert (
            attrs["geospatial_lat_min"]
            == attrs["geospatial_lat_max"]
            == testing.LATITUDE
        )
        assert (
            attrs["geospatial_lon_min"]
            == attrs["geospatial_lon_max"]
            == testing.LONGITUDE
        )

    def test_root_group_declares_the_zarr_conventions(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))

        attrs = _root_attrs(path)
        names = {c["name"] for c in attrs["zarr_conventions"]}
        assert names == {"proj", "license", "stac:"}
        assert attrs["proj:code"] == "EPSG:4979"
        assert attrs["license"] == {"spdx": "CC-BY-4.0"}
        assert attrs["stac:link"]["href"] == _metadata().identity.stac_link
        assert attrs["canvod:uuid"] == _UUID

    def test_root_copy_holds_the_repository_metadata(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))

        assert (
            _root_attrs(path)["canvod:repository_metadata"]
            == _repo(path).get_metadata()
        )

    def test_old_metadata_attribute_is_not_written(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))

        assert "canvod_metadata" not in _root_attrs(path)


class TestSnapshotSummary:
    def test_summary_describes_the_committed_data(self, tmp_path):
        path = _store(tmp_path)
        _commit(
            path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01T00:00:00", 4)
        )

        attrs = _root_attrs(path)
        summary = attrs["canvod:snapshot_summary"]
        assert summary["temporal"]["time_coverage_start"] == "2025-01-01T00:00:00Z"
        assert summary["temporal"]["time_coverage_end"] == "2025-01-01T00:00:15Z"
        assert summary["summaries"]["total_epochs"] == 4
        assert summary["receivers"]["canopy_01"]["epochs"] == 4
        assert summary["receivers"]["canopy_01"]["sids"] == 2
        assert attrs["time_coverage_start"] == "2025-01-01T00:00:00Z"
        assert attrs["time_coverage_end"] == "2025-01-01T00:00:15Z"

    def test_concurrent_writers_of_two_receivers_both_commit(self, tmp_path):
        path = _store(tmp_path)
        repo = _repo(path)
        first, second = repo.writable_session("main"), repo.writable_session("main")
        _write_receiver(first, "canopy_01", "2025-01-01T00:00:00", 4)
        _write_receiver(second, "reference_01", "2025-01-01T00:00:00", 6)

        commit_with_rebase(first, "canopy", store_path=path, config=_CONFIG)
        commit_with_rebase(second, "reference", store_path=path, config=_CONFIG)

        receivers = _root_attrs(path)["canvod:snapshot_summary"]["receivers"]
        assert receivers["canopy_01"]["epochs"] == 4
        assert receivers["reference_01"]["epochs"] == 6


def _write_log_book(session: icechunk.Session, name: str, positions, actions) -> None:
    """A log book with one row per file, the header position in its attrs."""
    import json

    table = zarr.open_group(session.store, mode="a").require_group(
        f"{name}/metadata/table"
    )
    n = len(positions)
    table.create_array("rinex_hash", data=np.array([f"h{i}" for i in range(n)]))
    table.create_array("action", data=np.array(actions))
    attrs = [
        json.dumps(
            {"APPROX POSITION X": x, "APPROX POSITION Y": y, "APPROX POSITION Z": z}
            if x is not None
            else {}
        )
        for x, y, z in positions
    ]
    table.create_array("attrs", data=np.array(attrs))


class TestReceiverPosition:
    def test_position_is_the_median_of_the_stored_files_header_positions(
        self, tmp_path
    ):
        path = _store(tmp_path)

        def write(session):
            _write_receiver(session, "canopy_01", "2025-01-01", 4)
            _write_log_book(
                session,
                "canopy_01",
                [
                    (4100000.0, 1200000.0, 4700000.0),
                    (4100002.0, 1200002.0, 4700002.0),
                    (4100010.0, 1200010.0, 4700010.0),
                    (9.0, 9.0, 9.0),  # skipped: not stored
                    (None, None, None),  # no header position
                ],
                ["initial", "appended", "appended", "skipped", "appended"],
            )

        _commit(path, write)

        receiver = _root_attrs(path)["canvod:snapshot_summary"]["receivers"][
            "canopy_01"
        ]
        assert receiver["position_ecef_m"] == [4100002.0, 1200002.0, 4700002.0]

    def test_rinex_approximate_position_text_is_read(self, tmp_path):
        import json

        path = _store(tmp_path)

        def write(session):
            _write_receiver(session, "canopy_01", "2025-01-01", 4)
            table = zarr.open_group(session.store, mode="a").require_group(
                "canopy_01/metadata/table"
            )
            table.create_array("rinex_hash", data=np.array(["h0"]))
            table.create_array("action", data=np.array(["initial"]))
            text = "(X = 4100000.5 m, Y = 1200000.25 m, Z = 4700000.0 m)"
            table.create_array(
                "attrs", data=np.array([json.dumps({"Approximate Position": text})])
            )

        _commit(path, write)

        receiver = _root_attrs(path)["canvod:snapshot_summary"]["receivers"][
            "canopy_01"
        ]
        assert receiver["position_ecef_m"] == [4100000.5, 1200000.25, 4700000.0]


class TestCommitMetadata:
    def test_commit_records_software_environment_and_settings(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))

        meta = _commit_metadata(path)
        assert "canvod-store-metadata" in meta["processing"]["software"]
        assert meta["environment"]["hostname"]
        assert "uv_lock_text" not in meta["environment"]
        assert meta["config"]["processing"] == {"batch_hours": 24}
        assert len(meta["config"]["config_hash"]) == 64

    def test_callers_commit_metadata_is_kept(self, tmp_path):
        path = _store(tmp_path)
        session = _repo(path).writable_session("main")
        _write_receiver(session, "canopy_01", "2025-01-01", 4)
        commit_with_rebase(
            session, "write", {"run_id": "r1"}, store_path=path, config=_CONFIG
        )

        assert _commit_metadata(path)["run_id"] == "r1"

    def test_lockfile_text_is_stored_once_per_hash(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))
        lock_hash = _commit_metadata(path)["environment"]["uv_lock_hash"]
        if lock_hash is None:
            pytest.skip("no uv.lock next to this checkout")

        _commit(path, lambda s: _write_receiver(s, "reference_01", "2025-01-01", 4))

        session = _repo(path).readonly_session(branch="main")
        environments = zarr.open_group(session.store, mode="r")["canvod/environments"]
        assert [name for name, _ in environments.groups()] == [lock_hash]
        lock_text = bytes(environments[f"{lock_hash}/uv_lock"][...]).decode()
        assert "version = 1" in lock_text
        assert bytes(environments[f"{lock_hash}/pyproject_toml"][...]).decode()


class TestCheck:
    def test_a_root_copy_edited_by_hand_refuses_the_next_commit(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))
        session = _repo(path).writable_session("main")
        root = zarr.open_group(session.store, mode="r+")
        copy = dict(root.attrs["canvod:repository_metadata"])
        copy["identity"] = {**copy["identity"], "title": "Edited"}
        root.attrs["canvod:repository_metadata"] = copy
        session.commit("hand edit")

        with pytest.raises(ValueError, match="older canvodpy or edited by hand"):
            _commit(path, lambda s: _write_receiver(s, "reference_01", "2025-01-01", 4))

    def test_an_amendment_since_the_last_commit_carries_into_the_next(self, tmp_path):
        path = _store(tmp_path)
        _commit(path, lambda s: _write_receiver(s, "canopy_01", "2025-01-01", 4))
        repo = _repo(path)
        amended = repo.get_metadata()
        amended["identity"] = {**amended["identity"], "title": "Fangorn GNSS"}
        amended["amendments"] = [
            {
                "field": "identity.title",
                "old": "Fangorn GNSS Store",
                "new": "Fangorn GNSS",
                "reason": "shorter",
                "who": "jane@host",
                "when": "2026-02-01T00:00:00+00:00",
            }
        ]
        repo.set_metadata(amended)

        _commit(path, lambda s: _write_receiver(s, "reference_01", "2025-01-01", 4))

        assert _root_attrs(path)["title"] == "Fangorn GNSS"

    def test_a_store_without_repository_metadata_takes_no_data(self, tmp_path):
        path = tmp_path / "plain"
        repo = icechunk.Repository.create(
            storage=icechunk.local_filesystem_storage(str(path))
        )
        before = repo.lookup_branch("main")
        session = repo.writable_session("main")
        _write_receiver(session, "canopy_01", "2025-01-01", 4)

        with pytest.raises(ValueError, match="no repository metadata"):
            commit_with_rebase(session, "write", store_path=path, config=_CONFIG)

        assert repo.lookup_branch("main") == before
