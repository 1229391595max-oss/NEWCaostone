"""Closed action-card state machine.

Exports and outcome reviews append independent records and never imply that an
approved recommendation was executed or completed.
"""

from __future__ import annotations

from typing import Literal

ActionStatus = Literal["new", "reviewed", "approved", "dismissed"]
ActionCommand = Literal[
    "review",
    "adjust",
    "approve",
    "dismiss",
    "export",
    "record_outcome",
]

TRANSITIONS: dict[ActionStatus, dict[ActionCommand, ActionStatus]] = {
    "new": {"review": "reviewed"},
    "reviewed": {
        "adjust": "reviewed",
        "approve": "approved",
        "dismiss": "dismissed",
    },
    "approved": {
        "export": "approved",
        "record_outcome": "approved",
    },
    "dismissed": {},
}


class ActionTransitionInvalid(RuntimeError):
    code = "ACTION_TRANSITION_INVALID"


def can_apply(status: str, command: str) -> bool:
    if status not in TRANSITIONS:
        return False
    return command in TRANSITIONS[status]  # type: ignore[operator]


def apply_command(status: str, command: str) -> ActionStatus:
    if not can_apply(status, command):
        raise ActionTransitionInvalid(f"{status}:{command}")
    return TRANSITIONS[status][command]  # type: ignore[index]
