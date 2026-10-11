"""Every data variable a reader writes says what it holds (ACDD 1.3, #208)."""

import pytest

from canvod.readers.gnss_specs import metadata
from canvod.readers.sbf import reader as sbf_reader

# ACDD 1.3 values of coverage_content_type.
_COVERAGE_CONTENT_TYPES = {
    "image",
    "thematicClassification",
    "physicalMeasurement",
    "auxiliaryInformation",
    "qualityInformation",
    "referenceInformation",
    "modelResult",
    "coordinate",
}

_ATTRIBUTES = {
    **{f"observables.{k}": v for k, v in metadata.OBSERVABLES_METADATA.items()},
    "SNR": metadata.SNR_METADATA,
    "CN0": metadata.CN0_METADATA,
    **{
        f"sbf.{name}": value
        for name, value in vars(sbf_reader).items()
        if name.endswith("_ATTRS") and isinstance(value, dict)
    },
}


@pytest.mark.parametrize("name", sorted(_ATTRIBUTES))
def test_a_variable_has_a_coverage_content_type(name):
    assert _ATTRIBUTES[name]["coverage_content_type"] in _COVERAGE_CONTENT_TYPES


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Pseudorange", "physicalMeasurement"),
        ("Phase", "physicalMeasurement"),
        ("Doppler", "physicalMeasurement"),
        ("LLI", "qualityInformation"),
        ("SSI", "qualityInformation"),
    ],
)
def test_observables_and_their_indicators(name, kind):
    assert metadata.OBSERVABLES_METADATA[name]["coverage_content_type"] == kind


def test_signal_strength_is_a_measurement():
    assert metadata.SNR_METADATA["coverage_content_type"] == "physicalMeasurement"
    assert metadata.CN0_METADATA["coverage_content_type"] == "physicalMeasurement"


@pytest.mark.parametrize("name", ["Pseudorange", "Doppler"])
def test_valid_min_of_a_float_variable_is_a_float(name):
    # CF: valid_min has the type of the variable.
    assert isinstance(metadata.OBSERVABLES_METADATA[name]["valid_min"], float)
    assert isinstance(metadata.SNR_METADATA["valid_min"], float)
