"""หน้า admin แบบ server-rendered — PRG pattern (POST แล้ว redirect กลับหน้า GET)

flash message ส่งผ่าน query string (?ok=... / ?error=...) เพื่อไม่ต้อง re-render
ในตัว POST handler · ทุกหน้า (ยกเว้น login) ผ่าน dependency require_admin
"""

from __future__ import annotations

import contextlib
import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from addons.admin.deps import (
    AdminDep,
    SessionDep,
    clear_session_cookie,
    has_admin_access,
    set_session_cookie,
    tenancy_enabled,
)
from addons.users import services as user_services
from addons.users.models import Role, User
from core.auth import create_access_token
from core.ratelimit import RateLimited, check_rate_limit, client_ip
from core.templating import render

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

MIN_USER_PASSWORD_LENGTH = 8


def _back(path: str, *, ok: str | None = None, error: str | None = None) -> RedirectResponse:
    query = urlencode({k: v for k, v in (("ok", ok), ("error", error)) if v})
    url = f"{path}?{query}" if query else path
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _page(name: str, request: Request, admin: User, **extra):
    context = {
        "admin": admin,
        "ok": request.query_params.get("ok"),
        "error": request.query_params.get("error"),
        "tenancy_on": tenancy_enabled(),
        **extra,
    }
    return render(f"admin/{name}", context)


# ── auth ────────────────────────────────────────────────────────────────────
@router.get("/admin/login")
async def login_page(request: Request):
    return render("admin/login.html", {"error": request.query_params.get("error")})


@router.post("/admin/login")
async def login_submit(
    request: Request,
    session: SessionDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    ip = client_ip(request)
    acct_key = f"login:acct:{email.lower()}"
    settings_login_fail = "อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือไม่มีสิทธิ์เข้าหน้าผู้ดูแล"
    from core.config import get_settings

    settings = get_settings()
    try:
        await check_rate_limit(f"login:ip:{ip}", settings.login_rate_limit_per_ip, 60)
        await check_rate_limit(
            acct_key, settings.login_rate_limit_per_account, 300, increment=False
        )
    except RateLimited:
        logger.warning("admin login ถูกจำกัดอัตรา ip=%s email=%s", ip, email)
        return render(
            "admin/login.html",
            {"error": "พยายามเข้าสู่ระบบถี่เกินไป ลองใหม่อีกครั้งภายหลัง"},
        )

    user = await user_services.authenticate(session, email, password)
    if user is None or not user.is_active or not has_admin_access(user):
        logger.warning("admin login ล้มเหลว ip=%s email=%s", ip, email)
        with contextlib.suppress(RateLimited):
            await check_rate_limit(acct_key, settings.login_rate_limit_per_account, 300)
        return render("admin/login.html", {"error": settings_login_fail})

    response = _back("/admin", ok="เข้าสู่ระบบแล้ว")
    set_session_cookie(
        response, create_access_token(user.id), secure=request.url.scheme == "https"
    )
    return response


@router.post("/admin/logout")
async def logout(_: AdminDep):
    response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response


# ── dashboard ────────────────────────────────────────────────────────────────
@router.get("/admin")
async def dashboard(request: Request, admin: AdminDep, session: SessionDep):
    user_count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    role_count = (await session.execute(select(func.count()).select_from(Role))).scalar_one()
    tenant_count = None
    if tenancy_enabled():
        from addons.tenancy.models import Tenant

        tenant_count = (
            await session.execute(select(func.count()).select_from(Tenant))
        ).scalar_one()
    module_count = len(ctx_load_order())
    return _page(
        "dashboard.html",
        request,
        admin,
        active="home",
        user_count=user_count,
        role_count=role_count,
        tenant_count=tenant_count,
        module_count=module_count,
    )


def ctx_load_order():
    from core.runtime import ctx

    return ctx.load_order


# ── users ────────────────────────────────────────────────────────────────────
@router.get("/admin/users")
async def users_page(request: Request, admin: AdminDep, session: SessionDep):
    users = list(
        (await session.execute(select(User).order_by(User.id))).scalars()
    )
    roles = list((await session.execute(select(Role).order_by(Role.name))).scalars())
    return _page("users.html", request, admin, active="users", users=users, roles=roles)


@router.post("/admin/users")
async def create_user(
    admin: AdminDep,
    session: SessionDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    full_name: Annotated[str, Form()] = "",
):
    email = email.strip().lower()
    if "@" not in email:
        return _back("/admin/users", error="อีเมลไม่ถูกต้อง")
    if len(password) < MIN_USER_PASSWORD_LENGTH:
        return _back(
            "/admin/users",
            error=f"รหัสผ่านต้องยาวอย่างน้อย {MIN_USER_PASSWORD_LENGTH} ตัวอักษร",
        )
    if await user_services.get_by_email(session, email):
        return _back("/admin/users", error="อีเมลนี้มีอยู่แล้ว")
    await user_services.create_user(session, email, password, full_name.strip())
    return _back("/admin/users", ok=f"สร้างผู้ใช้ {email} แล้ว")


@router.post("/admin/users/{user_id}/roles")
async def set_user_roles(
    user_id: int,
    admin: AdminDep,
    session: SessionDep,
    role_ids: Annotated[list[int], Form()] = [],  # noqa: B006 — FastAPI Form ต้องมี default
):
    user = await session.get(User, user_id)
    if user is None:
        return _back("/admin/users", error="ไม่พบผู้ใช้")
    result = await session.execute(select(Role).where(Role.id.in_(role_ids)))
    user.roles = list(result.scalars())
    await session.commit()
    return _back("/admin/users", ok=f"อัปเดตบทบาทของ {user.email} แล้ว")


@router.post("/admin/users/{user_id}/toggle")
async def toggle_user(user_id: int, admin: AdminDep, session: SessionDep):
    user = await session.get(User, user_id)
    if user is None:
        return _back("/admin/users", error="ไม่พบผู้ใช้")
    if user.id == admin.id:
        return _back("/admin/users", error="ปิดบัญชีตัวเองไม่ได้")
    if user.is_active and user.is_superuser:
        active_supers = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.is_superuser.is_(True), User.is_active.is_(True))
            )
        ).scalar_one()
        if active_supers <= 1:
            return _back("/admin/users", error="ปิด superuser คนสุดท้ายไม่ได้")
    user.is_active = not user.is_active
    await session.commit()
    state = "เปิด" if user.is_active else "ปิด"
    return _back("/admin/users", ok=f"{state}ใช้งานบัญชี {user.email} แล้ว")


# ── roles ────────────────────────────────────────────────────────────────────
@router.get("/admin/roles")
async def roles_page(request: Request, admin: AdminDep, session: SessionDep):
    roles = list((await session.execute(select(Role).order_by(Role.name))).scalars())
    known = sorted(
        {p for m in ctx_load_order() for p in m.manifest.get("permissions", [])}
    )
    return _page("roles.html", request, admin, active="roles", roles=roles, known_permissions=known)


@router.post("/admin/roles")
async def create_role(
    admin: AdminDep,
    session: SessionDep,
    name: Annotated[str, Form()],
    permissions: Annotated[str, Form()] = "",
):
    name = name.strip()
    if not name:
        return _back("/admin/roles", error="ต้องระบุชื่อบทบาท")
    if await session.scalar(select(Role).where(Role.name == name)):
        return _back("/admin/roles", error="ชื่อบทบาทนี้มีอยู่แล้ว")
    perms = sorted({p.strip() for p in permissions.replace(",", " ").split() if p.strip()})
    session.add(Role(name=name, permissions=perms))
    await session.commit()
    return _back("/admin/roles", ok=f"สร้างบทบาท {name} แล้ว")


@router.post("/admin/roles/{role_id}/delete")
async def delete_role(role_id: int, admin: AdminDep, session: SessionDep):
    role = await session.get(Role, role_id)
    if role is None:
        return _back("/admin/roles", error="ไม่พบบทบาท")
    name = role.name
    await session.delete(role)  # user_roles ผูก ondelete CASCADE — assignment หายตาม
    await session.commit()
    return _back("/admin/roles", ok=f"ลบบทบาท {name} แล้ว")


# ── tenants (ต้องเปิดโมดูล tenancy) ──────────────────────────────────────────
@router.get("/admin/tenants")
async def tenants_page(request: Request, admin: AdminDep, session: SessionDep):
    if not tenancy_enabled():
        return _page("tenants.html", request, admin, active="tenants", tenants=[])
    from addons.tenancy.models import Tenant, TenantMember, Workspace

    tenants = list(
        (await session.execute(select(Tenant).order_by(Tenant.tenant_id))).scalars()
    )
    members = list((await session.execute(select(TenantMember))).scalars())
    workspaces = list((await session.execute(select(Workspace))).scalars())
    rows = [
        {
            "tenant": t,
            "members": [m for m in members if m.tenant_id == t.tenant_id],
            "workspaces": [w for w in workspaces if w.tenant_id == t.tenant_id],
        }
        for t in tenants
    ]
    return _page("tenants.html", request, admin, active="tenants", tenants=rows)


@router.post("/admin/tenants")
async def create_tenant(
    admin: AdminDep,
    session: SessionDep,
    tenant_id: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    if not tenancy_enabled():
        return _back("/admin/tenants", error="ยังไม่ได้เปิดโมดูล tenancy")
    from addons.tenancy import services as tenancy_services
    from core.tenancy import InvalidId

    try:
        await tenancy_services.create_tenant(
            session, tenant_id.strip(), display_name.strip()
        )
        await session.commit()
    except InvalidId as e:
        return _back("/admin/tenants", error=str(e))
    except Exception:
        await session.rollback()
        return _back("/admin/tenants", error="สร้าง tenant ไม่สำเร็จ (id ซ้ำ?)")
    return _back("/admin/tenants", ok=f"สร้าง tenant {tenant_id} แล้ว")


@router.post("/admin/tenants/{tenant_id}/members")
async def add_member(
    tenant_id: str,
    admin: AdminDep,
    session: SessionDep,
    user_id: Annotated[int, Form()],
    role: Annotated[str, Form()] = "member",
):
    if not tenancy_enabled():
        return _back("/admin/tenants", error="ยังไม่ได้เปิดโมดูล tenancy")
    from addons.tenancy import services as tenancy_services
    from addons.tenancy.models import Tenant

    if await session.get(Tenant, tenant_id) is None:
        return _back("/admin/tenants", error="ไม่พบ tenant")
    if await session.get(User, user_id) is None:
        return _back("/admin/tenants", error="ไม่พบผู้ใช้")
    try:
        await tenancy_services.add_member(session, tenant_id, user_id, role.strip() or "member")
        await session.commit()
    except Exception:
        await session.rollback()
        return _back("/admin/tenants", error="ผู้ใช้นี้เป็นสมาชิกอยู่แล้ว")
    return _back("/admin/tenants", ok=f"เพิ่มสมาชิก user {user_id} เข้า {tenant_id} แล้ว")


# ── modules (read-only — โมดูลเป็น declarative ผ่าน PSTACK_MODULES) ───────────
@router.get("/admin/modules")
async def modules_page(request: Request, admin: AdminDep, session: SessionDep):
    from core.registry import installed_modules

    installed = {r.name: r.version for r in await installed_modules(session)}
    rows = [
        {
            "name": m.name,
            "version": m.version,
            "installed": installed.get(m.name),
            "depends": m.depends,
            "permissions": m.manifest.get("permissions", []),
        }
        for m in ctx_load_order()
    ]
    return _page("modules.html", request, admin, active="modules", modules=rows)
