"""Job lifecycle invariants shared by API and background workers."""

import pytest

from core.task.job_state import JobState, transition
from server import workers


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobState.PENDING, JobState.RUNNING),
        (JobState.RUNNING, JobState.CANCELLING),
        (JobState.CANCELLING, JobState.CANCELLED),
        (JobState.RUNNING, JobState.DONE),
        (JobState.RUNNING, JobState.FAILED),
    ],
)
def test_valid_job_transitions(current, target):
    assert transition(current, target) is target


def test_same_state_update_is_allowed_for_heartbeats():
    assert transition(JobState.RUNNING, JobState.RUNNING) is JobState.RUNNING


@pytest.mark.parametrize("terminal", [JobState.CANCELLED, JobState.DONE, JobState.FAILED])
def test_terminal_job_cannot_change_state(terminal):
    with pytest.raises(ValueError, match="illegal job transition"):
        transition(terminal, JobState.RUNNING)


def test_cancelled_job_cannot_finish_as_done():
    with pytest.raises(ValueError, match="illegal job transition"):
        transition(JobState.CANCELLED, JobState.DONE)


def test_late_worker_completion_cannot_overwrite_cancelled(monkeypatch):
    monkeypatch.setattr(workers, "_persist_job", lambda *_args, **_kwargs: None)
    with workers._jobs_lock:
        workers._jobs.pop("job-late-completion", None)

    workers._set_job("job-late-completion", status="running")
    workers._set_job("job-late-completion", status="cancelling")
    workers._set_job("job-late-completion", status="cancelled")

    with pytest.raises(ValueError, match="illegal job transition"):
        workers._set_job("job-late-completion", status="done")

    with workers._jobs_lock:
        assert workers._jobs["job-late-completion"]["status"] == "cancelled"
        workers._jobs.pop("job-late-completion", None)
