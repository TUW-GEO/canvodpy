"""The deprecated SingleReceiverProcessor refuses to process (A20 #2).

Its process() relied on a processor method that has been removed. It now
raises at once with a message naming the replacement, instead of an
AttributeError after discovering the files.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from canvodpy.orchestrator.pipeline import SingleReceiverProcessor

from canvod.utils.tools import YYYYDOY


def test_process_names_the_replacement(tmp_path: Path) -> None:
    site = SimpleNamespace(site_name="Fangorn")
    with pytest.warns(FutureWarning, match="process_date"):
        processor = SingleReceiverProcessor(
            receiver_name="canopy_01",
            receiver_type="canopy",
            data_dir=tmp_path,
            yyyydoy=YYYYDOY.from_str("2025001"),
            site=site,
        )
    with pytest.raises(NotImplementedError) as e:
        processor.process()
    assert (
        "canvodpy.Site('Fangorn').pipeline().process_date('2025001')['canopy_01']"
        in str(e.value)
    )
