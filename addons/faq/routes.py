from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.faq.models import Faq
from core.auth import require_permission
from core.db import get_session
from core.templating import render

router = APIRouter(tags=["faq"])


class FaqIn(BaseModel):
    question: str
    answer: str
    sort: int = 0


class FaqOut(BaseModel):
    id: int
    question: str
    answer: str
    sort: int

    model_config = {"from_attributes": True}


async def _all_faqs(session: AsyncSession) -> list[Faq]:
    result = await session.execute(select(Faq).order_by(Faq.sort, Faq.id))
    return list(result.scalars())


@router.get("/faq")
async def faq_page(session: Annotated[AsyncSession, Depends(get_session)]):
    """หน้า HTML สาธารณะ — เทมเพลตมาจาก templates/ ของโมดูลนี้เอง"""
    return render("faq/index.html", {"faqs": await _all_faqs(session)})


@router.get("/api/faq", response_model=list[FaqOut])
async def list_faq(session: Annotated[AsyncSession, Depends(get_session)]):
    return await _all_faqs(session)


@router.post("/api/faq", response_model=FaqOut, status_code=201)
async def create_faq(
    data: FaqIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(require_permission("faq.manage"))],
):
    record = Faq(**data.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/api/faq/{faq_id}", status_code=204)
async def delete_faq(
    faq_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(require_permission("faq.manage"))],
):
    record = await session.get(Faq, faq_id)
    if record is None:
        raise HTTPException(status_code=404, detail="faq not found")
    await session.delete(record)
    await session.commit()
