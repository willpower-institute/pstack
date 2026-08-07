import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import get_session, get_sessionmaker

from addons.ai_agent import services
from addons.ai_agent.runtime import build_system_prompt, get_runtime

router = APIRouter(prefix="/api/agent", tags=["ai_agent"])


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


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    data: SessionCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.create_session(session, user.id, data.title)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.list_sessions(session, user.id)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    await services.get_owned_session(session, session_id, user)
    records = await services.list_messages(session, session_id)
    # แสดงเฉพาะแถวที่มีข้อความ (ข้าม tool traffic)
    return [r for r in records if r.text]


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(user: Annotated[object, Depends(get_current_user)]):
    return [
        ToolOut(name=t.name, module=t.module, description=t.description)
        for t in services.tools_for_user(user)
    ]


@router.post("/sessions/{session_id}/messages")
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
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': 'internal', 'detail': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
