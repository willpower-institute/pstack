"""AI tools ของโมดูล line_oa"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.line_oa import client as line_client
from addons.line_oa.models import LineChannel, LineUser
from addons.users.models import User
from core.ai import agent_tool


@agent_tool(module="line_oa", permission="line_oa.push")
async def send_line_push(session: AsyncSession, email: str, message: str) -> str:
    """ส่งข้อความ push ทาง LINE ไปหาผู้ใช้ในระบบ (ระบุด้วยอีเมล) — ผู้ใช้ต้องเคยผูกบัญชี LINE ไว้"""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return f"ไม่พบผู้ใช้ {email}"
    result = await session.execute(
        select(LineUser).where(LineUser.user_id == user.id, LineUser.followed.is_(True))
    )
    line_user = result.scalars().first()
    if line_user is None:
        return f"{email} ยังไม่ได้ผูกบัญชี LINE"
    channel = await session.get(LineChannel, line_user.channel_pk)
    ok = await line_client.push(
        channel.access_token, line_user.line_user_id, [line_client.text_message(message)]
    )
    return "ส่งข้อความแล้ว" if ok else "ส่งไม่สำเร็จ (LINE API error)"
