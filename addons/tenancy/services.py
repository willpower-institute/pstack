"""Tenant/workspace/membership operations — ใช้ primitives จาก core.tenancy

โมดูลโดเมนควร import scope helper (`TenantScope`, `scoped`, `assert_same_tenant`)
จาก **core.tenancy** ไม่ใช่ที่นี่ — ไฟล์นี้เป็นแค่ CRUD ของ control plane
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.tenancy.models import Tenant, TenantMember, Workspace
from core.tenancy import TenantScope, validate_id


async def create_tenant(
    session: AsyncSession,
    tenant_id: str,
    display_name: str = "",
    timezone: str = "Asia/Bangkok",
) -> Tenant:
    validate_id(tenant_id, "tenant_id")
    tenant = Tenant(
        tenant_id=tenant_id, display_name=display_name or tenant_id, timezone=timezone
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def create_workspace(
    session: AsyncSession, scope: TenantScope, workspace_id: str, display_name: str = ""
) -> Workspace:
    validate_id(workspace_id, "workspace_id")
    ws = Workspace(
        workspace_id=workspace_id, tenant_id=scope.tenant_id, display_name=display_name
    )
    session.add(ws)
    await session.flush()
    return ws


async def add_member(
    session: AsyncSession, tenant_id: str, user_id: int, role: str = "member"
) -> TenantMember:
    member = TenantMember(tenant_id=tenant_id, user_id=user_id, role=role)
    session.add(member)
    await session.flush()
    return member


async def is_member(session: AsyncSession, tenant_id: str, user_id: int) -> bool:
    result = await session.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is not None


async def member_role(session: AsyncSession, tenant_id: str, user_id: int) -> str | None:
    result = await session.execute(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def tenants_of(session: AsyncSession, user_id: int) -> list[str]:
    result = await session.execute(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    return list(result.scalars())
