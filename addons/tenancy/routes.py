"""REST สำหรับจัดการ tenant / member / workspace

- จัดการ (สร้าง tenant, เพิ่ม member) ต้องมีสิทธิ์ `tenancy.manage`
- `/api/tenancy/me` — user คนไหนก็ดู tenant ของตัวเองได้
- endpoint ที่ทำงานในบริบท tenant ใช้ ScopeDep (ต้องส่ง header X-Tenant-Id)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from addons.tenancy import services
from addons.tenancy.deps import ScopeDep, SessionDep
from addons.tenancy.models import Tenant, TenantMember
from core.auth import get_current_user, require_permission
from core.tenancy import InvalidId

router = APIRouter(prefix="/api/tenancy", tags=["tenancy"])

Manage = Depends(require_permission("tenancy.manage"))


class TenantIn(BaseModel):
    tenant_id: str
    display_name: str = ""
    timezone: str = "Asia/Bangkok"


class TenantOut(BaseModel):
    tenant_id: str
    display_name: str
    timezone: str

    model_config = {"from_attributes": True}


class MemberIn(BaseModel):
    user_id: int
    role: str = "member"


class WorkspaceIn(BaseModel):
    workspace_id: str
    display_name: str = ""


@router.post("/tenants", response_model=TenantOut, status_code=201, dependencies=[Manage])
async def create_tenant(body: TenantIn, session: SessionDep) -> Any:
    try:
        tenant = await services.create_tenant(
            session, body.tenant_id, body.display_name, body.timezone
        )
    except InvalidId as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail="tenant_id นี้มีอยู่แล้ว") from e
    await session.commit()
    return tenant


@router.get("/tenants", response_model=list[TenantOut], dependencies=[Manage])
async def list_tenants(session: SessionDep) -> Any:
    result = await session.execute(select(Tenant).order_by(Tenant.tenant_id))
    return list(result.scalars())


@router.post("/tenants/{tenant_id}/members", status_code=201, dependencies=[Manage])
async def add_member(tenant_id: str, body: MemberIn, session: SessionDep) -> dict:
    if await session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="ไม่พบ tenant")
    try:
        await services.add_member(session, tenant_id, body.user_id, body.role)
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail="user นี้เป็นสมาชิกอยู่แล้ว") from e
    await session.commit()
    return {"tenant_id": tenant_id, "user_id": body.user_id, "role": body.role}


@router.get("/me")
async def my_tenants(
    user: Annotated[Any, Depends(get_current_user)], session: SessionDep
) -> dict:
    if getattr(user, "is_superuser", False):
        result = await session.execute(select(Tenant.tenant_id))
        return {"tenants": list(result.scalars()), "superuser": True}
    return {"tenants": await services.tenants_of(session, user.id), "superuser": False}


@router.post("/workspaces", status_code=201)
async def create_workspace(body: WorkspaceIn, scope: ScopeDep, session: SessionDep) -> dict:
    try:
        ws = await services.create_workspace(
            session, scope, body.workspace_id, body.display_name
        )
    except InvalidId as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail="workspace_id นี้มีอยู่แล้ว") from e
    await session.commit()
    return {"workspace_id": ws.workspace_id, "tenant_id": ws.tenant_id}


@router.get("/members")
async def list_members(scope: ScopeDep, session: SessionDep) -> Any:
    from core.tenancy import scoped

    result = await session.execute(
        scoped(select(TenantMember), TenantMember, scope).order_by(TenantMember.user_id)
    )
    return [
        {"user_id": m.user_id, "role": m.role, "tenant_id": m.tenant_id}
        for m in result.scalars()
    ]
