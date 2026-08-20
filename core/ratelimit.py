"""Rate limiter แบบ fixed window — ใช้ Redis ถ้ามี ไม่มีก็ตกมาใช้ in-process

    from core.ratelimit import check_rate_limit

    await check_rate_limit(f"login:ip:{ip}", limit=20, window_seconds=60)

เกินโควตา -> raise RateLimited (มี retry_after) ให้ชั้น route แปลงเป็น HTTP 429

ทำไมเป็น fixed window: นับด้วย INCR + EXPIRE ครั้งเดียวต่อ request ไม่ต้องใช้ Lua
ไม่ต้องเก็บ timestamp ทุกครั้ง — ยอมให้เกินโควตาได้เล็กน้อยตรงรอยต่อหน้าต่าง
ซึ่งรับได้สำหรับงานกันเดารหัสผ่าน

⚠️ fallback แบบ in-process นับแยกกันต่อ worker — ถ้ารันหลาย worker/หลาย replica
โดยไม่มี Redis โควตาจริงจะเท่ากับ limit × จำนวน worker (log warning ไว้ให้แล้ว)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from core.config import get_settings

logger = logging.getLogger(__name__)

_redis = None
_redis_ready: bool | None = None  # None = ยังไม่ได้ลองต่อ
_warned_fallback = False


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"เกินโควตา ลองใหม่ใน {retry_after} วินาที")
        self.retry_after = retry_after


@dataclass
class _MemoryWindow:
    counts: dict[str, tuple[int, float]] = field(default_factory=dict)

    def hit(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        count, expires = self.counts.get(key, (0, 0.0))
        if expires <= now:
            count, expires = 0, now + window_seconds
        count += 1
        self.counts[key] = (count, expires)
        if len(self.counts) > 10_000:  # กันโตไม่จำกัดเมื่อโดนยิงด้วย key สุ่ม
            self.counts = {
                k: v for k, v in self.counts.items() if v[1] > now
            }
        return count

    def peek(self, key: str) -> int:
        count, expires = self.counts.get(key, (0, 0.0))
        return count if expires > time.monotonic() else 0


_memory = _MemoryWindow()


async def _get_redis():
    global _redis, _redis_ready
    if _redis_ready is not None:
        return _redis
    try:
        from redis import asyncio as aioredis

        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await client.ping()
        _redis, _redis_ready = client, True
    except Exception as e:
        logger.warning("rate limit: Redis ไม่พร้อม (%s) — นับแบบ in-process แทน", e)
        _redis, _redis_ready = None, False
    return _redis


async def check_rate_limit(
    key: str, limit: int, window_seconds: int, *, increment: bool = True
) -> None:
    """raise RateLimited ถ้าเกินโควตาในหน้าต่างนี้

    increment=False = แค่ดูว่าโควตาถูกใช้หมดแล้วหรือยัง ไม่นับเพิ่ม
    (ใช้เช็คก่อนทำงานหนัก เช่นก่อนเรียก bcrypt ซึ่งกิน CPU ~300ms ต่อครั้ง)

    เกณฑ์ต่างกันเล็กน้อยตามความหมาย: increment=True นับรวมครั้งปัจจุบันแล้ว
    จึงเกินเมื่อ count > limit · increment=False ยังไม่รวมครั้งปัจจุบัน
    จึงเต็มโควตาตั้งแต่ count >= limit
    """
    global _warned_fallback
    if limit <= 0:  # ตั้ง 0 = ปิดการจำกัด
        return

    client = await _get_redis()
    if client is not None:
        redis_key = f"pstack:rl:{key}"
        if increment:
            count = await client.incr(redis_key)
            if count == 1:
                await client.expire(redis_key, window_seconds)
        else:
            count = int(await client.get(redis_key) or 0)
        if count > limit or (not increment and count >= limit):
            ttl = await client.ttl(redis_key)
            raise RateLimited(retry_after=max(ttl, 1))
        return

    if not _warned_fallback:
        _warned_fallback = True
        logger.warning(
            "rate limit ทำงานแบบ in-process — หลาย worker จะนับแยกกัน "
            "(โควตาจริง = limit × จำนวน worker)"
        )
    count = _memory.hit(key, window_seconds) if increment else _memory.peek(key)
    if count > limit or (not increment and count >= limit):
        raise RateLimited(retry_after=window_seconds)


async def reset() -> None:
    """ล้างสถานะ — สำหรับเทสเท่านั้น"""
    global _redis, _redis_ready, _warned_fallback
    _memory.counts.clear()
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            logger.debug("ปิด redis client ไม่สำเร็จ", exc_info=True)
    _redis, _redis_ready, _warned_fallback = None, None, False
