"""Multi-tenancy primitives ที่ **kernel เป็นเจ้าของ** — ไม่มีตาราง ไม่มี FastAPI

โมดูลโดเมนไหนที่เก็บข้อมูลของ tenant import จากที่นี่:

    from core.tenancy import TenantScope, scoped, assert_same_tenant, validate_id

แยกกับ addon `tenancy` อย่างชัดเจน:
  - `core.tenancy` (ไฟล์นี้)  = สัญญา/ตัวช่วย ที่ทุก addon พึ่งได้ (path-independent)
  - `addons/tenancy/`          = โมดูลติดตั้งได้ (ตาราง tenant/workspace/member + migration + routes)

── id format ──────────────────────────────────────────────────────────────
`ID_PATTERN` ตั้งใจให้ **ตรงกับ `identity/v1 $defs.Id`** ของ agent-platform เป๊ะ
(lowercase, ขึ้นต้นด้วย alphanumeric, ยาวไม่เกิน 63) — consumer ที่มี contract ของตัวเอง
เขียนเทส assert ได้ว่ายังตรงกัน:

    assert core.tenancy.ID_PATTERN.pattern == "<identity/v1 pattern>"

🔒 ห้ามขยับ pattern นี้โดยไม่ประสานกับ consumer — มันเป็น contract ข้าม repo

── RLS ────────────────────────────────────────────────────────────────────
`scoped()` เป็นด่าน app-level (ทุก query ต้องผ่าน) · RLS เป็นด่าน DB-level กันพลาด
ตารางที่เก็บข้อมูล tenant ควรเปิด RLS + FORCE ด้วย `rls_statements()` ใน migration
แล้วตั้ง GUC ต่อ transaction ด้วย `set_tenant()` — policy จะกรองให้เองแม้ลืม scoped()
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncSession

# identity/v1 $defs.Id — ดู docstring ด้านบน ห้ามขยับเดี่ยว
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

# GUC ที่ RLS policy อ่าน — ตั้งด้วย set_tenant() ต่อ transaction
TENANT_GUC = "pstack.tenant_id"


class InvalidId(ValueError):
    pass


class TenantIsolationError(PermissionError):
    """ข้าม tenant — เป็นความผิดพลาดร้ายแรงเสมอ ไม่ใช่แค่ 403 ธรรมดา"""


def validate_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise InvalidId(
            f"{field} ไม่ตรงรูปแบบ identity/v1 $defs.Id "
            f"(lowercase, ขึ้นต้นด้วย alphanumeric, ยาวไม่เกิน 63): {value!r}"
        )
    return value


def new_id(prefix: str) -> str:
    """สร้าง id ใหม่ที่ตรง pattern — prefix ช่วยให้อ่าน log ออกว่าเป็นของอะไร"""
    return validate_id(f"{prefix}-{uuid.uuid4().hex[:16]}", prefix)


@dataclass(frozen=True)
class Principal:
    """identity/v1 $defs.Principal — ใครเป็นคนทำ action นี้"""

    type: str  # human | agent | service
    id: str
    display_name: str = ""

    def as_dict(self) -> dict:
        return {"type": self.type, "id": self.id, "display_name": self.display_name}


@dataclass(frozen=True)
class TenantScope:
    """context ขั้นต่ำของทุก request ที่แตะข้อมูลของ tenant (identity/v1 RequestContext)"""

    tenant_id: str
    principal: Principal
    workspace_id: str | None = None
    correlation_id: str | None = None


def scoped(stmt: Select, model: type, scope: TenantScope) -> Select:
    """เติมเงื่อนไข tenant ให้ query — ทุก query ที่อ่านข้อมูลของ tenant ต้องผ่านตัวนี้

    🔒 ห้าม select() ตารางที่มี tenant_id ตรง ๆ ในโค้ดโดเมน — ใช้ scoped() เสมอ
       (RLS เป็นตาข่ายรองอีกชั้น แต่ scoped() คือด่านที่ตั้งใจ)
    """
    column = getattr(model, "tenant_id", None)
    if column is None:
        raise TypeError(
            f"{model.__name__} ไม่มีคอลัมน์ tenant_id — ตารางที่เก็บข้อมูลของ tenant ต้องมีเสมอ"
        )
    return stmt.where(column == scope.tenant_id)


def assert_same_tenant(scope: TenantScope, row: object) -> None:
    """กันการหยิบ object จากที่อื่นมาใช้ข้าม tenant"""
    row_tenant = getattr(row, "tenant_id", None)
    if row_tenant != scope.tenant_id:
        raise TenantIsolationError(
            f"ข้าม tenant: scope={scope.tenant_id} แต่ข้อมูลเป็นของ {row_tenant}"
        )


def rls_statements(table: str, tenant_column: str = "tenant_id") -> list[str]:
    """SQL เปิด RLS + FORCE + policy กรองตาม GUC — idempotent (สั่งซ้ำได้)

    ใช้ใน migration **นอก** guard has_table เสมอ เพื่อให้ deployment ที่ adopt
    (ข้าม create_table) ก็ได้ RLS ครบ ไม่ใช่แค่ deploy ใหม่

        for stmt in rls_statements("appointment"):
            op.execute(stmt)

    policy ใช้ current_setting(..., true) → ถ้าไม่ได้ตั้ง GUC จะได้ค่าว่าง = เห็น 0 แถว
    (deny by default — ปลอดภัยกว่าเปิดหมดเมื่อลืมตั้ง scope)
    """
    policy = f"{table}_tenant_isolation"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {policy} ON {table}",
        f"CREATE POLICY {policy} ON {table} "
        f"USING ({tenant_column} = current_setting('{TENANT_GUC}', true))",
    ]


async def set_tenant(session: AsyncSession, tenant_id: str) -> None:
    """ตั้ง GUC ให้ RLS policy กรองตาม tenant นี้ ใน transaction ปัจจุบัน (Postgres)

    ใช้ set_config(..., is_local=true) → มีผลเฉพาะใน transaction นี้ (ปลอดภัยกับ pool)
    บน sqlite เป็น no-op (ไม่มี RLS/GUC) — scoped() ยังทำงานตามปกติ
    """
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT set_config(:k, :v, true)"), {"k": TENANT_GUC, "v": tenant_id}
    )
