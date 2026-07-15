"""Report generation job (P5): drain queued research runs via the transactional
lease and run each through the LangGraph research graph (design §4.6, §6.1).

Deployed with **--max-retries=1** (unlike the posting jobs): this job produces a
draft only, and the lease + checkpointed resume guarantee that a task retry
re-acquires the same run and continues from its last completed superstep rather
than double-executing (design §6.3). `worker_id` is CLOUD_RUN_EXECUTION, stable
across task retries.
"""

import os

from app.repo import research as repo
from app.research.graph import runner
from app.research.schemas import ResearchRunStatus
from app.utils import observability
from app.utils.logging import get_logger

log = get_logger(__name__)

MAX_RUNS_PER_EXECUTION = 5  # drain a few queued runs; the scheduler re-triggers


def main() -> None:
    worker_id = os.environ.get("CLOUD_RUN_EXECUTION", "local")
    processed = 0
    try:
        for _ in range(MAX_RUNS_PER_EXECUTION):
            run = repo.claim_next(worker_id)
            if run is None:
                break
            processed += 1
            log.info("claimed research run", extra={"fields": {"run": run.id, "worker": worker_id}})
            try:
                runner.run_research(run)
            except Exception as exc:  # noqa: BLE001 — one run's failure must not abort the job
                log.error("research run failed", extra={"fields": {"run": run.id, "error": str(exc)}})
                repo.set_status(run.id, ResearchRunStatus.failed.value, error=str(exc)[:1000])
    finally:
        # The task can be reclaimed as soon as main() returns; drain queued traces first.
        observability.flush_langsmith()
    log.info("generate_report finished", extra={"fields": {"processed": processed}})


if __name__ == "__main__":
    main()
