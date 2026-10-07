# Offline tests for logic_manager.
# Uses fake AI answers (no real API), so it runs anywhere, including Docker.
# Run with:  pytest

from copy import deepcopy

import logic_manager
import pytest


@pytest.mark.parametrize(
    "details",
    [
        {"emails": [], "phone_numbers": [], "ip_addresses": []},
        {"emails": ["demo123@example.test"], "phone_numbers": [], "ip_addresses": []},
        {"emails": [], "phone_numbers": ["12345678"], "ip_addresses": []},
        {"emails": [], "phone_numbers": [], "ip_addresses": ["2001:DB8::10", "192.0.2.10"]},
        {
            "emails": ["b2@example.test", "a1@example.test", "b2@example.test"],
            "phone_numbers": ["87654321", "12345678", "87654321"],
            "ip_addresses": ["2001:DB8::10", "192.0.2.10", "2001:DB8::10"],
        },
    ],
    ids=["empty", "email-only", "phone-only", "ip-only", "all-with-repeats"],
)
def test_hold_details(details):
    """Preserve the dictionary, lists, and values through the Logic Manager."""
    # Snapshot values and list references to detect mutation or replacement.
    original_values = deepcopy(details)
    original_lists = details.copy()

    returned = logic_manager.hold_details(details)

    # The handoff must preserve identity as well as order and repeated values.
    assert returned is details
    assert returned == original_values
    for key, original_list in original_lists.items():
        assert returned[key] is original_list
