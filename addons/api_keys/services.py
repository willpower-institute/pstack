import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.api_keys.models import ApiKey
from addons.users.models import User

KEY_PREFIX = "psk_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_key(session: AsyncSession, user_id: int, name: str) -> tuple[ApiKey, str]:
    """คืน (record, plaintext) — plaintext แสดงครั้งเดียว ไม่ถูกเก็บ"""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    record = ApiKey(
        name=name,
        key_prefix=plaintext[:12],
        key_hash=_hash(plaintext),
        user_id=user_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record, plaintext


async def resolve_api_key(session: AsyncSession, token: str) -> User | None:
    """token resolver ที่เสียบเข้า core.auth — คืน None = ไม่ใช่ key ของเรา ให้ลองวิธีอื่นต่อ"""
    if not token.startswith(KEY_PREFIX):
        return None
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == _hash(token), ApiKey.revoked_at.is_(None))
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    user = await session.get(User, record.user_id)
    if user is None:
        return None
    # อัปเดต last_used_at แบบหยาบๆ (เว้นช่วง > 60 วิ ลดการเขียนถี่)
    now = datetime.now(UTC)
    last = record.last_used_at
    if last is not None and last.tzinfo is None:  # sqlite เก็บ naive
        last = last.replace(tzinfo=UTC)
    if last is None or (now - last).total_seconds() > 60:
        record.last_used_at = now
        await session.commit()
    return user


async def list_keys(session: AsyncSession, user_id: int) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id.desc())
    )
    return list(result.scalars())


async def revoke_key(session: AsyncSession, record: ApiKey) -> None:
    record.revoked_at = datetime.now(UTC)
    await session.commit()
