"""FastAPI application factory + lifespan

create_app():
  1. discover addons + resolve dependency order จาก PSTACK_MODULES
  2. import ทุกโมดูล + mount routers/static/templates/tools  (ยังไม่แตะ DB)
lifespan (ตอน start ก่อนรับ request):
  3. สร้างตาราง registry -> install/upgrade โมดูลตามลำดับ (สร้างตาราง + hooks)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import get_settings
from core.db import dispose_engine, get_engine, get_sessionmaker
from core.loader import discover, load_module, resolve_order
from core.registry import create_core_tables, sync_modules
from core.runtime import ctx
from core.templating import build_template_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = get_engine()
    await create_core_tables(engine)
    async with get_sessionmaker()() as session:
        await sync_modules(engine, session, ctx.load_order)
    await ctx.events.connect_redis(settings.redis_url)
    logger.info(
        "pstack ready — modules: %s", ", ".join(m.name for m in ctx.load_order) or "(none)"
    )
    yield
    from core.jobs import close_pool

    await ctx.events.close()
    await close_pool()
    await dispose_engine()


# header ที่ปลอดภัยกับทุกหน้าโดยไม่ต้องตั้งค่าอะไรเพิ่ม
# (CSP กับ HSTS ไม่ใส่ให้ที่นี่ — CSP ต้องปรับตามเนื้อหาของแต่ละ deployment
#  ส่วน HSTS ควรตั้งที่ reverse proxy ที่รู้ว่ากำลังเสิร์ฟผ่าน https จริง)
SECURITY_HEADERS = {
    # กันเบราว์เซอร์เดา content-type เอง — สำคัญกับไฟล์ที่ผู้ใช้อัปโหลดมา
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def create_app() -> FastAPI:
    settings = get_settings()
    docs_on = settings.docs_enabled
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        debug=settings.debug,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    ctx.app = app
    ctx.settings = settings

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    ctx.modules = discover(settings.addons_paths_list)
    order = resolve_order(settings.modules_list, ctx.modules)
    ctx.load_order = [ctx.modules[name] for name in order]

    for info in ctx.load_order:
        logger.info("loading module '%s' %s", info.name, info.version)
        load_module(app, info)

    build_template_env(ctx.load_order)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "modules": [m.name for m in ctx.load_order],
        }

    return app
