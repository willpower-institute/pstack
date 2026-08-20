"""ARQ worker entrypoint — รันด้วย: arq core.worker.WorkerSettings

โหลดโมดูลทั้งหมดก่อน (jobs ลงทะเบียนตอน import) แล้วค่อยสร้าง WorkerSettings

worker ไม่ได้รัน FastAPI lifespan จึงต้องต่อ Redis ให้ event bus เองผ่าน hook ของ arq
ไม่งั้น handler ที่ประกาศด้วย @ctx.events.on ในโปรเซสนี้จะไม่ได้รับ event ที่
broadcast=True ส่งมาเลย (เงียบ ไม่มี error)

⚠️ ห้าม subclass WorkerSettings — arq อ่านค่าจาก `settings_cls.__dict__` ตรง ๆ
   attribute ที่สืบทอดมาจากคลาสแม่ (functions, cron_jobs, redis_settings) จะหายไป
   แล้วได้ "RuntimeError: at least one function or cron_job must be registered"
   ต้องแปะ hook ลงบนคลาสที่ build_worker_settings() คืนมาโดยตรง
"""

from core.app import create_app
from core.config import get_settings
from core.jobs import build_worker_settings
from core.runtime import ctx

create_app()

WorkerSettings = build_worker_settings()


async def _on_startup(_arq_ctx) -> None:
    await ctx.events.connect_redis(get_settings().redis_url)


async def _on_shutdown(_arq_ctx) -> None:
    await ctx.events.close()


WorkerSettings.on_startup = staticmethod(_on_startup)
WorkerSettings.on_shutdown = staticmethod(_on_shutdown)
