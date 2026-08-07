"""Event bus แบบ in-process — โมดูลคุยกันผ่าน event แทนการ import ตรง

ใช้งาน:
    from core.runtime import ctx

    @ctx.events.on("users.created")
    async def handle(payload): ...

    await ctx.events.emit("users.created", {"user_id": 1})

(Phase 2: เพิ่ม Redis pub/sub สำหรับข้าม process)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event: str) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self._handlers[event].append(fn)
            return fn

        return decorator

    async def emit(self, event: str, payload: Any = None) -> None:
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
