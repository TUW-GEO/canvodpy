"""Integration test to verify SID filtering works."""

import pytest


@pytest.mark.integration
def test_sid_filtering_integration(rosalia_one_day):
    """Test SID filtering with full orchestrator."""
    _config, counter = rosalia_one_day
    assert counter == 1, "Should have processed exactly one date"
