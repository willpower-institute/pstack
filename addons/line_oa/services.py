import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import hash_password

from addons.line_oa.config import get_line_settings
from addons.line_oa.models import LineChannel, LineLinkCode, LineUser
from addons.users.models import User

GUEST_EMAIL = "line-guest@pstack.local"


async def get_channel_by_line_id(session: AsyncSession, channel_id: str) -> LineChannel | None:
    result = await session.execute(
        select(LineChannel).where(LineChannel.channel_id == channel_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_line_user(
    session: AsyncSession, channel: LineChannel, line_user_id: str
) -> LineUser:
    result = await session.execute(
        select(LineUser).where(
            LineUser.channel_pk == channel.id, LineUser.line_user_id == line_user_id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = LineUser(channel_pk=channel.id, line_user_id=line_user_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return record


async def get_guest_user(session: AsyncSession) -> User:
    """service user สำหรับ LINE user ที่ยังไม่ผูกบัญชี — ไม่มี role จึงใช้ได้เฉพาะ
    tools ที่ไม่ต้องการ permission"""
    result = await session.execute(select(User).where(User.email == GUEST_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=GUEST_EMAIL,
            full_name="LINE Guest",
            password_hash=hash_password(secrets.token_hex(32)),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


# ---- account linking ----


async def create_link_code(session: AsyncSession, user_id: int) -> LineLinkCode:
    settings = get_line_settings()
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    record = LineLinkCode(
        code=code,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.link_code_ttl_minutes),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def redeem_link_code(
    session: AsyncSession, line_user: LineUser, code: str
) -> User | None:
    result = await session.execute(
        select(LineLinkCode).where(LineLinkCode.code == code.strip().upper())
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:  # sqlite เก็บ naive datetime
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await session.delete(record)
        await session.commit()
        return None
    user = await session.get(User, record.user_id)
    line_user.user_id = record.user_id
    line_user.agent_session_id = None  # เริ่ม agent session ใหม่ในสิทธิ์ของ user จริง
    await session.delete(record)
    await session.commit()
    return user
