"""Tenant / Workspace / Membership — **control plane** ของ multi-tenancy

ตารางกลาง (ไม่มี prefix `ap_`) — ชื่อ constraint/index ตั้ง explicit ให้ตรงกับ
initial migration เป๊ะ เพื่อให้ deployment ที่ adopt (rename ตารางเดิมมา) มีชื่อ
ตรงกับ deploy ใหม่ — ไม่งั้น revision ถัดไปที่ drop_constraint จะพังเฉพาะที่ adopt

🔒 ตาราง 3 ตัวนี้เป็น control plane — ป้องกันด้วย membership check + superuser
   **ไม่เปิด RLS** (ถ้าเปิด จะอ่าน membership เพื่อสร้าง scope ไม่ได้ = ตายตอนบูต)
   RLS มีไว้สำหรับตาราง **ข้อมูลโดเมน** ที่มี tenant_id — ใช้ core.tenancy.rls_statements()
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.clock import now as _now
from core.db import Base


class Tenant(Base):
    """ขอบเขต isolation แข็ง — ห้ามข้ามเด็ดขาด (identity/v1 · agent-platform ADR-0007)"""

    __tablename__ = "tenant"

    tenant_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Workspace(Base):
    """ขอบเขตงานภายใน tenant — `Project`/`Department` เป็น label ของ workspace ไม่ใช่ชั้นใหม่"""

    __tablename__ = "workspace"

    workspace_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(63),
        ForeignKey("tenant.tenant_id", ondelete="CASCADE", name="workspace_tenant_id_fkey"),
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TenantMember(Base):
    """ผูก user ของ pstack เข้ากับ tenant — user ที่ไม่ได้เป็นสมาชิก เข้า tenant นั้นไม่ได้เลย"""

    __tablename__ = "tenant_member"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(63),
        ForeignKey("tenant.tenant_id", ondelete="CASCADE", name="tenant_member_tenant_id_fkey"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(default=_now)
