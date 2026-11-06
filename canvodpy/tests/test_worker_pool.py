"""A run has one worker pool, whichever thread asks for it (#433).

loky keeps its reusable executor per thread. A run asks for its pool from
the main thread (VOD), the thread that reads the units and the threads
that prepare the days; each would get a pool of its own, with as many
workers as the memory budget planned for the whole run.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from canvodpy.orchestrator.pipeline import PipelineOrchestrator


def _orchestrator(workers: int) -> PipelineOrchestrator:
    pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
    pipe._workers = workers
    pipe.n_max_workers = workers
    resources = {"nice_priority": 0, "cpu_affinity": None}
    pipe._config = SimpleNamespace(
        processing=SimpleNamespace(
            params=SimpleNamespace(resolve_resources=lambda: resources)
        )
    )
    return pipe


def _pool_in_a_thread(pipe: PipelineOrchestrator):
    pools = []
    thread = threading.Thread(target=lambda: pools.append(pipe.worker_pool()))
    thread.start()
    thread.join()
    return pools[0]


def test_every_thread_of_a_run_gets_the_same_pool() -> None:
    pipe = _orchestrator(workers=1)

    here = pipe.worker_pool()

    assert _pool_in_a_thread(pipe) is here
    assert _pool_in_a_thread(pipe) is here
    assert here.submit(sum, [1, 2]).result() == 3


def test_a_broken_pool_is_replaced() -> None:
    pipe = _orchestrator(workers=1)
    broken = pipe.worker_pool()
    broken.shutdown(wait=True)

    pool = _pool_in_a_thread(pipe)

    assert pool is not broken
    assert pool.submit(sum, [1, 2]).result() == 3
    assert pipe.worker_pool() is pool


def test_a_run_sized_again_gets_a_pool_of_the_new_size() -> None:
    pipe = _orchestrator(workers=1)
    first = pipe.worker_pool()

    pipe._workers = 2  # the memory plan of the next run

    pool = _pool_in_a_thread(pipe)
    assert pool is not first
    assert pool._max_workers == 2
    assert pipe.worker_pool() is pool
