"""Single-worker in-process calibration queue for the local app."""
from __future__ import annotations
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
import uuid

EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tumor-fit")
JOBS: dict[str, dict[str, Any]] = {}


class JobCancelled(Exception):
    pass


def submit(task, *args, **kwargs) -> str:
    """Queue `task(job_id, *args, **kwargs)` on the single worker thread.

    The job_id is injected as the first argument so the task can report its
    own progress with `update(job_id, ...)` as it works through each
    (law, start) pair.
    """
    job_id = f"j_{uuid.uuid4().hex[:10]}"
    JOBS[job_id] = {"job_id": job_id, "status": "queued", "step": 0, "n_steps": 1, "stage": "queued", "result_id": None, "cancel_requested": False, "created_at": datetime.now(timezone.utc).isoformat(), "future": None}
    future = EXECUTOR.submit(_run, job_id, task, args, kwargs)
    JOBS[job_id]["future"] = future
    return job_id


def _run(job_id, task, args, kwargs):
    JOBS[job_id].update(status="running", stage="starting")
    try:
        result = task(job_id, *args, **kwargs)
        JOBS[job_id].update(status="done", step=JOBS[job_id]["n_steps"], stage="done", result=result, result_id=job_id)
    except JobCancelled:
        JOBS[job_id].update(status="cancelled", stage="cancelled", error="Job cancelled")
    except Exception as exc:
        JOBS[job_id].update(status="error", stage=str(exc), error=str(exc))


def update(job_id: str, **fields) -> None:
    """Let a running task report its own progress (stage text, step, n_steps)."""
    job = JOBS.get(job_id)
    if job is not None:
        job.update(fields)


def cancel(job_id: str) -> bool:
    job = JOBS.get(job_id)
    if not job or job.get("status") in {"done", "error", "cancelled"}:
        return False
    job["cancel_requested"] = True
    return True


def is_cancelled(job_id: str) -> bool:
    return bool(JOBS.get(job_id, {}).get("cancel_requested"))


def get(job_id: str):
    job = JOBS.get(job_id)
    if not job: return None
    return {key: value for key, value in job.items() if key not in {"future", "result"}}


def result(job_id: str):
    return JOBS.get(job_id, {}).get("result")
