"""ARQ worker entrypoint — รันด้วย: arq core.worker.WorkerSettings

โหลดโมดูลทั้งหมดก่อน (jobs ลงทะเบียนตอน import) แล้วค่อยสร้าง WorkerSettings
"""

from core.app import create_app
from core.jobs import build_worker_settings

create_app()
WorkerSettings = build_worker_settings()
