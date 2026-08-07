from sqlalchemy.ext.asyncio import AsyncSession


async def on_install(session: AsyncSession) -> None:
    pass


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
