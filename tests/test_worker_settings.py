"""WorkerSettings ต้องประกาศครบทั้ง job และ hook ต่อ event bus

worker เป็นโปรเซสแยกที่ไม่ได้รัน FastAPI lifespan — ถ้าไม่ต่อ Redis เอง
handler ที่ประกาศด้วย @ctx.events.on ในโปรเซสนี้จะไม่ได้รับ event ที่ broadcast มา
โดยไม่มี error ให้จับเลย เทสนี้กันไม่ให้ hook หายไปเงียบ ๆ
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _kwargs() -> dict:
    """อ่านค่าด้วยกลไกเดียวกับที่ arq ใช้จริงตอน create_worker()"""
    from arq.worker import get_kwargs

    from core.worker import WorkerSettings

    return get_kwargs(WorkerSettings)


def test_arq_sees_worker_attributes():
    """กันเคส subclass — arq อ่านจาก __dict__ เท่านั้น attribute ที่สืบทอดมาจะหายไปหมด
    แล้วพังตอนบูตด้วย 'at least one function or cron_job must be registered'

    (เทสความ 'มีอยู่' ของ attribute ไม่ใช่จำนวน job — จำนวนขึ้นกับ PSTACK_MODULES)"""
    kwargs = _kwargs()
    for key in ("functions", "cron_jobs", "redis_settings"):
        assert key in kwargs, f"arq มองไม่เห็น {key} — WorkerSettings ถูก subclass อยู่หรือเปล่า"


def test_worker_connects_event_bus_on_startup():
    """ไม่มี hook นี้ = event ที่ broadcast=True ไปไม่ถึง worker (README เคลมว่าถึง)"""
    kwargs = _kwargs()
    assert "on_startup" in kwargs, "worker ไม่ได้ต่อ Redis ให้ event bus ตอน startup"
    assert "on_shutdown" in kwargs, "worker ไม่ได้ปิด event bus ตอน shutdown"
