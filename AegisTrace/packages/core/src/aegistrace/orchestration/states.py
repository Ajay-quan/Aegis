# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Workflow state machine. The transition table is the single authority on
legal moves; persistence enforces it inside the same transaction that appends
the corresponding event."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RECOVERING = "RECOVERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


S = RunState
TERMINAL = frozenset({S.SUCCEEDED, S.FAILED, S.CANCELLED, S.TIMED_OUT})

# NEEDS_RECONCILIATION is deliberately not terminal and cannot reach SUCCEEDED
# automatically: only an operator reconciliation decides the outcome.
TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    S.CREATED: frozenset({S.VALIDATING, S.CANCELLED}),
    S.VALIDATING: frozenset({S.QUEUED, S.FAILED, S.CANCELLED}),
    S.QUEUED: frozenset({S.RUNNING, S.CANCELLED, S.TIMED_OUT}),
    S.RUNNING: frozenset(
        {
            S.WAITING_FOR_APPROVAL,
            S.RETRY_SCHEDULED,
            S.RECOVERING,
            S.SUCCEEDED,
            S.FAILED,
            S.CANCELLED,
            S.TIMED_OUT,
            S.NEEDS_RECONCILIATION,
        }
    ),
    S.WAITING_FOR_APPROVAL: frozenset({S.QUEUED, S.FAILED, S.CANCELLED, S.TIMED_OUT}),
    S.RETRY_SCHEDULED: frozenset({S.QUEUED, S.FAILED, S.CANCELLED}),
    S.RECOVERING: frozenset({S.QUEUED, S.RETRY_SCHEDULED, S.FAILED, S.NEEDS_RECONCILIATION, S.CANCELLED}),
    S.NEEDS_RECONCILIATION: frozenset({S.SUCCEEDED, S.FAILED, S.QUEUED, S.CANCELLED}),
    S.SUCCEEDED: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
    S.TIMED_OUT: frozenset(),
}

# Transitions out of NEEDS_RECONCILIATION require a human operator.
OPERATOR_ONLY: frozenset[tuple[RunState, RunState]] = frozenset(
    (S.NEEDS_RECONCILIATION, t) for t in TRANSITIONS[S.NEEDS_RECONCILIATION]
)


class IllegalTransition(Exception):
    def __init__(self, current: RunState, target: RunState) -> None:
        super().__init__(f"illegal transition {current} -> {target}")
        self.current = current
        self.target = target


def check_transition(current: RunState, target: RunState) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(current, target)
