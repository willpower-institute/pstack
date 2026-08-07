"""AI tool สาธารณะ (permission=None) — guest ที่ทักมาทาง LINE ก็ถามได้"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.faq.models import Faq
from core.ai import agent_tool


@agent_tool(module="faq", permission=None)
async def search_faq(session: AsyncSession, query: str) -> str:
    """ค้นหาคำถามที่พบบ่อย (FAQ) จากคำค้น — ใช้ตอบคำถามทั่วไปเกี่ยวกับระบบ/บริการ"""
    result = await session.execute(
        select(Faq)
        .where(Faq.question.ilike(f"%{query}%") | Faq.answer.ilike(f"%{query}%"))
        .order_by(Faq.sort, Faq.id)
        .limit(5)
    )
    faqs = list(result.scalars())
    if not faqs:
        return "ไม่พบ FAQ ที่ตรงกับคำค้นนี้"
    return "\n\n".join(f"Q: {f.question}\nA: {f.answer}" for f in faqs)
