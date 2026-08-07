"""ตัวอย่าง AI tools — pattern ที่ทุกโมดูลใช้ expose ความสามารถให้ agent"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.users import services
from addons.users.models import User
from core.ai import agent_tool


@agent_tool(module="users", permission="users.read")
async def count_users(session: AsyncSession) -> str:
    """นับจำนวนผู้ใช้ที่ active อยู่ในระบบ"""
    n = await services.count_active(session)
    return f"มีผู้ใช้ active {n} คน"


@agent_tool(module="users", permission="users.read")
async def search_users(session: AsyncSession, query: str) -> str:
    """ค้นหาผู้ใช้จากอีเมลหรือชื่อ (คืนไม่เกิน 10 รายการ)"""
    result = await session.execute(
        select(User)
        .where((User.email.ilike(f"%{query}%")) | (User.full_name.ilike(f"%{query}%")))
        .limit(10)
    )
    users = list(result.scalars())
    if not users:
        return "ไม่พบผู้ใช้ที่ตรงกับคำค้น"
    return "\n".join(f"- {u.full_name or '(ไม่มีชื่อ)'} <{u.email}>" for u in users)
