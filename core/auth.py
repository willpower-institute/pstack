"""Auth kernel — password hashing (bcrypt), JWT (PyJWT), dependencies สำหรับ RBAC

kernel ไม่รู้จักตาราง user — โมดูล users ลงทะเบียน ctx.user_loader ให้ตอน import
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.db import get_session
from core.runtime import ctx

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC)
        + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from e


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if ctx.user_loader is None:
        raise HTTPException(status_code=500, detail="no user module installed")
    token = credentials.credentials

    # โมดูลอาจเสียบวิธี auth เพิ่ม (เช่น API key) — ลองก่อน แล้วค่อย fallback เป็น JWT
    for resolver in ctx.token_resolvers:
        user = await resolver(session, token)
        if user is not None:
            if not getattr(user, "is_active", False):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="user not active"
                )
            return user

    user_id = decode_access_token(token)
    user = await ctx.user_loader(session, user_id)
    if user is None or not getattr(user, "is_active", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


def require_permission(permission: str):
    """Dependency factory: ผู้ใช้ต้องมี permission นี้ (superuser ผ่านเสมอ)

    ใช้: Depends(require_permission("users.read"))
    """

    async def checker(user: Annotated[Any, Depends(get_current_user)]) -> Any:
        if getattr(user, "is_superuser", False):
            return user
        perms: set[str] = set()
        for role in getattr(user, "roles", []):
            perms.update(role.permissions or [])
        if permission not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {permission}",
            )
        return user

    return checker
