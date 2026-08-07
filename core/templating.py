"""Namespaced Jinja2 templating — โมดูลละหนึ่ง namespace

โมดูลที่มีโฟลเดอร์ templates/ อ้างเทมเพลตแบบ "module_name/page.html"
(รองรับ override ข้ามโมดูลภายหลังด้วยการวาง path ซ้อนใน ChoiceLoader)
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, PrefixLoader, select_autoescape

from core.loader import ModuleInfo
from core.runtime import ctx


def build_template_env(modules: list[ModuleInfo]) -> Environment:
    mapping = {
        info.name: FileSystemLoader(info.path / "templates")
        for info in modules
        if (info.path / "templates").is_dir()
    }
    env = Environment(
        loader=PrefixLoader(mapping),
        autoescape=select_autoescape(["html", "xml"]),
    )
    ctx.jinja_env = env
    return env


def render(template: str, context: dict[str, Any] | None = None) -> HTMLResponse:
    if ctx.jinja_env is None:
        raise RuntimeError("template env ยังไม่ถูกสร้าง")
    html = ctx.jinja_env.get_template(template).render(context or {})
    return HTMLResponse(html)
