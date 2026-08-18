"""จัดการ webhook event + สะพานเชื่อม LINE ↔ AI agent

หลักการ: webhook ตอบ 200 เร็วที่สุด งานหนัก (agent) รันเป็น background task
(PSTACK_LINE_SYNC=true จะ await ให้จบก่อนตอบ — ใช้ในเทส)

สิทธิ์ของ agent:
  - LINE user ที่ผูกบัญชีแล้ว -> ใช้ tools ตาม RBAC ของ user คนนั้น
  - ยังไม่ผูก -> ใช้ผ่าน guest user (ได้เฉพาะ tools ที่ไม่ต้องการ permission)
"""

from __future__ import annotations

import asyncio
import logging

from addons.ai_agent import services as agent_services
from addons.ai_agent.runtime import build_system_prompt, get_runtime
from addons.line_oa import client as line_client
from addons.line_oa import services
from addons.line_oa.config import get_line_settings
from addons.line_oa.models import LineChannel, LineUser
from addons.users.models import User
from core.db import get_sessionmaker
from core.runtime import ctx

logger = logging.getLogger(__name__)

LINE_STYLE = (
    "บริบท: คุยผ่านแชท LINE — ตอบสั้นกระชับเป็นข้อความธรรมดา ไม่ใช้ markdown "
    "ไม่ใช้ตาราง ขึ้นบรรทัดใหม่แทน bullet ได้"
)


async def handle_events(channel_pk: int, events: list[dict]) -> None:
    for event in events:
        try:
            await _handle_event(channel_pk, event)
        except Exception:
            logger.exception("line event handling failed: %s", event.get("type"))


def dispatch(channel_pk: int, events: list[dict]):
    """คืน coroutine ที่ webhook จะ await (sync mode) หรือโยนเป็น task"""
    if get_line_settings().sync_mode:
        return handle_events(channel_pk, events)
    task = asyncio.create_task(handle_events(channel_pk, events))
    task.add_done_callback(lambda t: t.exception())  # กัน unhandled warning

    async def _noop() -> None:
        return None

    return _noop()


async def _handle_event(channel_pk: int, event: dict) -> None:
    etype = event.get("type")
    source = event.get("source", {})
    line_user_id = source.get("userId")
    if not line_user_id:
        return

    async with get_sessionmaker()() as db:
        channel = await db.get(LineChannel, channel_pk)
        if channel is None:
            return
        line_user = await services.get_or_create_line_user(db, channel, line_user_id)

        if etype == "follow":
            line_user.followed = True
            await db.commit()
            await ctx.events.emit(
                "line.followed",
                {"channel": channel.channel_id, "line_user_id": line_user_id},
                broadcast=True,
            )
            if channel.greeting:
                await line_client.reply(
                    channel.access_token,
                    event.get("replyToken", ""),
                    [line_client.text_message(channel.greeting, channel.quick_menu)],
                )
            return

        if etype == "unfollow":
            line_user.followed = False
            await db.commit()
            await ctx.events.emit(
                "line.unfollowed",
                {"channel": channel.channel_id, "line_user_id": line_user_id},
                broadcast=True,
            )
            return

        if etype == "postback":
            await ctx.events.emit(
                "line.postback",
                {
                    "channel": channel.channel_id,
                    "line_user_id": line_user_id,
                    "data": event.get("postback", {}).get("data", ""),
                },
                broadcast=True,
            )
            return

        if etype != "message" or event.get("message", {}).get("type") != "text":
            return

        text = event["message"]["text"]
        reply_token = event.get("replyToken", "")

        await ctx.events.emit(
            "line.message.received",
            {
                "channel": channel.channel_id,
                "channel_pk": channel.id,  # ใช้หา access_token ได้โดยไม่ต้อง query ซ้ำ
                "line_user_id": line_user_id,
                "text": text,
                "reply_token": reply_token,  # โมดูลที่ตอบเองใช้ client.respond() ได้ (#6)
            },
            broadcast=True,
        )

        # คำสั่งผูกบัญชี: "link <CODE>"
        stripped = text.strip()
        if stripped.lower().startswith("link ") or stripped.lower() == "link":
            parts = stripped.split(maxsplit=1)
            code = parts[1] if len(parts) > 1 else ""
            user = await services.redeem_link_code(db, line_user, code) if code else None
            if user:
                msg = f"ผูกบัญชีกับ {user.full_name or user.email} สำเร็จแล้วครับ ✅"
            else:
                msg = "โค้ดไม่ถูกต้องหรือหมดอายุ — ขอโค้ดใหม่จากหน้าโปรไฟล์ในระบบครับ"
            await line_client.reply(
                channel.access_token, reply_token, [line_client.text_message(msg)]
            )
            return

        if not channel.agent_enabled:
            return  # โมดูลอื่น subscribe line.message.received ไปตอบเองได้

    # งาน agent — เปิด session DB ใหม่ (คนละ scope กับด้านบน)
    answer = await _run_agent(channel_pk, line_user.id, text)
    if answer:
        # respond() ลอง reply ก่อน (agent อาจใช้เวลานานจน token หมด) แล้ว fallback push ให้เอง
        await line_client.respond(
            channel.access_token, reply_token, line_user_id, [line_client.text_message(answer)]
        )


async def _run_agent(channel_pk: int, line_user_pk: int, text: str) -> str:
    async with get_sessionmaker()() as db:
        line_user = await db.get(LineUser, line_user_pk)
        if line_user.user_id is not None:
            user = await db.get(User, line_user.user_id)
        else:
            user = await services.get_guest_user(db)

        if line_user.agent_session_id is None:
            agent_session = await agent_services.create_session(
                db, user.id, title=f"LINE: {line_user.line_user_id[:12]}"
            )
            line_user.agent_session_id = agent_session.id
            await db.commit()
        session_id = line_user.agent_session_id

        history_rows = await agent_services.list_messages(db, session_id)
        history = [{"role": r.role, "content": r.content} for r in history_rows]
        tools = agent_services.tools_for_user(user)
        system = build_system_prompt(user, tools) + "\n\n" + LINE_STYLE

    async def save(role: str, content: list, msg_text: str) -> None:
        async with get_sessionmaker()() as db2:
            await agent_services.append_message(db2, session_id, role, content, msg_text)

    chunks: list[str] = []
    runtime = get_runtime()
    try:
        async for ev in runtime.run_turn(history, text, tools, system, save):
            if ev["type"] == "text":
                chunks.append(ev["delta"])
            elif ev["type"] == "error":
                logger.error("line agent error: %s", ev)
                return "ขออภัยครับ ระบบขัดข้องชั่วคราว ลองใหม่อีกครั้งนะครับ"
    except Exception:
        logger.exception("line agent turn failed")
        return "ขออภัยครับ ระบบขัดข้องชั่วคราว ลองใหม่อีกครั้งนะครับ"
    return "".join(chunks).strip()
