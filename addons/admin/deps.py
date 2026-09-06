"""Cookie session + dependency สำหรับหน้า admin (server-rendered)

pstack auth หลักเป็น Bearer-only (Authorization header) ซึ่งเบราว์เซอร์ไม่ส่งมาตอน
navigate หน้าเว็บ — โมดูลนี้จึงเก็บ JWT เดิม (core.auth) ไว้ใน cookie HttpOnly แทน
ไม่แตะ core auth เลย · หน้า admin ต้องการสิทธิ์ `admin.access` (superuser ผ่านเสมอ)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from addons.users.models import User
from core.auth import decode_access_token
from core.config import get_settings
from core.db import get_session
from core.runtime import ctx

COOKIE_NAME = "pstack_admin"
LOGIN_PATH = "/admin/login"
# cookie อายุเท่า JWT (นาที → วินาที)
COOKIE_MAX_AGE = get_settings().access_token_expire_minutes * 60


def has_admin_access(user: User) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    perms = {p for role in getattr(user, "roles", []) for p in (role.permissions or [])}
    return "admin.access" in perms


def set_session_cookie(response, token: str, *, secure: bool) -> None:
    """ตั้ง cookie session — HttpOnly กัน JS อ่าน, SameSite=Lax กัน CSRF ข้ามไซต์

    `secure` ให้ผู้เรียกส่งจาก scheme จริงของ request (https เท่านั้น) — ตั้งจาก
    request.url.scheme เพื่อให้ทำงานทั้งหลัง reverse proxy (X-Forwarded-Proto=https)
    และไม่พังบน http (dev/เทส) ที่ Secure cookie จะไม่ถูกส่ง
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/admin",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/admin")


class _RedirectToLogin(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="ต้องล็อกอินก่อน",
            headers={"Location": LOGIN_PATH},
        )


async def require_admin(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> User:
    """คืน user ที่ล็อกอินและมีสิทธิ์ admin — ไม่ผ่านเงื่อนไขไหนก็ redirect ไปหน้า login"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _RedirectToLogin()
    try:
        user_id = decode_access_token(token)
    except HTTPException:
        raise _RedirectToLogin() from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active or not has_admin_access(user):
        raise _RedirectToLogin()
    return user


AdminDep = Annotated[User, Depends(require_admin)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def tenancy_enabled() -> bool:
    """โมดูล tenancy ถูกเปิดใน PSTACK_MODULES หรือไม่ (หน้า tenants พึ่งอันนี้)"""
    return any(m.name == "tenancy" for m in ctx.load_order)
