"""Helper สำหรับเทส async — เลี่ยงบั๊ก global engine ผูกกับ event loop (issue #8)

`core.db.get_engine()` เก็บ engine เป็น global ตัวเดียว engine นั้นผูกกับ event loop ที่สร้างมัน
เทส async ที่ใช้ loop ใหม่ต่อเทส (pytest-asyncio) แล้วหยิบ engine เดิมมาใช้จะเจอ
`RuntimeError: got Future attached to a different loop` บน asyncpg — aiosqlite เงียบเพราะ
รันบน thread บั๊กจึงโผล่เฉพาะตอนเปิด Postgres ใน CI

ใช้ helper นี้สร้าง engine แยกต่อเทส:

    import pytest_asyncio
    from core.testing import isolated_session

    @pytest_asyncio.fixture
    async def db_session():
        async with isolated_session() as session:
            yield session
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import get_settings


@asynccontextmanager
async def isolated_session(database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    """สร้าง engine + session ของตัวเอง แล้ว dispose เมื่อจบ — ไม่แตะ global engine

    database_url เว้นไว้ = ใช้ค่าจาก settings (PSTACK_DATABASE_URL)
    """
    engine = create_async_engine(database_url or get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()
