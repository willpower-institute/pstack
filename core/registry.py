"""Module registry — สถานะการติดตั้งโมดูลใน DB + lifecycle install/upgrade

หลักการ: PSTACK_MODULES ใน settings เป็น declarative list ว่าระบบนี้ใช้โมดูลอะไร
ตอนบูต kernel เทียบกับตาราง pstack_module:
  - ยังไม่เคยติดตั้ง  -> สร้างตารางของโมดูล + on_install hook + บันทึก record
  - version ใน manifest ใหม่กว่า -> สร้างตารางที่เพิ่มใหม่ + on_upgrade hook + อัปเดต record
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.loader import ModuleInfo

logger = logging.getLogger(__name__)


class ModuleRecord(Base):
    __tablename__ = "pstack_module"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32))
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


async def create_core_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[ModuleRecord.__table__], checkfirst=True
        )


async def _create_module_tables(engine: AsyncEngine, info: ModuleInfo) -> None:
    tables = [Base.metadata.tables[t] for t in info.tables]
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables, checkfirst=True)


async def sync_modules(
    engine: AsyncEngine, session: AsyncSession, load_order: list[ModuleInfo]
) -> None:
    for info in load_order:
        record = await session.get(ModuleRecord, info.name)
        if record is None:
            logger.info("installing module '%s' %s", info.name, info.version)
            await _create_module_tables(engine, info)
            if info.hooks and hasattr(info.hooks, "on_install"):
                await info.hooks.on_install(session)
            session.add(ModuleRecord(name=info.name, version=info.version))
            await session.commit()
        elif record.version != info.version:
            logger.info(
                "upgrading module '%s' %s -> %s", info.name, record.version, info.version
            )
            await _create_module_tables(engine, info)  # ตารางใหม่ที่เพิ่มมา
            if info.hooks and hasattr(info.hooks, "on_upgrade"):
                await info.hooks.on_upgrade(session, record.version)
            record.version = info.version
            await session.commit()


async def installed_modules(session: AsyncSession) -> list[ModuleRecord]:
    result = await session.execute(select(ModuleRecord).order_by(ModuleRecord.name))
    return list(result.scalars())
