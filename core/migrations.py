"""Alembic per-module — โมดูลละหนึ่ง script directory + version table ของตัวเอง

    addons/<name>/migrations/
    ├── env.py            (generate อัตโนมัติ — อ่าน connection จาก config.attributes)
    ├── script.py.mako
    └── versions/*.py

version table: alembic_version_<name> — แต่ละโมดูลมี lineage อิสระ ไม่ชนกัน
โมดูลที่ "ไม่มี" โฟลเดอร์ migrations จะ fallback เป็น create-table-on-install ตามเดิม

การเทียบ schema (autogenerate) กรองเฉพาะตารางของโมดูลนั้น (include_object)
จึงไม่เห็นตารางของโมดูลอื่นเป็นของแปลกปลอม
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from core.loader import ModuleInfo

logger = logging.getLogger(__name__)

_ENV_PY = '''"""alembic env — generate โดย pstack อย่าเรียกด้วย alembic CLI ตรงๆ
ใช้ผ่าน `python cli.py makemigration/migrate` เท่านั้น (connection ถูกส่งมาทาง attributes)
"""
from alembic import context

from core.db import Base

config = context.config
module_tables = config.attributes.get("module_tables")


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        if name.startswith("alembic_version"):
            return False
        if module_tables is not None:
            return name in module_tables
    return True


connection = config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    version_table=config.get_main_option("version_table"),
    include_object=include_object,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
'''

_SCRIPT_MAKO = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
import sqlalchemy as sa
from alembic import op
${imports + "\n" if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


def migrations_dir(info: ModuleInfo) -> Path:
    return info.path / "migrations"


def has_migrations(info: ModuleInfo) -> bool:
    return (migrations_dir(info) / "env.py").exists()


def revision_is_empty(path: Path) -> bool:
    """revision ไม่มีคำสั่ง schema เลย (ไม่มี op.) — issue #7"""
    return "op." not in path.read_text()


def ensure_scaffold(info: ModuleInfo) -> None:
    mig = migrations_dir(info)
    (mig / "versions").mkdir(parents=True, exist_ok=True)
    if not (mig / "env.py").exists():
        (mig / "env.py").write_text(_ENV_PY)
    if not (mig / "script.py.mako").exists():
        (mig / "script.py.mako").write_text(_SCRIPT_MAKO)


def _build_config(info: ModuleInfo) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir(info)))
    cfg.set_main_option("version_table", f"alembic_version_{info.name}")
    return cfg


async def upgrade_to_head(engine: AsyncEngine, info: ModuleInfo) -> None:
    cfg = _build_config(info)

    def _run(conn: Connection) -> None:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    logger.info("module '%s': migrations upgraded to head", info.name)


async def stamp(engine: AsyncEngine, info: ModuleInfo, rev: str = "head") -> None:
    """บันทึกว่าโมดูลนี้อยู่ที่ revision `rev` โดย **ไม่รันคำสั่ง schema**

    ใช้ตอน adopt ตารางที่มีอยู่แล้วเข้าสู่การจัดการของ alembic — เขียน/อัปเดต
    version table `alembic_version_<name>` ให้ชี้ head โดยไม่ create/alter อะไร

    หมายเหตุ: path ของ addon `tenancy` ไม่ต้องพึ่ง stamp เพราะ initial migration
    เป็น idempotent (เจอตารางแล้วข้าม) — alembic บันทึก revision ให้เองตอนรัน ·
    stamp มีไว้สำหรับเคส adopt อื่น / rollback / ซ่อม version table ที่หลุด
    """
    cfg = _build_config(info)

    def _run(conn: Connection) -> None:
        cfg.attributes["connection"] = conn
        command.stamp(cfg, rev)

    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    logger.info("module '%s': stamped to %s", info.name, rev)


async def autogenerate(engine: AsyncEngine, info: ModuleInfo, message: str) -> None:
    """สร้าง revision ใหม่จาก diff ระหว่าง models กับ DB (เฉพาะตารางของโมดูลนี้)"""
    ensure_scaffold(info)
    cfg = _build_config(info)
    cfg.attributes["module_tables"] = set(info.tables)

    def _run(conn: Connection) -> None:
        cfg.attributes["connection"] = conn
        command.revision(cfg, message=message, autogenerate=True)

    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
