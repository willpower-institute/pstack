from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import hash_password, verify_password
from core.runtime import ctx

from addons.users.models import User


async def load_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(session, email)
    if user is None or not verify_password(password, user.password_hash):
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
