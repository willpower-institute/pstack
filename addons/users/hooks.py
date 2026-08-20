import logging

from sqlalchemy.ext.asyncio import AsyncSession

from addons.users import services
from core.auth import verify_password
from core.config import WEAK_ADMIN_PASSWORDS, get_settings

logger = logging.getLogger(__name__)


async def on_install(session: AsyncSession) -> None:
    """สร้าง admin คนแรกจาก PSTACK_ADMIN_EMAIL / PSTACK_ADMIN_PASSWORD"""
    settings = get_settings()
    if await services.get_by_email(session, settings.admin_email):
        return
    await services.create_user(
        session,
        email=settings.admin_email,
        password=settings.admin_password,
        full_name="Administrator",
        is_superuser=True,
    )
    logger.info("created initial admin user: %s", settings.admin_email)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    """ตรวจว่ารหัสของ admin ในฐานข้อมูลยังเป็นค่าที่เดาได้อยู่ไหม

    ตรวจ "ของจริงใน DB" ไม่ใช่ค่าใน .env เพราะ PSTACK_ADMIN_PASSWORD ใช้แค่ตอน
    สร้างบัญชีครั้งแรก — deployment ที่ติดตั้งไว้ตั้งแต่ก่อนมีการบังคับ
    อาจยังใช้ admin/admin อยู่แม้ .env จะถูกแก้ไปแล้ว
    """
    settings = get_settings()
    admin = await services.get_by_email(session, settings.admin_email)
    if admin is None:
        return
    weak = next(
        (p for p in WEAK_ADMIN_PASSWORDS if p and verify_password(p, admin.password_hash)),
        None,
    )
    if weak is not None:
        logger.error(
            "บัญชี %s ยังใช้รหัสผ่านที่เดาได้อยู่ — ใครก็เข้าระบบเป็น superuser ได้ "
            "เปลี่ยนทันทีด้วย: python cli.py set-password %s",
            settings.admin_email,
            settings.admin_email,
        )
