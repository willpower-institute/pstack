from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.faq.models import Faq

SEED = [
    ("ระบบนี้คืออะไร", "pstack — BaaS framework ที่ขยายได้ด้วยโมดูล พร้อม AI agent ในตัว", 1),
    ("ติดต่อทีมงานได้ทางไหน", "ทักผ่าน LINE OA หรืออีเมลผู้ดูแลระบบได้เลยครับ", 2),
]


async def on_install(session: AsyncSession) -> None:
    count = (await session.execute(select(func.count()).select_from(Faq))).scalar_one()
    if count:
        return
    for question, answer, sort in SEED:
        session.add(Faq(question=question, answer=answer, sort=sort))
    await session.commit()


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
