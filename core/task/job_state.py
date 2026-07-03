"""Canonical lifecycle rules for background collect and send jobs."""

from enum import StrEnum


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    DONE = "done"
    FAILED = "failed"


TERMINAL_STATES = frozenset({JobState.CANCELLED, JobState.DONE, JobState.FAILED})

ALLOWED_TRANSITIONS = {
    JobState.PENDING: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {
        JobState.CANCELLING,
        JobState.CANCELLED,
        JobState.DONE,
        JobState.FAILED,
    },
    JobState.CANCELLING: {JobState.CANCELLED, JobState.FAILED},
    JobState.CANCELLED: set(),
    JobState.DONE: set(),
    JobState.FAILED: set(),
}


def transition(current: JobState | str, target: JobState | str) -> JobState:
    current_state = JobState(current)
    target_state = JobState(target)
    if target_state is current_state:
        return target_state
    if target_state not in ALLOWED_TRANSITIONS[current_state]:
        raise ValueError(f"illegal job transition: {current_state} -> {target_state}")
    return target_state
