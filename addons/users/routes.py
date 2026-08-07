from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.users import services
from addons.users.models import User
from core.auth import create_access_token, get_current_user, require_permission
from core.db import get_session

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
    data: LoginIn, session: Annotated[AsyncSession, Depends(get_session)]
) -> TokenOut:
    user = await services.authenticate(session, data.email, data.password)
    if user is None or not user.is_active:
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
