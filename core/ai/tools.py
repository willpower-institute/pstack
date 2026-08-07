"""AI Tool Registry — โมดูลไหนก็ลงทะเบียน tool ให้ agent เรียกได้

ใช้งานใน addons/<module>/tools.py:

    from core.ai import agent_tool

    @agent_tool(module="users", permission="users.read")
    async def count_users(session) -> str:
        \"\"\"นับจำนวนผู้ใช้ในระบบ\"\"\"
        ...

สัญญา (convention):
  - อาร์กิวเมนต์แรกชื่อ session — runtime จะส่ง AsyncSession ให้เอง
  - พารามิเตอร์อื่นต้องมี type hint (str/int/float/bool) — ใช้สร้าง JSON schema
  - docstring คือ description ที่ agent เห็น
  - permission ถูกเช็คกับ user เจ้าของ session ก่อนรันเสมอ

Phase 3 จะเพิ่ม agent runtime (Anthropic SDK tool runner) มาใช้ registry นี้
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class ToolDef:
    name: str
    fn: Callable[..., Awaitable[str]]
    module: str
    description: str
    permission: str | None
    input_schema: dict


_registry: dict[str, ToolDef] = {}


def _build_schema(fn: Callable) -> dict:
    props: dict[str, dict] = {}
    required: list[str] = []
    sig = inspect.signature(fn)
    for pname, param in sig.parameters.items():
        if pname == "session":
            continue
        ann = param.annotation
        json_type = _PY_TO_JSON.get(ann, "string")
        props[pname] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


def agent_tool(module: str, permission: str | None = None):
    def decorator(fn: Callable[..., Awaitable[str]]):
        name = fn.__name__
        if name in _registry:
            raise ValueError(f"agent tool ชื่อซ้ำ: {name} (จาก {_registry[name].module})")
        _registry[name] = ToolDef(
            name=name,
            fn=fn,
            module=module,
            description=inspect.getdoc(fn) or "",
            permission=permission,
            input_schema=_build_schema(fn),
        )
        return fn

    return decorator


def get_tools(modules: list[str] | None = None) -> list[ToolDef]:
    tools = list(_registry.values())
    if modules is not None:
        tools = [t for t in tools if t.module in modules]
    return tools
