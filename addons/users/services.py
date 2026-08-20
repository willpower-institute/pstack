import secrets
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.users.models import User
from core.auth import hash_password, verify_password
from core.runtime import ctx


async def load_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """hash ของรหัสสุ่มที่ไม่มีใครรู้ — ใช้เผา CPU ให้เท่ากันตอนไม่เจอ user

    คำนวณครั้งเดียวต่อโปรเซส (bcrypt กิน ~300ms) แล้ว cache ไว้
    """
    return hash_password(secrets.token_urlsafe(32))


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(session, email)
    if user is None:
        # เทียบกับ hash หลอกให้เสียเวลาเท่ากับกรณีที่เจอ user จริง
        # ไม่งั้นเวลาตอบต่างกัน ~50 เท่า (327ms vs 6ms) = กวาดได้ว่าอีเมลไหนมีบัญชี
        verify_password(password, _dummy_hash())
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_user(
    session: AsyncSession,
    email: str,
    password: str,
    full_name: str = "",
    is_superuser: bool = False,
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await ctx.events.emit("users.created", {"user_id": user.id, "email": user.email})
    return user


async def count_active(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )
    return result.scalar_one()
