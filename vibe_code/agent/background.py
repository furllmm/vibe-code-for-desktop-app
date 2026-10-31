"""Thread-based background execution with deduplication, cancellation and progress."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .autonomy import RunCheckpoint


class DuplicateTaskError(RuntimeError):
    pass


@dataclass
class BackgroundJob:
    key: str
    label: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    status: str = "queued"
    progress: RunCheckpoint | None = None
    error: str = ""
    thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self.status in {"queued", "running"}


class BackgroundTaskManager:
    """Run long agent jobs off the UI thread. State is read by polling ``jobs()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, BackgroundJob] = {}

    def submit(
        self,
        key: str,
        label: str,
        work: Callable[[threading.Event, Callable[[RunCheckpoint], None]], RunCheckpoint],
    ) -> BackgroundJob:
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.active:
                raise DuplicateTaskError(f"'{label}' is already running")
            job = BackgroundJob(key, label)
            self._jobs[key] = job

        def progress(checkpoint: RunCheckpoint) -> None:
            with self._lock:
                job.progress = checkpoint

        def target() -> None:
            with self._lock:
                job.status = "running"
            try:
                result = work(job.cancel_event, progress)
            except Exception as exc:  # surfaced in the UI; never re-raised in a worker thread
                with self._lock:
                    job.status = "error"
                    job.error = str(exc) or exc.__class__.__name__
                return
            with self._lock:
                job.progress = result
                job.status = result.status

        job.thread = threading.Thread(target=target, name=f"vibe-job-{key}", daemon=True)
        job.thread.start()
        return job

    def cancel(self, key: str) -> bool:
        with self._lock:
            job = self._jobs.get(key)
        if job is None or not job.active:
            return False
        job.cancel_event.set()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()

    def jobs(self) -> list[BackgroundJob]:
        with self._lock:
            return list(self._jobs.values())

    def get(self, key: str) -> BackgroundJob | None:
        with self._lock:
            return self._jobs.get(key)

    def wait(self, key: str, timeout: float | None = None) -> bool:
        job = self.get(key)
        if job is None or job.thread is None:
            return True
        job.thread.join(timeout)
        return not job.thread.is_alive()
