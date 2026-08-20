import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from addons.ai_agent import services
from addons.ai_agent.runtime import build_system_prompt, get_runtime
from core.auth import get_current_user
from core.db import get_session, get_sessionmaker

# router หลักของโมดูล (loader mount ตัวนี้) — หน้าเว็บอยู่ที่ /agent, API อยู่ใต้ /api/agent
router = APIRouter(tags=["ai_agent"])
api = APIRouter(prefix="/api/agent")


@router.get("/agent")
async def chat_page():
    """หน้าแชทตัวอย่าง — เปิดเบราว์เซอร์คุยกับ agent ได้เลย (login ด้วยบัญชีในระบบ)"""
    from core.templating import render

    return render("ai_agent/chat.html")


class SessionCreateIn(BaseModel):
    title: str = ""


class SessionOut(BaseModel):
    id: int
    title: str
    tenant_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatIn(BaseModel):
    text: str


class ToolOut(BaseModel):
    name: str
    module: str
    description: str


@api.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    data: SessionCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
):
    """สร้างแชทใหม่ — ส่ง X-Tenant-Id มาด้วยเพื่อผูก session นี้กับ tenant

    tenant ถูกผูกที่ตอนสร้าง **ครั้งเดียว** แล้วใช้กับทุก turn ในแชทนั้น
    เปลี่ยน tenant กลางแชทไม่ได้ (ต้องเปิดแชทใหม่) — กันประวัติสองบริบทปนกัน
    """
    if x_tenant_id:
        try:
            await services.authorize_tenant(session, user, x_tenant_id)
        except services.TenantNotAllowed:
            # 404 ไม่ใช่ 403 — ไม่ยืนยันให้คนนอกรู้ว่า tenant นี้มีอยู่จริง
            raise HTTPException(status_code=404, detail="ไม่พบ tenant") from None
    return await services.create_session(session, user.id, data.title, x_tenant_id)


@api.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.list_sessions(session, user.id)


@api.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    await services.get_owned_session(session, session_id, user)
    records = await services.list_messages(session, session_id)
    # แสดงเฉพาะแถวที่มีข้อความ (ข้าม tool traffic)
    return [r for r in records if r.text]


@api.get("/tools", response_model=list[ToolOut])
async def list_tools(user: Annotated[object, Depends(get_current_user)]):
    return [
        ToolOut(name=t.name, module=t.module, description=t.description)
        for t in services.tools_for_user(user)
    ]


@api.post("/sessions/{session_id}/messages")
async def chat(
    session_id: int,
    data: ChatIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    """ส่งข้อความหา agent — ตอบกลับเป็น SSE stream (text/event-stream)"""
    record = await services.get_owned_session(session, session_id, user)
    if record.tenant_id:
        # ตรวจซ้ำทุก turn — สมาชิกภาพอาจถูกถอนหลังจากสร้าง session ไปแล้ว
        try:
            await services.authorize_tenant(session, user, record.tenant_id)
        except services.TenantNotAllowed as e:
            raise HTTPException(status_code=403, detail=str(e)) from None
    history_rows = await services.list_messages(session, session_id)
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    if not record.title:
        record.title = data.text[:80]
        await session.commit()

    tools = services.tools_for_user(user)
    system = build_system_prompt(user, tools, record.tenant_id)
    runtime = get_runtime()

    async def save(role: str, content: list, text: str) -> None:
        # ใช้ session ใหม่ต่อครั้ง — SSE generator รันยาวกว่า request dependency scope
        async with get_sessionmaker()() as db:
            await services.append_message(db, session_id, role, content, text)

    async def sse() -> object:
        try:
            async for event in runtime.run_turn(
                history, data.text, tools, system, save, record.tenant_id
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': 'internal', 'detail': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


router.include_router(api)
