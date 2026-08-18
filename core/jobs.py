"""Background jobs (ARQ) — โมดูลลงทะเบียน job ใน addons/<name>/jobs.py

แบบ "สั่งแล้วรัน":

    from core.jobs import background_job, enqueue

    @background_job
    async def send_report(ctx, user_id: int) -> None:  # ctx คือ arq context เสมอ
        ...

    await enqueue("send_report", user_id=1)   # จากที่ไหนก็ได้ในระบบ

แบบ "ทำงานเองเป็นระยะ" (periodic/cron — worker เดินลูปเอง):

    from core.jobs import periodic_job

    @periodic_job(minute=set(range(0, 60)))   # ทุกนาที (kwargs ส่งตรงให้ arq.cron)
    async def care_tick(ctx) -> None:
        ...

    ⏰ cron ตีความด้วย "เวลา UTC ของ container" — คำนวณ due time เป็น UTC ไว้ก่อนเสมอ
    (ทั้ง framework ยึด UTC — datetime.now(UTC))

Worker แยกโปรเซส: `arq core.worker.WorkerSettings` (มี service ใน docker-compose แล้ว)
รัน worker หลาย replica ได้ — arq ทำ job coalescing ผ่าน Redis ให้ cron ยิงครั้งเดียว
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from core.config import get_settings

logger = logging.getLogger(__name__)

_jobs: dict[str, Callable[..., Awaitable[Any]]] = {}
# job ที่ทำงานเองเป็นระยะ: (fn, cron_kwargs ที่ส่งให้ arq.cron)
_periodic: list[tuple[Callable[..., Awaitable[Any]], dict]] = []
_pool: Any = None


def background_job(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    if fn.__name__ in _jobs:
        raise ValueError(f"background job ชื่อซ้ำ: {fn.__name__}")
    _jobs[fn.__name__] = fn
    return fn


def periodic_job(**cron_kwargs: Any):
    """ลงทะเบียน job ที่ worker เรียกเองเป็นระยะ (issue #2)

    cron_kwargs ส่งตรงให้ arq.cron: minute / hour / day / weekday / month / second /
    run_at_startup / unique / timeout ฯลฯ เช่น:
        @periodic_job(minute=set(range(0, 60)))   # ทุกนาที
        @periodic_job(hour={9}, minute={0})       # ทุกวัน 09:00 UTC
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        _periodic.append((fn, cron_kwargs))
        return fn

    return decorator


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
    from arq import cron
    from arq.connections import RedisSettings

    cron_list = [cron(fn, **spec) for fn, spec in _periodic]

    class WorkerSettings:
        functions = list(_jobs.values())
        cron_jobs = cron_list
        redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

    logger.info(
        "worker jobs: %s | periodic: %s",
        ", ".join(_jobs) or "(none)",
        ", ".join(fn.__name__ for fn, _ in _periodic) or "(none)",
    )
    return WorkerSettings
