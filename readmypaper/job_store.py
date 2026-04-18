from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from .types import JobResult, JobState, JobStatus


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def create(self, filename: str) -> JobState:
        with self._lock:
            return self._create_locked(filename)

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def restore(self, job: JobState) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def restore_if_absent(self, job: JobState) -> bool:
        with self._lock:
            if job.job_id in self._jobs:
                return False
            self._jobs[job.job_id] = job
            return True

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        step: str | None = None,
        progress: float | None = None,
        error: str | None = None,
        engine_used: str | None = None,
        result: JobResult | None = None,
    ) -> JobState:
        with self._lock:
            state = self._jobs[job_id]
            if status is not None:
                state.status = status
            if step is not None:
                state.step = step
            if progress is not None:
                state.progress = max(0.0, min(1.0, progress))
            if error is not None:
                state.error = error
            if engine_used is not None:
                state.engine_used = engine_used
            if result is not None:
                state.result = result
            state.updated_at = datetime.now(timezone.utc)
            return state

    def list(self) -> Iterable[JobState]:
        with self._lock:
            return list(self._jobs.values())

    def count_active_jobs(self) -> int:
        with self._lock:
            return self._count_active_jobs_locked()

    def create_with_capacity_check(self, filename: str, max_pending_jobs: int) -> JobState | None:
        with self._lock:
            if self._count_active_jobs_locked() >= max_pending_jobs:
                return None
            return self._create_locked(filename)

    def _create_locked(self, filename: str) -> JobState:
        job_id = uuid4().hex
        state = JobState(job_id=job_id, filename=filename)
        self._jobs[job_id] = state
        return state

    def _count_active_jobs_locked(self) -> int:
        return sum(
            1 for job in self._jobs.values() if job.status in {JobStatus.PENDING, JobStatus.RUNNING}
        )
