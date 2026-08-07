"""pstack CLI

    python cli.py run                 # รัน dev server
    python cli.py modules             # โมดูลที่ discover ได้ + สถานะติดตั้ง
    python cli.py new-module <name>   # สร้างโครง addon ใหม่
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(host: str = "0.0.0.0", port: int = 8000, reload: bool = True) -> None:
    """รัน dev server (uvicorn)"""
    import uvicorn

    uvicorn.run("main:app", host=host, port=port, reload=reload)


@app.command()
def modules() -> None:
    """แสดงโมดูลทั้งหมดที่ discover ได้ พร้อมสถานะจาก DB (ถ้าต่อได้)"""
    from core.config import get_settings
    from core.loader import discover

    settings = get_settings()
    found = discover(settings.addons_paths_list)
    enabled = set(settings.modules_list)

    installed: dict[str, str] = {}
    try:
        installed = asyncio.run(_fetch_installed())
    except Exception as e:  # DB อาจยังไม่ขึ้น — แสดงเฉพาะ discovered
        typer.secho(f"(อ่านสถานะจาก DB ไม่ได้: {e})", fg="yellow")

    for name, info in sorted(found.items()):
        state = installed.get(name)
        mark = "✔ installed " + state if state else ("· enabled" if name in enabled else "· available")
        deps = f"  depends: {', '.join(info.depends)}" if info.depends else ""
        typer.echo(f"{name:<16} {info.version:<8} {mark}{deps}")


async def _fetch_installed() -> dict[str, str]:
    from core.db import dispose_engine, get_sessionmaker
    from core.registry import installed_modules

    try:
        async with get_sessionmaker()() as session:
            records = await installed_modules(session)
            return {r.name: r.version for r in records}
    finally:
        await dispose_engine()


@app.command()
def makemigration(
    module: str,
    message: str = typer.Option("update", "-m", "--message"),
) -> None:
    """สร้าง alembic revision จาก diff ของ models โมดูลนั้นเทียบกับ DB"""
    from core.app import create_app

    create_app()  # import ทุกโมดูล -> metadata + info.tables พร้อม

    from core.db import dispose_engine, get_engine
    from core.runtime import ctx

    info = next((m for m in ctx.load_order if m.name == module), None)
    if info is None:
        typer.secho(
            f"โมดูล '{module}' ไม่อยู่ใน PSTACK_MODULES — เพิ่มใน .env ก่อน", fg="red"
        )
        raise typer.Exit(1)

    async def _run() -> None:
        from core import migrations

        try:
            await migrations.autogenerate(get_engine(), info, message)
        finally:
            await dispose_engine()

    asyncio.run(_run())
    typer.secho(f"สร้าง revision ใหม่ใน addons/{module}/migrations/versions/", fg="green")


@app.command()
def migrate() -> None:
    """apply migrations + install/upgrade ทุกโมดูลตาม PSTACK_MODULES (เหมือนตอนบูต app)"""
    from core.app import create_app

    create_app()

    from core.db import dispose_engine, get_engine, get_sessionmaker
    from core.registry import create_core_tables, sync_modules
    from core.runtime import ctx

    async def _run() -> None:
        engine = get_engine()
        try:
            await create_core_tables(engine)
            async with get_sessionmaker()() as session:
                await sync_modules(engine, session, ctx.load_order)
        finally:
            await dispose_engine()

    asyncio.run(_run())
    typer.secho("migrate เสร็จ", fg="green")


MANIFEST_TMPL = '''{{
    "name": "{name}",
    "version": "0.1.0",
    "depends": ["users"],
    "summary": "",
}}
'''

ROUTES_TMPL = '''from fastapi import APIRouter

router = APIRouter(prefix="/api/{name}", tags=["{name}"])


@router.get("/ping")
async def ping() -> dict:
    return {{"module": "{name}", "status": "ok"}}
'''

TOOLS_TMPL = '''"""AI tools ของโมดูล — ลบไฟล์นี้ได้ถ้าไม่ต้องการ expose อะไรให้ agent

from sqlalchemy.ext.asyncio import AsyncSession

from core.ai import agent_tool


@agent_tool(module="{name}", permission="{name}.read")   # permission=None = สาธารณะ (guest LINE ใช้ได้)
async def search_{name}(session: AsyncSession, query: str) -> str:
    \"\"\"คำอธิบายนี้คือสิ่งที่ agent ใช้ตัดสินใจเรียก tool\"\"\"
    ...
"""
'''

HOOKS_TMPL = '''from sqlalchemy.ext.asyncio import AsyncSession


async def on_install(session: AsyncSession) -> None:
    pass


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    pass
'''


@app.command(name="new-module")
def new_module(name: str, addons_path: str = "addons") -> None:
    """สร้างโครง addon ใหม่ใน addons/<name>"""
    if not name.isidentifier():
        typer.secho(f"ชื่อโมดูลต้องเป็น python identifier: {name}", fg="red")
        raise typer.Exit(1)
    target = Path(addons_path) / name
    if target.exists():
        typer.secho(f"{target} มีอยู่แล้ว", fg="red")
        raise typer.Exit(1)

    target.mkdir(parents=True)
    (target / "__init__.py").write_text("")
    (target / "__manifest__.py").write_text(MANIFEST_TMPL.format(name=name))
    (target / "models.py").write_text("from core.db import Base  # noqa: F401\n")
    (target / "routes.py").write_text(ROUTES_TMPL.format(name=name))
    (target / "tools.py").write_text(TOOLS_TMPL.format(name=name))
    (target / "hooks.py").write_text(HOOKS_TMPL)
    (target / "templates").mkdir()
    (target / "static").mkdir()

    typer.secho(f"สร้างโมดูล '{name}' แล้วที่ {target}", fg="green")
    typer.echo(f"เพิ่ม '{name}' เข้า PSTACK_MODULES ใน .env เพื่อเปิดใช้งาน")


if __name__ == "__main__":
    app()
