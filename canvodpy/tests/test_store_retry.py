"""Store retries: only errors that can be transient are retried."""

import icechunk
import pytest
import structlog
from canvodpy.orchestrator import store_retry


class _Failing:
    """Raises ``exc`` on the first ``n`` calls, then returns ``"ok"``."""

    def __init__(self, exc: Exception, n: int) -> None:
        self.exc, self.n, self.calls = exc, n, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.n:
            raise self.exc
        return "ok"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(store_retry._time, "sleep", lambda _s: None)


@pytest.mark.parametrize(
    "exc", [OSError("os error 103"), icechunk.IcechunkError("connection dropped")]
)
def test_transient_errors_are_retried(exc):
    fn = _Failing(exc, 2)
    log = structlog.get_logger()
    assert store_retry.call_with_store_retries(fn, logger=log) == "ok"
    assert fn.calls == 3


@pytest.mark.parametrize("exc", [ValueError("validation failed"), RuntimeError("x")])
def test_other_errors_propagate_at_once(exc):
    fn = _Failing(exc, 1)
    with pytest.raises(type(exc)):
        store_retry.call_with_store_retries(fn, logger=structlog.get_logger())
    assert fn.calls == 1


_CONFLICTS = [
    icechunk.ConflictError("parent snapshot"),
    icechunk.RebaseFailedError("snapshot", []),
]


@pytest.mark.parametrize("exc", _CONFLICTS)
def test_a_conflict_is_retried_once_without_waiting(exc, monkeypatch):
    # Another commit moved the branch. Each call opens a new session, so one
    # more try starts from the new commit; there is nothing to wait for.
    sleeps = []
    monkeypatch.setattr(store_retry._time, "sleep", sleeps.append)
    fn = _Failing(exc, 1)
    assert (
        store_retry.call_with_store_retries(fn, logger=structlog.get_logger()) == "ok"
    )
    assert fn.calls == 2
    assert sleeps == []


@pytest.mark.parametrize("exc", _CONFLICTS)
def test_a_second_conflict_propagates(exc):
    fn = _Failing(exc, 2)
    with pytest.raises(icechunk.ConflictError):
        store_retry.call_with_store_retries(fn, logger=structlog.get_logger())
    assert fn.calls == 2
