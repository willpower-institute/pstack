"""AppContext — จุดกลางที่ kernel และโมดูลใช้ร่วมกัน

โมดูลเข้าถึงผ่าน `from core.runtime import ctx`
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from core.events import EventBus

if TYPE_CHECKING:
    from fastapi import FastAPI
    from jinja2 import Environment
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.config import Settings
    from core.loader import ModuleInfo


class AppContext:
    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.settings: Settings | None = None
        self.events = EventBus()
        self.modules: dict[str, ModuleInfo] = {}
        self.load_order: list[ModuleInfo] = []
        self.jinja_env: Environment | None = None
        # โมดูล users ลงทะเบียน loader นี้ให้ core.auth ใช้หา user จาก token
        self.user_loader: Callable[[AsyncSession, int], Awaitable[Any]] | None = None


ctx = AppContext()
