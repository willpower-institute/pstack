"""MCP server แบบ stateless — JSON-RPC 2.0 ตาม Model Context Protocol

รองรับ method: initialize, ping, tools/list, tools/call (+ notifications = รับทิ้ง)
tools มาจาก core.ai registry กรองตามสิทธิ์ของ user เจ้าของ token — ตัวเดียวกับที่
agent ภายในใช้ ดังนั้นโมดูลใหม่เพิ่ม tool ปุ๊บ MCP client ภายนอกเห็นทันที
"""

from __future__ import annotations

import logging
from typing import Any

from addons.ai_agent.services import TenantNotAllowed, authorize_tenant, tools_for_user
from core.db import get_sessionmaker
from core.tenancy import bind_tenant

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "pstack", "version": "0.1.0"}


def _result(rpc_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _error(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _call_tool(
    tool, arguments: dict, user=None, tenant_id: str | None = None
) -> tuple[str, bool]:
    try:
        async with get_sessionmaker()() as db:
            if tenant_id:
                # ตรวจ membership ก่อน bind — ห้ามเชื่อ header ลอย ๆ
                try:
                    await authorize_tenant(db, user, tenant_id)
                except TenantNotAllowed as e:
                    return str(e), True
                await bind_tenant(db, tenant_id)
            output = await tool.fn(db, **arguments)
        return str(output), False
    except Exception as e:
        logger.exception("mcp tool '%s' failed", tool.name)
        return f"tool error: {e}", True


async def handle_rpc(user, payload: Any, tenant_id: str | None = None) -> dict | None:
    """คืน dict = JSON-RPC response, คืน None = notification (ตอบ 202 เปล่า)"""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid request (expect single JSON-RPC 2.0 object)")

    method = payload.get("method", "")
    params = payload.get("params") or {}

    if "id" not in payload:  # notification เช่น notifications/initialized
        return None
    rpc_id = payload["id"]

    if method == "initialize":
        return _result(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "pstack tools — สิทธิ์ตาม user เจ้าของ token; "
                    "เรียก tools/list เพื่อดูว่าใช้อะไรได้บ้าง"
                ),
            },
        )

    if method == "ping":
        return _result(rpc_id, {})

    if method == "tools/list":
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in tools_for_user(user)
        ]
        return _result(rpc_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        tool = next((t for t in tools_for_user(user) if t.name == name), None)
        if tool is None:
            return _error(rpc_id, -32602, f"unknown or unauthorized tool: {name}")
        output, is_error = await _call_tool(
            tool, arguments, user=user, tenant_id=tenant_id
        )
        return _result(
            rpc_id,
            {"content": [{"type": "text", "text": output}], "isError": is_error},
        )

    return _error(rpc_id, -32601, f"method not found: {method}")
