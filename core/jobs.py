"""Background jobs (ARQ) — โมดูลลงทะเบียน job ใน addons/<name>/jobs.py

    from core.jobs import background_job

    @background_job
    async def send_report(ctx, user_id: int) -> None:  # ctx คือ arq context เสมอ
        ...

    # จากที่ไหนก็ได้ในระบบ
    from core.jobs import enqueue
    await enqueue("send_report", user_id=1)

Worker แยกโปรเซส: `arq core.worker.WorkerSettings` (มี service ใน docker-compose แล้ว)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from core.config import get_settings

logger = logging.getLogger(__name__)

_jobs: dict[str, Callable[..., Awaitable[Any]]] = {}
_pool: Any = None


def background_job(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    if fn.__name__ in _jobs:
        raise ValueError(f"background job ชื่อซ้ำ: {fn.__name__}")
    _jobs[fn.__name__] = fn
    return fn


async def enqueue(job_name: str, *args: Any, **kwargs: Any) -> Any:
    if job_name not in _jobs:
        raise KeyError(f"ไม่พบ job '{job_name}' — ต้องลงทะเบียนด้วย @background_job ก่อน")
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return await _pool.enqueue_job(job_name, *args, **kwargs)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def build_worker_settings() -> type:
    """สร้าง WorkerSettings จาก registry — เรียกหลังโหลดโมดูลครบแล้วเท่านั้น"""
    from arq.connections import RedisSettings

    class WorkerSettings:
        functions = list(_jobs.values())
        redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

    logger.info("worker jobs: %s", ", ".join(_jobs) or "(none)")
    return WorkerSettings
