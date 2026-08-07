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
    (target / "hooks.py").write_text(HOOKS_TMPL)
    (target / "templates").mkdir()
    (target / "static").mkdir()

    typer.secho(f"สร้างโมดูล '{name}' แล้วที่ {target}", fg="green")
    typer.echo(f"เพิ่ม '{name}' เข้า PSTACK_MODULES ใน .env เพื่อเปิดใช้งาน")


if __name__ == "__main__":
    app()
