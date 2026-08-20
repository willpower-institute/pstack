import contextlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.users import services
from addons.users.models import User
from core.auth import create_access_token, get_current_user, require_permission
from core.config import get_settings
from core.db import get_session
from core.ratelimit import RateLimited, check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool

    model_config = {"from_attributes": True}


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""


@router.post("/api/auth/login", response_model=TokenOut)
async def login(
    data: LoginIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    acct_key = f"login:acct:{data.email.lower()}"
    try:
        # ต่อ IP นับทุกครั้ง — กันคนเดียวไล่ยิงหลายบัญชี (credential stuffing)
        await check_rate_limit(
            f"login:ip:{client_ip}", settings.login_rate_limit_per_ip, 60
        )
        # ต่อบัญชีนับเฉพาะครั้งที่ล้มเหลว — ผู้ใช้จริงที่ล็อกอินถูกไม่โดนกวน
        # เช็คก่อนเรียก authenticate() เพราะ bcrypt กิน CPU ~300ms ต่อครั้ง
        await check_rate_limit(
            acct_key, settings.login_rate_limit_per_account, 300, increment=False
        )
    except RateLimited as e:
        logger.warning("login ถูกจำกัดอัตรา ip=%s email=%s", client_ip, data.email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="พยายามเข้าสู่ระบบถี่เกินไป ลองใหม่อีกครั้งภายหลัง",
            headers={"Retry-After": str(e.retry_after)},
        ) from e

    user = await services.authenticate(session, data.email, data.password)
    if user is None or not user.is_active:
        # เดิมไม่มี log อะไรเลย — ตรวจย้อนหลังว่าถูกเดารหัสไม่ได้
        logger.warning("login ล้มเหลว ip=%s email=%s", client_ip, data.email)
        with contextlib.suppress(RateLimited):
            # นับความล้มเหลวไว้ ครั้งถัดไปจะโดนกันตั้งแต่ก่อนเรียก bcrypt
            await check_rate_limit(
                acct_key, settings.login_rate_limit_per_account, 300
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/api/users/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.get("/api/users", response_model=list[UserOut])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[User, Depends(require_permission("users.read"))],
) -> list[User]:
    result = await session.execute(select(User).order_by(User.id))
    return list(result.scalars())


@router.post("/api/users", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[User, Depends(require_permission("users.write"))],
) -> User:
    if await services.get_by_email(session, data.email):
        raise HTTPException(status_code=409, detail="email already exists")
    return await services.create_user(session, data.email, data.password, data.full_name)
