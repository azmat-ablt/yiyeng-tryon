import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from .inference.base import TryOnProvider
from .schemas import utcnow
from .storage import LocalStorage
from .store import Asset

JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Job:
    id: str
    status: JobStatus = "queued"
    result_url: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)


class JobManager:
    """进程内任务队列。任务量大时替换为 Redis + Celery/ARQ，接口保持不变。"""

    def __init__(self, storage: LocalStorage, provider: TryOnProvider) -> None:
        self._storage = storage
        self._provider = provider
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def create(self, person: Asset, garment: Asset, cloth_type: str = "upper") -> Job:
        job = Job(id=uuid.uuid4().hex)
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, person.path, garment.path, cloth_type))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def _run(self, job: Job, person_path: Path, garment_path: Path, cloth_type: str) -> None:
        job.status = "running"
        try:
            output = await self._provider.generate(person_path, garment_path, cloth_type)
            job.result_url = self._storage.save_result(job.id, output.data, output.media_type)
            job.status = "succeeded"
        except Exception as exc:
            job.error = str(exc) or exc.__class__.__name__
            job.status = "failed"
