"""Reference files take the geometry of their own canopy's file (broadcast mode).

In broadcast + shared position mode, ``prepare_batch_tasks`` gives each
reference file the file of its paired canopy that starts at the same time,
matched by the start time of the canonical names (any physical naming).
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock

from canvodpy.orchestrator.discovery import ReceiverDay
from canvodpy.orchestrator.processor import (
    RinexDataProcessor,
    preprocess_with_hermite_aux,
)

# physical name -> canonical name
_FILES = {
    "canopy_01": {
        "c1_a.sbf": "FANA01INK_R_20250012300_15M_05S_AA.sbf",
        "c1_b.sbf": "FANA01INK_R_20250012315_15M_05S_AA.sbf",
    },
    "canopy_02": {
        "c2_a.sbf": "FANA02INK_R_20250012300_15M_05S_AA.sbf",
        "c2_b.sbf": "FANA02INK_R_20250012315_15M_05S_AA.sbf",
    },
    "reference_01": {
        "r_a.sbf": "FANR01INK_R_20250012300_15M_05S_AA.sbf",
        "r_b.sbf": "FANR01INK_R_20250012315_15M_05S_AA.sbf",
        "r_c.sbf": "FANR01INK_R_20250012330_15M_05S_AA.sbf",
    },
}


def _day(receiver: str) -> ReceiverDay:
    return ReceiverDay(receiver, Path("/data") / receiver, "2025001")


def _processor() -> RinexDataProcessor:
    proc = object.__new__(RinexDataProcessor)
    proc._config = MagicMock()
    proc._config.processing.params.receiver_position_mode = "shared"
    proc._config.processing.params.rinex_v3_parser = "validated"
    proc._config.processing.params.store_radial_distance = False
    proc._config.processing.params.store_sbf_raw_observables = True
    proc.use_sbf_geometry = True
    proc.keep_sids = None
    proc._reader_name = "sbf"
    proc._logger = MagicMock()
    proc.matched_data_dirs = MagicMock()
    proc.matched_data_dirs.yyyydoy.to_str.return_value = "2025001"
    proc._canonical_names = {
        Path("/data") / receiver / physical: canonical
        for receiver, files in _FILES.items()
        for physical, canonical in files.items()
    }
    proc._get_rinex_files = lambda day, _fmt=None: sorted(
        Path("/data") / day.receiver / name for name in _FILES[day.receiver]
    )
    proc._compute_receiver_position = MagicMock(return_value=MagicMock())
    return proc


def test_reference_takes_its_own_canopys_file_by_start_time() -> None:
    proc = _processor()
    receiver_configs = [
        ("canopy_01", "canopy", _day("canopy_01"), None, "sbf"),
        ("canopy_02", "canopy", _day("canopy_02"), None, "sbf"),
        (
            "reference_01_canopy_01",
            "reference",
            _day("reference_01"),
            _day("canopy_01"),
            "sbf",
        ),
        (
            "reference_01_canopy_02",
            "reference",
            _day("reference_01"),
            _day("canopy_02"),
            "sbf",
        ),
    ]

    tasks, _ = proc.prepare_batch_tasks(["SNR"], receiver_configs)

    names = list(inspect.signature(preprocess_with_hermite_aux).parameters)
    canopy_file_of = {
        (args["receiver_type"], args["rnx_file"].name): args["broadcast_canopy_file"]
        for args in (dict(zip(names, task[:-1], strict=True)) for task in tasks)
    }
    assert canopy_file_of[("reference_01_canopy_01", "r_a.sbf")].name == "c1_a.sbf"
    assert canopy_file_of[("reference_01_canopy_01", "r_b.sbf")].name == "c1_b.sbf"
    assert canopy_file_of[("reference_01_canopy_02", "r_a.sbf")].name == "c2_a.sbf"
    assert canopy_file_of[("reference_01_canopy_02", "r_b.sbf")].name == "c2_b.sbf"
    # No canopy file starts at 23:30: own geometry, with a warning
    assert canopy_file_of[("reference_01_canopy_01", "r_c.sbf")] is None
    assert canopy_file_of[("canopy_01", "c1_a.sbf")] is None
    warnings = [c.args[0] for c in proc._logger.warning.call_args_list if c.args]
    assert warnings.count("no_canopy_file_for_reference_geometry") == 2
