from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from addons.api_keys import services
from core.auth import get_current_user
from core.db import get_session

router = APIRouter(prefix="/api/keys", tags=["api_keys"])


class KeyCreateIn(BaseModel):
    name: str


class KeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class KeyCreatedOut(KeyOut):
    key: str  # plaintext — แสดงครั้งเดียวตอนสร้างเท่านั้น


@router.post("", response_model=KeyCreatedOut, status_code=201)
async def create_key(
    data: KeyCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    record, plaintext = await services.create_key(session, user.id, data.name)
    return KeyCreatedOut(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        key=plaintext,
    )


@router.get("", response_model=list[KeyOut])
async def list_keys(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.list_keys(session, user.id)


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    for record in await services.list_keys(session, user.id):
        if record.id == key_id:
            await services.revoke_key(session, record)
            return
    raise HTTPException(status_code=404, detail="key not found")
