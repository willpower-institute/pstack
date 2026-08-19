"""นาฬิกาของ kernel — ทุกโมดูลควรเรียกผ่านที่นี่ ไม่เรียก datetime.now() ตรง

เหตุผล: scenario test ต้องเลื่อนเวลาไปข้างหน้าเพื่อทดสอบ retry / missed / escalation /
consent หมดอายุ — ถ้าโค้ดเรียก datetime.now() เอง จะเทสวงจร closed-loop ไม่ได้เลย

ทั้ง framework ยึด **UTC** (aware datetime เสมอ) — set_now ปฏิเสธ naive datetime

    from core.clock import now, FakeClock

    with FakeClock("2026-08-19T07:00:00+07:00") as clk:
        ...
        clk.advance(minutes=45)

หมายเหตุ: override เป็น process-global (ตั้งใจให้ใช้ในเทสเท่านั้น) — โค้ด production
เรียกแค่ `now()` ซึ่ง fallback เป็น datetime.now(UTC) ปกติ
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self

_override: datetime | None = None


def now() -> datetime:
    """เวลาปัจจุบันแบบ UTC-aware — หรือค่าที่ FakeClock ตั้งไว้ (ในเทส)"""
    return _override if _override is not None else datetime.now(UTC)


def set_now(value: datetime | str | None) -> None:
    """ตั้ง/ล้าง override — None = กลับไปใช้เวลาจริง"""
    global _override
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value is not None and value.tzinfo is None:
        raise ValueError("เวลาที่ตั้งต้องมี timezone — naive datetime ทำให้ routine เพี้ยนข้ามโซน")
    _override = value


class FakeClock:
    """ใช้ในเทสเท่านั้น — ตรึงเวลาไว้ที่ start แล้ว advance ทีละช่วง"""

    def __init__(self, start: datetime | str) -> None:
        self.start = datetime.fromisoformat(start) if isinstance(start, str) else start

    def __enter__(self) -> Self:
        set_now(self.start)
        return self

    def __exit__(self, *exc: object) -> None:
        set_now(None)

    def advance(self, **kwargs: float) -> datetime:
        current = now() + timedelta(**kwargs)
        set_now(current)
        return current

    def set(self, value: datetime | str) -> datetime:
        set_now(value)
        return now()
