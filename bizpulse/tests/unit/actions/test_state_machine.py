from __future__ import annotations

import pytest

from src.actions.state_machine import ActionTransitionInvalid, apply_command, can_apply


@pytest.mark.parametrize(
    ("start", "command", "allowed"),
    [
        ("new", "approve", False),
        ("new", "review", True),
        ("new", "adjust", False),
        ("reviewed", "adjust", True),
        ("reviewed", "approve", True),
        ("reviewed", "dismiss", True),
        ("approved", "export", True),
        ("approved", "record_outcome", True),
        ("approved", "dismiss", False),
        ("dismissed", "review", False),
    ],
)
def test_action_transition_matrix(start: str, command: str, allowed: bool) -> None:
    assert can_apply(start, command) is allowed


def test_independent_records_do_not_change_approved_state() -> None:
    assert apply_command("approved", "export") == "approved"
    assert apply_command("approved", "record_outcome") == "approved"


def test_invalid_transition_fails_closed() -> None:
    with pytest.raises(ActionTransitionInvalid):
        apply_command("new", "approve")
