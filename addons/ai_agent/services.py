from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.ai_agent.models import AgentMessage, AgentSession
from core.ai import get_tools
from core.ai.tools import ToolDef


class TenantNotAllowed(Exception):
    """user เข้าถึง tenant ที่ขอไม่ได้ — หรือระบบไม่ได้เปิดโมดูล tenancy ไว้"""


async def authorize_tenant(session: AsyncSession, user, tenant_id: str) -> None:
    """ตรวจว่า user เข้าถึง tenant นี้ได้จริง — fail closed เสมอ

    วางไว้ที่ ai_agent เพราะทั้ง agent ภายในและ mcp_server (ซึ่ง depends ai_agent อยู่แล้ว)
    ใช้ร่วมกัน · ไม่ import addons.tenancy ที่ระดับ module เพื่อให้ deployment ที่ไม่ได้
    เปิด tenancy ยัง import โมดูลนี้ได้ตามปกติ
    """
    if getattr(user, "is_superuser", False):
        return

    from core.runtime import ctx

    if not any(m.name == "tenancy" for m in ctx.load_order):
        raise TenantNotAllowed("ระบบนี้ไม่ได้เปิดโมดูล tenancy — ระบุ tenant ไม่ได้")

    from addons.tenancy.services import is_member

    if not await is_member(session, tenant_id, user.id):
        raise TenantNotAllowed(f"ไม่มีสิทธิ์ใน tenant: {tenant_id}")


async def create_session(
    session: AsyncSession, user_id: int, title: str = "", tenant_id: str | None = None
) -> AgentSession:
    record = AgentSession(user_id=user_id, title=title, tenant_id=tenant_id)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_owned_session(
    session: AsyncSession, session_id: int, user
) -> AgentSession:
    record = await session.get(AgentSession, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="session not found")
    if record.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="not your session")
    return record


async def list_sessions(session: AsyncSession, user_id: int) -> list[AgentSession]:
    result = await session.execute(
        select(AgentSession)
        .where(AgentSession.user_id == user_id)
        .order_by(AgentSession.updated_at.desc())
    )
    return list(result.scalars())


async def list_messages(session: AsyncSession, session_id: int) -> list[AgentMessage]:
    result = await session.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.id)
    )
    return list(result.scalars())


async def append_message(
    session: AsyncSession, session_id: int, role: str, content: list, text: str = ""
) -> AgentMessage:
    record = AgentMessage(session_id=session_id, role=role, content=content, text=text)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


def user_permissions(user) -> set[str] | None:
    """คืน None = superuser (ได้ทุกอย่าง), ไม่งั้นคืน set ของ permission"""
    if user.is_superuser:
        return None
    perms: set[str] = set()
    for role in getattr(user, "roles", []):
        perms.update(role.permissions or [])
    return perms


def tools_for_user(user) -> list[ToolDef]:
    perms = user_permissions(user)
    tools = []
    for tool in get_tools():
        if perms is None or tool.permission is None or tool.permission in perms:
            tools.append(tool)
    return tools
