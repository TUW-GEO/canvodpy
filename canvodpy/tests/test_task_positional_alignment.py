"""Regression test: task-tuple values must land on the right parameter.

``prepare_batch_tasks`` builds flat positional tuples with ``_task_args``
that ``pipeline.py``'s ``_submit_task`` splats straight into
``preprocess_with_hermite_aux`` / ``preprocess_reference_with_hermite_aux_fanout``
(after stripping the trailing fan-out marker). Before ``_task_args`` the
tuples were written out by hand and were shifted by one slot: the main
pipeline passed ``broadcast_canopy_file`` as ``store_sbf_raw_observables``
(so SBF raw observables were never stored) and the canopy reader format as
``broadcast_canopy_file``. These tests splat ``_task_args`` tuples the way
``pipeline.py`` does and check that every value arrives by name.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from canvodpy.orchestrator.processor import (
    _task_args,
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition

_POSITION = ECEFPosition(x=1.0, y=2.0, z=3.0)


def _splat(func, task_args: tuple) -> dict:
    """Bind the tuple exactly as pipeline._submit_task passes it."""
    bound = inspect.signature(func).bind(*task_args[:-1])
    bound.apply_defaults()
    return dict(bound.arguments)


def test_non_fanout_tuple_delivers_every_value_to_its_parameter() -> None:
    kwargs = {
        "rnx_file": Path("file.sbf"),
        "keep_vars": ["SNR"],
        "aux_zarr_path": Path("aux.zarr"),
        "receiver_position": _POSITION,
        "receiver_type": "reference_01",
        "keep_sids": ["G01|L1|C"],
        "reader_name": "sbf",
        "use_sbf_geometry": True,
        "store_radial_distance": True,
        "store_sbf_raw_observables": False,
        "broadcast_canopy_file": Path("canopy.sbf"),
        "broadcast_canopy_fmt": "sbf",
        "aux_group": "some-fingerprint/2025213",
    }
    task_args = _task_args(
        preprocess_with_hermite_aux, is_reference_fanout=False, **kwargs
    )

    assert task_args[-1] is False
    assert task_args[3] is _POSITION  # pipeline reads the lane from [3]/[4]
    assert task_args[4] == "reference_01"
    arguments = _splat(preprocess_with_hermite_aux, task_args)
    for name, value in kwargs.items():
        assert arguments[name] == value, name


def test_fanout_tuple_delivers_every_value_to_its_parameter() -> None:
    canopy_positions = {"reference_01_canopy_01": _POSITION}
    kwargs = {
        "rnx_file": Path("ref.sbf"),
        "keep_vars": None,
        "aux_zarr_path": Path("aux.zarr"),
        "canopy_positions": canopy_positions,
        "receiver_type": "reference:ref_dir",
        "keep_sids": None,
        "reader_name": "sbf",
        "store_radial_distance": True,
        "store_sbf_raw_observables": False,
        "aux_group": "some-fingerprint/2025213",
    }
    task_args = _task_args(
        preprocess_reference_with_hermite_aux_fanout,
        is_reference_fanout=True,
        **kwargs,
    )

    assert task_args[-1] is True
    assert task_args[3] is canopy_positions
    assert task_args[4] == "reference:ref_dir"
    arguments = _splat(preprocess_reference_with_hermite_aux_fanout, task_args)
    for name, value in kwargs.items():
        assert arguments[name] == value, name
