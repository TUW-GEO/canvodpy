"""Optional receiver and antenna details of a receiver (#207)."""

import pytest
from pydantic import ValidationError

from canvod.config.models import ReceiverConfig


def test_a_receiver_without_details_still_loads():
    receiver = ReceiverConfig(type="canopy", directory="c")

    assert receiver.receiver_hardware is None
    assert receiver.antenna is None


def test_receiver_and_antenna_details_are_read():
    receiver = ReceiverConfig.model_validate(
        {
            "type": "canopy",
            "directory": "c",
            "receiver_hardware": {
                "manufacturer": "Septentrio",
                "model": "PolaRx5",
                "serial_number": "3013312",
                "firmware": "5.5.0",
            },
            "antenna": {
                "model": "SEPCHOKE_B3E6",
                "radome": "NONE",
                "height_m": 1.5,
                "choke_ring": True,
                "polarization": "dual-pol",
            },
        }
    )

    assert receiver.receiver_hardware.model == "PolaRx5"
    assert receiver.antenna.height_m == 1.5
    assert receiver.antenna.manufacturer is None
    assert receiver.antenna.choke_ring is True
    assert receiver.antenna.polarization == "dual-pol"


def test_an_unknown_polarization_is_refused():
    with pytest.raises(ValidationError, match="polarization"):
        ReceiverConfig.model_validate(
            {"type": "canopy", "directory": "c", "antenna": {"polarization": "linear"}}
        )


def test_an_unknown_detail_is_refused():
    with pytest.raises(ValidationError, match="serial"):
        ReceiverConfig.model_validate(
            {"type": "canopy", "directory": "c", "antenna": {"serial": "5112"}}
        )
