from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_permission
from core.db import get_session

from addons.line_oa import bridge, services
from addons.line_oa.client import verify_signature
from addons.line_oa.config import get_line_settings
from addons.line_oa.models import LineChannel

router = APIRouter(prefix="/api/line", tags=["line_oa"])


class ChannelIn(BaseModel):
    name: str
    channel_id: str
    channel_secret: str
    access_token: str
    agent_enabled: bool = True
    greeting: str = ""
    quick_menu: list[dict] = []


class ChannelUpdateIn(BaseModel):
    name: str | None = None
    access_token: str | None = None
    agent_enabled: bool | None = None
    greeting: str | None = None
    quick_menu: list[dict] | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    channel_id: str
    agent_enabled: bool
    greeting: str
    quick_menu: list

    model_config = {"from_attributes": True}


class LinkCodeOut(BaseModel):
    code: str
    expires_in_minutes: int


@router.post("/channels", response_model=ChannelOut, status_code=201)
async def create_channel(
    data: ChannelIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(require_permission("line_oa.manage"))],
):
    if await services.get_channel_by_line_id(session, data.channel_id):
        raise HTTPException(status_code=409, detail="channel_id already exists")
    record = LineChannel(**data.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(require_permission("line_oa.manage"))],
):
    result = await session.execute(select(LineChannel).order_by(LineChannel.id))
    return list(result.scalars())


@router.patch("/channels/{channel_pk}", response_model=ChannelOut)
async def update_channel(
    channel_pk: int,
    data: ChannelUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(require_permission("line_oa.manage"))],
):
    record = await session.get(LineChannel, channel_pk)
    if record is None:
        raise HTTPException(status_code=404, detail="channel not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    await session.commit()
    await session.refresh(record)
    return record


@router.post("/link-code", response_model=LinkCodeOut)
async def create_link_code(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    """ขอโค้ดผูกบัญชี — เอาไปพิมพ์ `link <code>` ในแชท LINE OA"""
    record = await services.create_link_code(session, user.id)
    return LinkCodeOut(
        code=record.code,
        expires_in_minutes=get_line_settings().link_code_ttl_minutes,
    )


@router.post("/webhook/{channel_id}")
async def webhook(
    channel_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """endpoint สาธารณะสำหรับ LINE platform — ยืนยันตัวตนด้วย X-Line-Signature"""
    channel = await services.get_channel_by_line_id(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="unknown channel")

    body = await request.body()
    signature = request.headers.get("x-line-signature")
    if not verify_signature(channel.channel_secret, body, signature):
        raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()
    await bridge.dispatch(channel.id, payload.get("events", []))
    return {"status": "ok"}
