from sqlalchemy.ext.asyncio import AsyncSession


async def on_install(session: AsyncSession) -> None:
    # ไม่ seed tenant ให้อัตโนมัติ — tenant แรกสร้างผ่าน API/สคริปต์ของ deployment
    pass


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
