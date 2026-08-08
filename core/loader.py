"""Module loader — discover addons, อ่าน __manifest__.py, จัดลำดับตาม depends แล้ว import

__manifest__.py ต้องเป็น dict literal (อ่านด้วย ast.literal_eval — ไม่ execute โค้ด):

    {
        "name": "users",
        "version": "1.0.0",
        "depends": [],
        "summary": "...",
    }

โครงไฟล์ในโมดูล (ทุกไฟล์ optional ยกเว้น manifest):
    models.py     — SQLAlchemy models (kernel เก็บรายชื่อตารางของโมดูลไว้ทำ install)
    routes.py     — ต้องมีตัวแปร `router: APIRouter`
    tools.py      — ลงทะเบียน AI tools ผ่าน @agent_tool
    hooks.py      — async def on_install(session), on_upgrade(session, from_version)
    templates/    — Jinja2 (อ้างชื่อแบบ "module_name/xxx.html")
    static/       — mount ที่ /static/<module_name>/
"""

from __future__ import annotations

import ast
import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.db import Base

logger = logging.getLogger(__name__)


class ModuleError(Exception):
    pass


# module name -> รายชื่อตาราง (คงอยู่ตลอดโปรเซส — import ซ้ำแล้ว diff metadata จะว่าง)
_module_tables_cache: dict[str, list[str]] = {}


@dataclass
class ModuleInfo:
    name: str
    path: Path
    manifest: dict
    package: str
    tables: list[str] = field(default_factory=list)
    hooks: ModuleType | None = None

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", "0.0.0"))

    @property
    def depends(self) -> list[str]:
        return list(self.manifest.get("depends", []))


def discover(addons_paths: list[str]) -> dict[str, ModuleInfo]:
    """รองรับหลาย addons path — รวม path นอกโปรเจกต์ (เช่น app repo แยกที่ใช้ pstack เป็นฐาน)

    ชื่อโฟลเดอร์ base ต้องไม่ซ้ำกัน (ใช้เป็น python package prefix) เช่น
    PSTACK_ADDONS_PATHS=/srv/pstack/addons,vdo_addons — ห้ามมี "addons" สองอัน
    """
    found: dict[str, ModuleInfo] = {}
    seen_bases: dict[str, Path] = {}
    for base in addons_paths:
        base_path = Path(base).resolve()
        if not base_path.is_dir():
            continue
        if base_path.name in seen_bases and seen_bases[base_path.name] != base_path:
            raise ModuleError(
                f"ชื่อโฟลเดอร์ addons ซ้ำกัน: '{base_path.name}' "
                f"({seen_bases[base_path.name]} กับ {base_path}) — "
                "ตั้งชื่อ dir ให้ต่างกัน เช่น addons กับ vdo_addons"
            )
        seen_bases[base_path.name] = base_path

        # ให้ package "<base_dir>.<module>" import ได้แม้ base อยู่นอก cwd
        parent = str(base_path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for child in sorted(base_path.iterdir()):
            manifest_file = child / "__manifest__.py"
            if not (child.is_dir() and manifest_file.exists()):
                continue
            try:
                manifest = ast.literal_eval(manifest_file.read_text())
            except (ValueError, SyntaxError) as e:
                raise ModuleError(f"manifest ของ '{child.name}' ไม่ใช่ dict literal: {e}") from e
            if not isinstance(manifest, dict):
                raise ModuleError(f"manifest ของ '{child.name}' ต้องเป็น dict")
            name = child.name  # ชื่อโมดูล = ชื่อโฟลเดอร์เสมอ
            if name in found:
                logger.warning(
                    "module '%s' ถูก override โดย %s (ทับ %s)", name, base_path, found[name].path
                )
            found[name] = ModuleInfo(
                name=name,
                path=child,
                manifest=manifest,
                package=f"{base_path.name}.{child.name}",
            )
    return found


def resolve_order(targets: list[str], available: dict[str, ModuleInfo]) -> list[str]:
    """Topological sort ของ targets + dependencies ทั้งหมด (DFS, ตรวจ cycle)"""
    order: list[str] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(name: str, chain: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in visiting:
            raise ModuleError(f"dependency วนลูป: {' -> '.join(chain + (name,))}")
        if name not in available:
            raise ModuleError(
                f"ไม่พบโมดูล '{name}' (ต้องการโดย {chain[-1] if chain else 'settings'})"
            )
        visiting.add(name)
        for dep in available[name].depends:
            visit(dep, chain + (name,))
        visiting.discard(name)
        done.add(name)
        order.append(name)

    for target in targets:
        visit(target, ())
    return order


def _import_submodule(info: ModuleInfo, name: str) -> ModuleType | None:
    if not (info.path / f"{name}.py").exists():
        return None
    return importlib.import_module(f"{info.package}.{name}")


def load_module(app: FastAPI, info: ModuleInfo) -> None:
    """Import โมดูลและลงทะเบียนทุก extension point (ไม่แตะ DB — ส่วน DB อยู่ใน registry)"""
    # snapshot ก่อน import ทั้ง package — โมดูลอาจ import models ทางอ้อมตั้งแต่ __init__
    # (cache ไว้เพราะ import ครั้งที่สองในโปรเซสเดิม diff จะว่างเปล่า)
    if info.name in _module_tables_cache:
        importlib.import_module(info.package)
        _import_submodule(info, "models")
        info.tables = _module_tables_cache[info.name]
    else:
        before = set(Base.metadata.tables)
        importlib.import_module(info.package)
        _import_submodule(info, "models")
        info.tables = sorted(set(Base.metadata.tables) - before)
        _module_tables_cache[info.name] = info.tables

    routes = _import_submodule(info, "routes")
    if routes is not None:
        router = getattr(routes, "router", None)
        if router is None:
            raise ModuleError(f"'{info.name}/routes.py' ต้องมีตัวแปร router")
        app.include_router(router)

    _import_submodule(info, "tools")
    _import_submodule(info, "jobs")
    info.hooks = _import_submodule(info, "hooks")

    static_dir = info.path / "static"
    if static_dir.is_dir():
        app.mount(
            f"/static/{info.name}",
            StaticFiles(directory=static_dir),
            name=f"static_{info.name}",
        )
