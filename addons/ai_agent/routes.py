import json
import logging
import traceback
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from addons.ai_agent import services
from addons.ai_agent.runtime import build_system_prompt, get_runtime
from core.auth import get_current_user
from core.config import get_settings
from core.db import get_session, get_sessionmaker

logger = logging.getLogger(__name__)

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
):
    return await services.create_session(session, user.id, data.title)


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
    history_rows = await services.list_messages(session, session_id)
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    if not record.title:
        record.title = data.text[:80]
        await session.commit()

    tools = services.tools_for_user(user)
    system = build_system_prompt(user, tools)
    runtime = get_runtime()

    async def save(role: str, content: list, text: str) -> None:
        # ใช้ session ใหม่ต่อครั้ง — SSE generator รันยาวกว่า request dependency scope
        async with get_sessionmaker()() as db:
            await services.append_message(db, session_id, role, content, text)

    async def sse() -> object:
        try:
            async for event in runtime.run_turn(history, data.text, tools, system, save):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            # อย่าส่งข้อความ exception ดิบออกไปให้ client — มันรั่วได้ทั้ง
            # connection string, path บนดิสก์ หรือ SQL ที่ล้มเหลว
            # ส่งไปแค่รหัสอ้างอิงที่เอาไปค้นใน log ของ server ได้
            ref = uuid.uuid4().hex[:8]
            logger.exception("agent turn ล้มเหลว (ref=%s) session=%s", ref, session_id)
            payload = {"type": "error", "error": "internal", "ref": ref}
            if get_settings().debug:
                payload["detail"] = traceback.format_exc()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


router.include_router(api)
