"""Create 1-day RINEX and SBF stores and exercise metadata lifecycle.

Integration tests using the canvod-readers test-data submodule.

Run with: uv run pytest packages/canvod-store-metadata/tests/test_1d_store.py -v -s
"""

import shutil
from pathlib import Path

import pytest
from canvod.utils import testing

_TEST_DATA = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
)
_RINEX_DIR = (
    _TEST_DATA
    / "valid"
    / "rinex_v3_04"
    / "01_Rosalia"
    / "02_canopy"
    / "01_GNSS"
    / "01_raw"
    / "25001"
)
_SBF_DIR = _TEST_DATA / "valid" / "sbf" / "01_Rosalia" / "02_canopy" / "25001"
SKIP_REASON = "Test data submodule not available"


def _build_store_and_metadata(
    store_path,
    datasets,
    *,
    store_id,
    title,
    store_type,
    source_format,
    file_count,
):
    """Shared helper: concat datasets, write to Icechunk, attach metadata."""
    import icechunk
    import xarray as xr

    from canvod.store_metadata import (
        format_metadata,
        read_metadata,
        validate_all,
        write_metadata,
    )
    from canvod.store_metadata.collectors import (
        collect_environment,
        collect_processing_provenance,
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
    from canvod.store_metadata.show import extract_env

    # ── 1. Concat ────────────────────────────────────────────────
    combined = xr.concat(datasets, dim="epoch")
    n_epochs = len(combined.epoch)
    n_sids = len(combined.sid)
    variables = list(combined.data_vars)

    print(
        f"\n{store_type}: {n_epochs} epochs x {n_sids} sids, "
        f"vars={variables[:5]}{'...' if len(variables) > 5 else ''}"
    )

    # ── 2. Create Icechunk store ─────────────────────────────────
    storage = icechunk.local_filesystem_storage(str(store_path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    combined.to_zarr(session.store, group="canopy_01", mode="w")
    snapshot = session.commit(f"Write 1-day {source_format} data")
    print(f"Store: {store_path.name} (snapshot: {snapshot[:8]})")

    # ── 3. Collect and write metadata ────────────────────────────
    time_start = str(combined.epoch.values[0])
    time_end = str(combined.epoch.values[-1])

    meta = StoreMetadata(
        identity=StoreIdentity(
            id=store_id,
            uuid="00000000-0000-4000-8000-000000000001",
            stac_link=(
                f"../../gnss-observations/org.middle-earth.{store_id}/"
                f"org.middle-earth.{store_id}.json"
            ),
            title=title,
            description=(f"1-hour subset of GNSS observations ({source_format})"),
            store_type=store_type,
            source_format=source_format,
            keywords=[
                "GNSS",
                "VOD",
                "Fangorn",
                source_format.upper(),
                "test",
            ],
            naming_authority="org.middle-earth",
        ),
        creator=Creator(
            name=testing.PERSON_NAME,
            email=testing.PERSON_EMAIL,
            institution=testing.INSTITUTION,
            department=testing.DEPARTMENT,
            research_group=testing.RESEARCH_GROUP,
            website=testing.WEBSITE,
        ),
        temporal=TemporalExtent(
            created="2026-03-07T00:00:00Z",
            updated="2026-03-07T00:00:00Z",
            collected_start=time_start,
            collected_end=time_end,
        ),
        spatial=SpatialExtent(
            site=SiteInfo(
                name="Fangorn",
                description="Mixed forest research site",
                country="AT",
            ),
            geospatial_lat=testing.LATITUDE,
            geospatial_lon=testing.LONGITUDE,
            geospatial_alt_m=testing.ALTITUDE_M,
            bbox=[
                testing.LONGITUDE,
                testing.LATITUDE,
                testing.LONGITUDE,
                testing.LATITUDE,
            ],
            extent_temporal_interval=[[time_start, time_end]],
        ),
        processing=collect_processing_provenance(
            store_type,
            source_format,
        ),
        environment=collect_environment(store_path),
        summaries=Summaries(
            total_epochs=n_epochs,
            total_sids=n_sids,
            variables=variables,
            file_count=file_count,
            history=[
                f"2026-03-07: 1-day {source_format} test store created",
            ],
        ),
    )

    write_metadata(store_path, meta)
    print("Metadata written")

    # ── 4. Read back and verify ──────────────────────────────────
    restored = read_metadata(store_path)
    assert restored.identity.id == store_id
    assert restored.summaries.total_epochs == n_epochs
    assert restored.environment.uv_lock_hash is not None
    assert restored.environment.pyproject_toml_text is not None
    assert restored.environment.uv_lock_text is not None
    print("Round-trip verified")

    # ── 5. Full report ───────────────────────────────────────────
    report = format_metadata(restored)
    print("\n" + report)

    # ── 6. Section queries ───────────────────────────────────────
    for section in ["identity", "env", "summaries", "validation"]:
        print(f"\n--- {section} ---")
        print(format_metadata(restored, section=section))

    # ── 7. Reproduce instructions ────────────────────────────────
    print("\n--- reproduce ---")
    print(format_metadata(restored, section="reproduce"))

    # ── 8. Validate ──────────────────────────────────────────────
    results = validate_all(restored)
    print("\nValidation:")
    for std, issues in results.items():
        status = "PASS" if not issues else f"{len(issues)} issues"
        print(f"  {std}: {status}")

    # ── 9. Extract env ───────────────────────────────────────────
    env_dir = store_path.parent / f"repro_env_{source_format}"
    extract_env(store_path, env_dir)
    assert (env_dir / "pyproject.toml").exists()
    assert (env_dir / "uv.lock").exists()
    toml_text = (env_dir / "pyproject.toml").read_text()
    assert "[tool.uv.workspace]" in toml_text
    print(f"Env extracted to {env_dir}")

    print(f"All checks passed for {store_id}!")
    return restored


@pytest.mark.integration
class TestOneDayStore:
    """Build real 1-day stores, write metadata, query it."""

    @pytest.fixture
    def gnss_store_path(self, tmp_path):
        sp = tmp_path / "test_1d_rinex"
        yield sp
        if sp.exists():
            shutil.rmtree(sp)

    @pytest.fixture
    def sbf_store_path(self, tmp_path):
        sp = tmp_path / "test_1d_sbf"
        yield sp
        if sp.exists():
            shutil.rmtree(sp)

    @pytest.mark.skipif(not _RINEX_DIR.exists(), reason=SKIP_REASON)
    def test_build_1d_gnss_store(self, gnss_store_path):
        from canvod.readers.rinex.v3_04 import Rnxv3Obs

        obs_files = sorted(_RINEX_DIR.glob("*.rnx"))[:4]
        assert len(obs_files) >= 4, f"Need >=4 RINEX files, got {len(obs_files)}"

        datasets = []
        for f in obs_files:
            reader = Rnxv3Obs(fpath=f)
            datasets.append(reader.to_ds())

        _build_store_and_metadata(
            gnss_store_path,
            datasets,
            store_id="fangorn-gnss",
            title="Fangorn GNSS Store (1-day test)",
            store_type="gnss_store",
            source_format="rinex3",
            file_count=len(obs_files),
        )

    @pytest.mark.skipif(not _SBF_DIR.exists(), reason=SKIP_REASON)
    def test_build_1d_sbf_store(self, sbf_store_path):
        from canvod.readers.sbf.reader import SbfReader

        sbf_files = sorted(_SBF_DIR.glob("*.sbf"))[:4]
        assert len(sbf_files) >= 4, f"Need >=4 SBF files, got {len(sbf_files)}"

        datasets = []
        for f in sbf_files:
            reader = SbfReader(fpath=f)
            datasets.append(reader.to_ds())

        _build_store_and_metadata(
            sbf_store_path,
            datasets,
            store_id="fangorn-gnss",
            title="Fangorn SBF Store (1-day test)",
            store_type="gnss_store",
            source_format="sbf",
            file_count=len(sbf_files),
        )
