from sqlalchemy.ext.asyncio import AsyncSession

from addons.line_oa import services


async def on_install(session: AsyncSession) -> None:
    # เตรียม guest user ไว้ล่วงหน้า (สำหรับ LINE user ที่ยังไม่ผูกบัญชี)
    await services.get_guest_user(session)


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
