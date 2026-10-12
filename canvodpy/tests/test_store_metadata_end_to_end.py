"""A run on the test data leaves a GNSS store with complete metadata (ADR 0014)."""

import icechunk
import pytest
import zarr

from canvod.store_metadata import read_metadata


@pytest.mark.integration
def test_one_day_leaves_complete_store_metadata(rosalia_one_day):
    config, _ = rosalia_one_day
    store_path = config.processing.storage.get_gnss_store_path("fangorn")
    repo = icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(store_path))
    )

    repository = repo.get_metadata()
    assert repository["identity"]["id"] == "fangorn-gnss"
    assert repository["identity"]["naming_authority"] == "org.middle-earth"
    assert set(repository["instruments"]["receivers"]) == {
        "canopy_01",
        "reference_01",
    }

    session = repo.readonly_session(branch="main")
    attrs = dict(zarr.open_group(session.store, mode="r").attrs)
    assert attrs["Conventions"] == "CF-1.11, ACDD-1.3"
    assert attrs["canvod:repository_metadata"] == repository
    receivers = attrs["canvod:snapshot_summary"]["receivers"]
    for name in ("canopy_01", "reference_01"):
        assert receivers[name]["epochs"] > 0
        x, y, z = receivers[name]["position_ecef_m"]
        assert 6.3e6 < (x**2 + y**2 + z**2) ** 0.5 < 6.4e6

    tip = repo.lookup_branch("main")
    commit = next(iter(repo.ancestry(snapshot_id=tip)))
    assert len(commit.metadata["config"]["config_hash"]) == 64
    assert commit.metadata["processing"]["software"]

    meta = read_metadata(store_path)
    assert meta.identity.uuid == repository["identity"]["uuid"]
    assert meta.summaries.total_epochs
