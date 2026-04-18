from __future__ import annotations

from readmypaper.job_store import JobStore
from readmypaper.types import JobStatus


def test_create_with_capacity_check_creates_when_under_limit() -> None:
    store = JobStore()

    job = store.create_with_capacity_check("paper.pdf", max_pending_jobs=1)

    assert job is not None
    assert job.filename == "paper.pdf"
    assert store.count_active_jobs() == 1


def test_create_with_capacity_check_rejects_when_at_limit() -> None:
    store = JobStore()
    store.create("existing.pdf")

    job = store.create_with_capacity_check("paper.pdf", max_pending_jobs=1)

    assert job is None
    assert len(list(store.list())) == 1


def test_count_active_jobs_ignores_completed_and_failed_jobs() -> None:
    store = JobStore()
    store.create("pending.pdf")
    running = store.create("running.pdf")
    completed = store.create("completed.pdf")
    failed = store.create("failed.pdf")

    store.update(running.job_id, status=JobStatus.RUNNING)
    store.update(completed.job_id, status=JobStatus.COMPLETED)
    store.update(failed.job_id, status=JobStatus.FAILED)

    assert store.count_active_jobs() == 2


def test_delete_removes_existing_job() -> None:
    store = JobStore()
    job = store.create("paper.pdf")

    deleted = store.delete(job.job_id)

    assert deleted is True
    assert store.get(job.job_id) is None


def test_delete_returns_false_for_missing_job() -> None:
    store = JobStore()

    deleted = store.delete("missing-job")

    assert deleted is False
