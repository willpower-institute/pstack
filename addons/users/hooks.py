import logging

from sqlalchemy.ext.asyncio import AsyncSession

from addons.users import services
from core.config import get_settings

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
    if settings.admin_password == "admin":
        logger.warning("admin password ยังเป็นค่า default — เปลี่ยนทันทีใน production!")


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
