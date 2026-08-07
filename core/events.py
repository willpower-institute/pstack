"""Event bus — in-process เสมอ + broadcast ข้ามโปรเซสผ่าน Redis pub/sub (optional)

ใช้งาน:
    from core.runtime import ctx

    @ctx.events.on("users.created")
    async def handle(payload): ...

    await ctx.events.emit("users.created", {"user_id": 1})                  # in-process
    await ctx.events.emit("users.created", {"user_id": 1}, broadcast=True)  # + Redis
                                                                            # (payload ต้องเป็น JSON ได้)

ถ้า Redis ไม่พร้อมตอนบูต ระบบยังทำงานต่อแบบ in-process (log warning ไว้)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]]

CHANNEL = "pstack:events"


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._redis: Any = None
        self._pubsub: Any = None
        self._listener_task: asyncio.Task | None = None
        self._origin = uuid.uuid4().hex  # กันรับ event ที่ตัวเอง broadcast ออกไป

    def on(self, event: str) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self._handlers[event].append(fn)
            return fn

        return decorator

    async def _dispatch(self, event: str, payload: Any) -> None:
        handlers = self._handlers.get(event, [])
        results = await asyncio.gather(
            *(h(payload) for h in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.exception(
                    "event handler %s failed for %s", handler.__qualname__, event,
                    exc_info=result,
                )

    async def emit(self, event: str, payload: Any = None, broadcast: bool = False) -> None:
        await self._dispatch(event, payload)
        if broadcast and self._redis is not None:
            message = json.dumps(
                {"origin": self._origin, "event": event, "payload": payload}
            )
            await self._redis.publish(CHANNEL, message)

    async def connect_redis(self, url: str) -> None:
        try:
            from redis import asyncio as aioredis

            self._redis = aioredis.from_url(url, decode_responses=True)
            await self._redis.ping()
        except Exception as e:
            logger.warning("Redis ไม่พร้อม (%s) — event bus ทำงานแบบ in-process เท่านั้น", e)
            self._redis = None
            return
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(CHANNEL)
        self._listener_task = asyncio.create_task(self._listen())
        logger.info("event bus: Redis broadcast enabled")

    async def _listen(self) -> None:
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                if data.get("origin") == self._origin:
                    continue
                await self._dispatch(data["event"], data.get("payload"))
            except Exception:
                logger.exception("bad event message from redis")

    async def close(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
