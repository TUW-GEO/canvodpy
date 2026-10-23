"""Tests for the RINEX v3.05 stripped (SNR-only) reader."""

from pathlib import Path

import numpy as np
import pytest

from canvod.readers.rinex import Rnxv3Obs, Rnxv3StrippedObs, StrippedRinexError

TEST_DATA_DIR = Path(__file__).parent / "test_data"
STRIPPED_ROOT = TEST_DATA_DIR / "valid/rinex_v3_05_stripped/01_ExampleSite"

CANOPY_10S = STRIPPED_ROOT / "01_canopy/25001/EXPA01MPI_R_20250010000_10S_01S_AA.rnx"
REFERENCE_10S = (
    STRIPPED_ROOT / "01_reference/25001/EXPR01MPI_R_20250010000_10S_01S_AA.rnx"
)
FULL_RINEX_V3 = (
    TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/"
    "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
)


@pytest.fixture
def canopy_file():
    if not CANOPY_10S.exists():
        pytest.skip(f"Stripped canopy test file not found: {CANOPY_10S}")
    return CANOPY_10S


class TestStrippedHeaderAndGuard:
    def test_loads_v3_05_header(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        assert reader.header.version == pytest.approx(3.05)
        assert reader.source_format == "rinex3_stripped"

    def test_all_obs_codes_are_snr(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        for system, codes in reader.header.obs_codes_per_system.items():
            for code in codes:
                assert code.startswith("S"), (
                    f"system {system} has non-SNR code {code!r}"
                )

    def test_rejects_full_rinex_file(self):
        if not FULL_RINEX_V3.exists():
            pytest.skip(f"Full RINEX v3 sample not found: {FULL_RINEX_V3}")
        with pytest.raises((StrippedRinexError, ValueError)) as exc:
            Rnxv3StrippedObs(fpath=FULL_RINEX_V3, completeness_mode="off")
        # pydantic wraps the error — check the message somewhere in the chain
        assert "stripped" in str(exc.value).lower()


class TestStrippedDataset:
    def test_to_ds_structure(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        ds = reader.to_ds()

        assert set(ds.dims) == {"epoch", "sid"}
        assert ds.sizes["epoch"] == 11
        assert ds.sizes["sid"] > 0

        # SNR is the *only* data variable produced by the stripped reader
        assert set(ds.data_vars) == {"SNR"}

        # Required coords from the reader contract
        for coord in (
            "epoch",
            "sid",
            "sv",
            "system",
            "band",
            "code",
            "freq_center",
            "freq_min",
            "freq_max",
        ):
            assert coord in ds.coords

        assert "File Hash" in ds.attrs

    def test_known_snr_values(self, canopy_file):
        """Spot-check a few hand-picked SNR values from the example file.

        First epoch is ``2025-01-01 00:00:00``.  These values are read directly
        from the columnar layout of the file's first epoch:

            G01        49.923          41.776          52.020 ...
            C09                        28.986
        """
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        ds = reader.to_ds()

        first = ds.isel(epoch=0)
        snr_first = first["SNR"]
        sids = ds["sid"].values.tolist()

        def lookup(sid: str) -> float:
            return float(snr_first.values[sids.index(sid)])

        # G01: GPS, header obs codes "S1C S1W S2L S2W S5Q"
        assert lookup("G01|L1|C") == pytest.approx(49.923, abs=1e-3)
        assert lookup("G01|L1|W") == pytest.approx(41.776, abs=1e-3)
        assert lookup("G01|L2|L") == pytest.approx(52.020, abs=1e-3)
        assert lookup("G01|L2|W") == pytest.approx(41.776, abs=1e-3)
        assert lookup("G01|L5|Q") == pytest.approx(54.356, abs=1e-3)
        # C09: BeiDou, header obs codes "S1P S2I S5P S6I S7D S7I".
        # Only S2I is filled in the first epoch (BeiDou band 2 = B1I).
        assert lookup("C09|B1I|I") == pytest.approx(28.986, abs=1e-3)
        assert np.isnan(lookup("C09|B1C|P"))

    def test_epoch_timestamps_monotonic(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        ds = reader.to_ds()
        epochs = ds["epoch"].values
        assert np.all(np.diff(epochs).astype("timedelta64[s]") > np.timedelta64(0, "s"))
        # 1 second sampling
        delta = (epochs[1] - epochs[0]).astype("timedelta64[s]")
        assert delta == np.timedelta64(1, "s")

    def test_event_epoch_skipped(self, canopy_file, tmp_path):
        # A flag-4 header record at the first epoch's timestamp must not
        # become an extra (duplicate) epoch.
        lines = canopy_file.read_text().splitlines(keepends=True)
        eoh = next(i for i, ln in enumerate(lines) if "END OF HEADER" in ln)
        first_epoch = lines[eoh + 1]
        event = first_epoch[:31] + "4  1\n" + "COMMENT".rjust(67) + "\n"
        lines.insert(eoh + 1, event)
        fpath = tmp_path / canopy_file.name
        fpath.write_text("".join(lines))

        reader = Rnxv3StrippedObs(fpath=fpath, completeness_mode="off")
        assert reader.to_ds().sizes["epoch"] == 11

    def test_completeness_inferred(self, canopy_file):
        # Default strict mode should *pass* on a clean 10-second / 1-Hz slice.
        reader = Rnxv3StrippedObs(fpath=canopy_file)
        assert reader.num_epochs == 11

    def test_iter_epochs_works(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        epochs = list(reader.iter_epochs())
        assert len(epochs) == 11

    def test_not_a_full_reader_instance_check(self, canopy_file):
        reader = Rnxv3StrippedObs(fpath=canopy_file, completeness_mode="off")
        # Subclass relationship is intentional — re-uses Rnxv3Obs machinery
        assert isinstance(reader, Rnxv3Obs)


@pytest.mark.integration
class TestStrippedReferenceFile:
    """Tests against the full-day reference file (~290 MB).

    Skipped unless the file actually exists.  Run with ``-m integration``.
    """

    def test_reference_file_loads(self):
        if not REFERENCE_10S.exists():
            pytest.skip(f"Reference file not found: {REFERENCE_10S}")
        reader = Rnxv3StrippedObs(fpath=REFERENCE_10S, completeness_mode="off")
        ds = reader.to_ds()
        assert set(ds.data_vars) == {"SNR"}
        assert ds.sizes["epoch"] > 0
        assert "File Hash" in ds.attrs
