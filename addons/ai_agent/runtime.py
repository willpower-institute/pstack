"""Agent runtime — manual agentic loop บน AsyncAnthropic streaming

เหตุที่ใช้ manual loop แทน SDK tool runner: tools ของเรามาจาก registry แบบ dynamic
(JSON schema สร้างไว้แล้ว + ต้องเช็ค permission ต่อ user + inject DB session ตอนรัน)

โฟลว์ต่อหนึ่งข้อความของผู้ใช้:
  user msg -> [stream assistant -> ถ้า tool_use: รัน tools + ส่ง tool_result กลับ]* -> done
ทุก entry (รวม tool traffic และ thinking blocks) ถูกเก็บลง DB เพื่อ replay ใน turn ถัดไป
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from addons.ai_agent.config import get_ai_settings
from core.ai.tools import ToolDef
from core.db import get_sessionmaker
from core.tenancy import bind_tenant

logger = logging.getLogger(__name__)


def _dump_blocks(content: list[Any]) -> list[dict]:
    return [b if isinstance(b, dict) else b.model_dump() for b in content]


def _text_of(blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def sanitize_assistant_content(blocks: list[dict]) -> list[dict]:
    """กติกา echo หลัง mid-stream fallback: ตัด thinking/tool_use ที่อยู่ก่อน
    fallback block สุดท้ายออก (เก็บ text ไว้) — ไม่มี fallback ก็คืนตามเดิม"""
    fallback_idx = [i for i, b in enumerate(blocks) if b.get("type") == "fallback"]
    if not fallback_idx:
        return blocks
    last = fallback_idx[-1]
    head = [b for b in blocks[:last] if b.get("type") in ("text", "fallback")]
    return head + blocks[last:]


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = get_ai_settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic()  # อ่าน ANTHROPIC_API_KEY จาก env
        return self._client

    def _stream_ctx(self, *, system: str, messages: list[dict], tools: list[dict]):
        kwargs: dict[str, Any] = dict(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        if self.settings.fallbacks:
            # claude-opus-5: ให้ระบบ re-route ไปโมเดล fallback อัตโนมัติเมื่อโดน refusal
            return self.client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        return self.client.messages.stream(**kwargs)

    async def _run_tool(
        self, tool: ToolDef, tool_input: dict, tenant_id: str | None = None
    ) -> tuple[str, bool]:
        try:
            async with get_sessionmaker()() as db:
                if tenant_id:
                    # session ผูก tenant ไว้ตอนสร้าง — bind ให้ RLS กรองที่ชั้น DB
                    # และให้ tool อ่านผ่าน core.tenancy.bound_tenant() ได้
                    await bind_tenant(db, tenant_id)
                result = await tool.fn(db, **tool_input)
            return str(result), False
        except Exception as e:
            logger.exception("agent tool '%s' failed", tool.name)
            return f"tool error: {e}", True

    async def run_turn(
        self,
        history: list[dict],
        user_text: str,
        tools: list[ToolDef],
        system: str,
        save,  # async fn(role, content_blocks, text) -> เก็บลง DB
        tenant_id: str | None = None,  # tenant ที่ผูกกับ agent session นี้
    ) -> AsyncIterator[dict]:
        """yield event dicts: text / tool_use / tool_result / done / error"""
        tool_map = {t.name: t for t in tools}
        tool_defs = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

        user_blocks = [{"type": "text", "text": user_text}]
        messages = history + [{"role": "user", "content": user_blocks}]
        await save("user", user_blocks, user_text)

        for _ in range(self.settings.max_loops):
            async with self._stream_ctx(
                system=system, messages=messages, tools=tool_defs
            ) as stream:
                async for delta in stream.text_stream:
                    if delta:
                        yield {"type": "text", "delta": delta}
                final = await stream.get_final_message()

            blocks = sanitize_assistant_content(_dump_blocks(final.content))
            assistant_text = _text_of(blocks)
            messages.append({"role": "assistant", "content": blocks})
            await save("assistant", blocks, assistant_text)

            stop = final.stop_reason
            if stop == "refusal":
                yield {"type": "error", "error": "refusal", "detail": "คำขอนี้ถูกปฏิเสธโดยระบบความปลอดภัยของโมเดล"}
                return
            if stop == "pause_turn":
                continue  # server-side tool ค้างกลางคัน — ส่งกลับไปให้ทำต่อ
            if stop != "tool_use":
                yield {"type": "done"}
                return

            # รัน tools ทุกตัวที่ขอมา แล้วส่งผลกลับใน user message เดียว
            results: list[dict] = []
            for block in blocks:
                if block.get("type") != "tool_use":
                    continue
                name = block["name"]
                yield {"type": "tool_use", "name": name, "input": block.get("input", {})}
                tool = tool_map.get(name)
                if tool is None:
                    output, is_error = f"unknown tool: {name}", True
                else:
                    output, is_error = await self._run_tool(
                        tool, block.get("input") or {}, tenant_id
                    )
                yield {"type": "tool_result", "name": name, "ok": not is_error}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": output,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
            await save("user", results, "")

        yield {"type": "error", "error": "max_loops", "detail": "เกินจำนวนรอบ tool สูงสุด"}


_runtime: AgentRuntime | None = None


def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime


def build_system_prompt(user, tools: list[ToolDef], tenant_id: str | None = None) -> str:
    settings = get_ai_settings()
    module_list = sorted({t.module for t in tools})
    parts = [
        "คุณคือผู้ช่วย AI ของระบบ pstack ตอบภาษาเดียวกับที่ผู้ใช้ใช้ กระชับ ตรงประเด็น",
        f"ผู้ใช้ปัจจุบัน: {user.full_name or user.email} <{user.email}>",
        "เมื่อคำตอบต้องใช้ข้อมูลจริงในระบบ ให้เรียก tool เสมอ อย่าเดาหรือแต่งข้อมูลเอง "
        "ถ้าไม่มี tool ที่ตอบได้ ให้บอกตรงๆ ว่าข้อมูลส่วนนั้นเข้าถึงไม่ได้",
        f"โมดูลที่มี tools ให้ใช้: {', '.join(module_list) or '(ไม่มี)'}",
    ]
    if tenant_id:
        parts.append(
            f"บทสนทนานี้ทำงานในบริบทของ tenant: {tenant_id} — "
            "ข้อมูลที่ tool คืนมาจะเป็นของ tenant นี้เท่านั้น "
            "ถ้าผู้ใช้ถามถึง tenant อื่น ให้บอกว่าต้องเปิดแชทใหม่ในบริบทของ tenant นั้น"
        )
    if settings.system_extra:
        parts.append(settings.system_extra)
    return "\n\n".join(parts)
